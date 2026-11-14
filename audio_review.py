"""Review a few suspect regions without re-running whole-file transcription."""
from __future__ import annotations

from pathlib import Path
import re

REVIEW_VERSION = 2


def lexical_speech(text: str) -> bool:
    from subtitle_processing import sound_key, contains_emoji
    if contains_emoji(text) or sound_key(text) is not None:
        return False
    compact = "".join(c for c in unicodedata.normalize("NFKC", text) if c.isalnum())
    vocal = set("あいうえおぁぃぅぇぉんっーはふへほアウオアイエンッハフヘホァィゥェォ")
    return len(compact) >= 2 and any(c not in vocal for c in compact)


def preceding_context(segment: dict, segments: list[dict]) -> str:
    rows = [row for row in segments if segment["start"] - 180 <= row["end"] <= segment["start"]
            and lexical_speech(row["text"]) and row.get("audio_review", {}).get("status") != "omitted"]
    return "\n".join(row["text"] for row in rows[-8:])[-600:]


def decode_window(source: Path, start: float, end: float):
    import av
    import numpy as np

    chunks = []
    with av.open(str(source)) as container:
        stream = container.streams.audio[0]
        origin = float(stream.start_time or 0) * stream.time_base
        begin, finish = max(0.0, start) + origin, end + origin
        container.seek(max(0, int(begin / stream.time_base)), stream=stream)
        resampler = av.AudioResampler(format="s16", layout="mono", rate=16000)
        for frame in container.decode(audio=0):
            if frame.time is not None and frame.time > finish + 0.1:
                break
            for converted in resampler.resample(frame):
                time = converted.time
                if time is None:
                    continue
                samples = converted.to_ndarray().reshape(-1)
                first = max(0, round((begin - time) * 16000))
                last = min(len(samples), round((finish - time) * 16000))
                if last > first:
                    chunks.append(samples[first:last])
    if not chunks:
        raise ValueError(f"Could not decode audio region: {start:.2f}-{end:.2f}")
    return np.concatenate(chunks).astype(np.float32) / 32768.0


def speech_seconds(audio) -> float:
    from faster_whisper.vad import get_speech_timestamps

    regions = get_speech_timestamps(audio, threshold=0.1, min_speech_duration_ms=100,
                                    min_silence_duration_ms=100, speech_pad_ms=0)
    return sum(item["end"] - item["start"] for item in regions) / 16000


def is_intro_candidate(segment: dict, segments: list[dict]) -> bool:
    # These are review candidates only; actual audio decides whether to suppress them.
    return (segment["start"] < 180 and re.search(r"\u3054\u8996\u8074|\u6700\u5f8c\u307e\u3067|\u305d\u308c\u3067\u306f\u307e\u305f", segment["text"]) is not None
            and any(segment["end"] < row["start"] < 180 and re.search(r"\u3053\u3093\u3070\u3093\u306f|\u3053\u3093\u306b\u3061\u306f|\u304a\u306f\u3088\u3046", row["text"]) for row in segments))


class ReviewRecognizer:
    def __init__(self, config: dict, *, alternate: bool = False):
        self.config = config
        self.model = None
        self.alternate = alternate

    def transcribe(self, audio, language: str, *, focus: tuple[float, float] | None = None) -> str:
        if self.model is None:
            import ctranslate2
            from faster_whisper import WhisperModel
            import main

            main.prepare_local_runtime()
            settings = main.asr_settings(self.config)
            device = settings["device"]
            if device == "auto":
                device = "cuda" if ctranslate2.get_cuda_device_count() else "cpu"
            compute = settings["compute_type"]
            if compute == "auto":
                compute = settings["automatic_compute_types"][device]
            name, local = main.resolve_model({**self.config, "whisper_model": settings["model"]})
            label = settings["model"]
            if self.alternate and settings["model"] == "large-v2":
                from faster_whisper.utils import download_model
                try:
                    name = download_model("turbo", cache_dir=str(main.resolve_setting(self.config["download_root"])), local_files_only=True)
                    local, label = True, "local turbo"
                except (OSError, ValueError):
                    pass
            print(f"Reviewing suspect audio with {label} ({device})...", flush=True)
            self.model = WhisperModel(name, device=device, compute_type=compute,
                                      download_root=str(main.resolve_setting(self.config["download_root"])), local_files_only=local)
        iterator, _ = self.model.transcribe(audio, language=language, beam_size=5, best_of=1,
                                           temperature=0.0, condition_on_previous_text=False,
                                           vad_filter=False, word_timestamps=focus is not None)
        if focus is None:
            return " ".join(item.text.strip() for item in iterator if item.text.strip())
        words = []
        for item in iterator:
            for word in item.words or []:
                if word.end > focus[0] and word.start < focus[1]:
                    words.append(word.word)
        return "".join(words).strip()


