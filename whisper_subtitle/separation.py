"""Run the bundled UVR separator in an isolated, managed process."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import time
import wave


class SeparationError(Exception):
    """A separation failure suitable for console display."""


def digest(path: Path) -> str:
    result = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def settings(options: dict, root: Path) -> dict:
    result = {key: options[key] for key in ("denoise", "chunks", "margin")}
    for key in ("executable_path", "model_path"):
        path = Path(options[key]).expanduser()
        path = (root / path).resolve() if not path.is_absolute() else path.resolve()
        if not path.is_file():
            raise SeparationError(f"Separation resource not found: {path}")
        result[key] = str(path)
        result[key + "_sha256"] = digest(path)
    result.update(version=1, sample_rate=44100, channels=2, n_fft=6144, dim_t=8, dim_f=2048)
    return result


def wav_info(path: Path) -> tuple[int, int, int]:
    with wave.open(str(path), "rb") as audio:
        info = audio.getnframes(), audio.getframerate(), audio.getnchannels()
        if info[0] <= 0 or info[1:] != (44100, 2) or audio.getsampwidth() != 2:
            raise ValueError("Expected nonempty stereo 44.1 kHz PCM16 audio")
        # Check the declared samples are actually present.
        remaining = info[0]
        while remaining:
            count = min(remaining, 65536)
            if len(audio.readframes(count)) != count * 4:
                raise ValueError("Truncated WAV data")
            remaining -= count
        return info


def extract_audio(source: Path, destination: Path) -> None:
    import av

    with av.open(str(source)) as container, wave.open(str(destination), "wb") as output:
        if not container.streams.audio:
            raise SeparationError("The media file has no audio stream.")
        output.setparams((2, 2, 44100, 0, "NONE", "not compressed"))
        resampler = av.AudioResampler(format="s16", layout="stereo", rate=44100)
        for frame in container.decode(audio=0):
            for converted in resampler.resample(frame):
                output.writeframesraw(converted.to_ndarray().tobytes())
        for converted in resampler.resample(None):
            output.writeframesraw(converted.to_ndarray().tobytes())
    wav_info(destination)


def run_process(command: list[str], directory: Path, log_path: Path) -> None:
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    environment = os.environ.copy()
    # Keep the frozen application's own runtime isolated from the caller.
    environment.pop("PYTHONHOME", None)
    environment.pop("PYTHONPATH", None)
    runtime = Path(command[0]).resolve().parent
    environment["NUMBA_CACHE_DIR"] = str(runtime / "numba-cache")
    environment["PYTHONUNBUFFERED"] = "1"
    with log_path.open("w", encoding="utf-8") as log:
        process = subprocess.Popen(command, cwd=runtime, stdout=log, stderr=subprocess.STDOUT,
                                   env=environment, creationflags=flags)
        started = time.monotonic()
        next_report = started + 10
        try:
            while True:
                try:
                    code = process.wait(timeout=1)
                    break
                except subprocess.TimeoutExpired:
                    if time.monotonic() >= next_report:
                        print(f"Separating vocals... {time.monotonic() - started:.0f} seconds elapsed", flush=True)
                        next_report = time.monotonic() + 10
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
    if code:
        raise SeparationError(f"Vocal separation failed (exit code {code}). See: {log_path}")


def separate(source: Path, cache_root: Path, policy: dict) -> Path:
    signature = hashlib.sha256(json.dumps(policy, sort_keys=True).encode()).hexdigest()
    directory = cache_root / "separation" / signature
    directory.mkdir(parents=True, exist_ok=True)
    vocals = directory / "vocals.wav"
    manifest_path = directory / "result.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest["settings"] == policy and tuple(manifest["audio"]) == wav_info(vocals) and manifest["sha256"] == digest(vocals):
            print(f"Reusing separated vocals: {vocals}", flush=True)
            return vocals
    except (OSError, ValueError, KeyError, TypeError, wave.Error, EOFError):
        pass
    mixture = directory / "mixture.wav"
    generated = directory / "mixture.wav_vocals.wav"
    accompaniment = directory / "mixture.wav_no_vocals.wav"
    try:
        print("Extracting stereo audio for vocal separation...", flush=True)
        extract_audio(source, mixture)
        expected = wav_info(mixture)
        generated.unlink(missing_ok=True)
        accompaniment.unlink(missing_ok=True)
        command = [policy["executable_path"], str(mixture), "--model_path", policy["model_path"],
                   "--chunks", str(policy["chunks"]), "--margin", str(policy["margin"]),
                   "--n_fft", "6144", "--dim_t", "8", "--dim_f", "2048"]
        if not policy["denoise"]:
            command.append("--no-denoise")
        print("Separating vocals with UVR_MDXNET_KARA_2...", flush=True)
        run_process(command, directory, directory / "separator.log")
        actual = wav_info(generated)
        if abs(actual[0] - expected[0]) > 4410:
            raise SeparationError("Separated audio duration differs from the source by more than 0.1 seconds.")
        generated.replace(vocals)
        manifest = {"settings": policy, "audio": actual, "sha256": digest(vocals)}
        temporary = manifest_path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        temporary.replace(manifest_path)
        for path in (mixture, accompaniment):
            path.unlink(missing_ok=True)
        print("Vocal separation completed.", flush=True)
        return vocals
    except SeparationError:
        raise
    except Exception as exc:
        raise SeparationError(f"Vocal separation failed: {exc}. See: {directory / 'separator.log'}") from exc


def export_vocals(source: Path, destination: Path) -> None:
    if source.resolve() == destination.resolve():
        raise SeparationError("The vocal export path conflicts with the source audio.")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + ".tmp")
    shutil.copyfile(source, temporary)
    temporary.replace(destination)
    print(f"Separated vocals: {destination}", flush=True)