def review_task(source: Path, cache: dict, cache_path: Path, config: dict) -> list[dict]:
    import main
    from subtitle_processing import contains_emoji, is_pure_emoji
    from sakura import is_untranslated_japanese
    from dictionary_rules import source_text

    candidates = []
    for segment in cache["segments"]:
        if is_pure_emoji(segment["text"]):
            continue
        previous = segment.get("audio_review", {})
        requested = segment.get("needs_audio_review", False)
        if previous.get("version") == REVIEW_VERSION and not requested:
            continue
        if previous.get("attempts", 0) >= 2:
            continue
        reason = None
        if contains_emoji(segment["text"]) or contains_emoji(segment.get("zh", "")):
            reason = "mixed_emoji"
        elif requested or is_untranslated_japanese(source_text(segment), segment.get("model_zh", segment.get("zh", ""))):
            reason = "untranslated_japanese"
        elif previous.get("version", 0) < REVIEW_VERSION and previous.get("reason") in {"untranslated_japanese", "mixed_emoji"}:
            reason = previous["reason"]
        elif is_intro_candidate(segment, cache["segments"]):
            reason = "suspect_intro"
        if reason:
            candidates.append((segment, reason))
    if not candidates:
        return []
    backup = cache_path.with_name("task.before-audio-review.json")
    if not backup.exists():
        main.save_json(backup, cache)
    recognizer = ReviewRecognizer(config, alternate=True)
    changes = []
    try:
        for segment, reason in candidates:
            print(f"Checking audio region #{segment['id']} ({main.console_time(segment['start'])}; {reason})...", flush=True)
            padding = 4.0 if reason == "untranslated_japanese" else 1.5 if reason == "mixed_emoji" else .3
            clip_start = max(0, segment["start"] - padding)
            audio = decode_window(source, clip_start, segment["end"] + padding)
            first = max(0, round((segment["start"] - clip_start) * 16000))
            last = min(len(audio), round((segment["end"] - clip_start) * 16000))
            speech = speech_seconds(audio[first:last])
            review = {"version": REVIEW_VERSION, "attempts": segment.get("audio_review", {}).get("attempts", 0) + 1,
                      "reason": reason, "speech_seconds": round(speech, 3)}
            segment.setdefault("original_asr", {key: segment[key] for key in ("text", "start", "end")})
            segment.pop("needs_audio_review", None)
            if speech < .1 and reason in {"suspect_intro", "mixed_emoji"}:
                review["status"] = "omitted"
            else:
                if reason in {"untranslated_japanese", "mixed_emoji"}:
                    focus = (segment["start"] - clip_start - .1, segment["end"] - clip_start + .1)
                    text = recognizer.transcribe(audio, cache["language"], focus=focus)
                else:
                    text = recognizer.transcribe(audio, cache["language"])
                review["recognized_text"] = text
                if text and not contains_emoji(text):
                    if text != segment["text"]:
                        segment["text"] = text
                        segment.pop("zh", None)
                    elif reason in {"untranslated_japanese", "mixed_emoji"}:
                        segment.pop("zh", None)
                    review["status"] = "reviewed"
                elif reason == "mixed_emoji":
                    review["status"] = "omitted"
                    review["note"] = "No reliable text recovered from the corrupted region."
                else:
                    review["status"] = "unresolved"
            segment["audio_review"] = review
            changes.append({"id": segment["id"], **review})
            main.save_json(cache_path, cache)
    finally:
        recognizer.model = None
    return changes
