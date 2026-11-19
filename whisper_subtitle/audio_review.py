"""Review a few suspect regions without re-running whole-file transcription."""
from __future__ import annotations

import json
from pathlib import Path
import re
import unicodedata

REVIEW_VERSION = 4
GAP_REVIEW_VERSION = 1


def lexical_speech(text: str) -> bool:
    from .subtitle_processing import sound_key, contains_emoji
    if contains_emoji(text) or sound_key(text) is not None:
        return False
    compact = "".join(c for c in unicodedata.normalize("NFKC", text) if c.isalnum())
    vocal = set("あいうえおぁぃぅぇぉんっーはふへほアウオアイエンッハフヘホァィゥェォ")
    return len(compact) >= 2 and any(c not in vocal for c in compact)


def preceding_context(segment: dict, segments: list[dict]) -> str:
    rows = [row for row in segments if segment["start"] - 180 <= row["end"] <= segment["start"]
            and lexical_speech(row["text"]) and row.get("audio_review", {}).get("status") != "omitted"]
    return "\n".join(row["text"] for row in rows[-8:])[-600:]


def context_candidate(segment: dict, segments: list[dict]) -> bool:
    return (bool(re.search("飲|のめ|寝て|寝る", segment["text"]))
            and bool(re.search("舐|なめ|耳", preceding_context(segment, segments))))


def isolated_short(segment: dict, segments: list[dict]) -> bool:
    ordered = sorted(segments, key=lambda row: (row["start"], row["end"]))
    index = next((i for i, row in enumerate(ordered) if row["id"] == segment["id"]), -1)
    if not 0 < index < len(ordered) - 1 or not lexical_speech(segment["text"]):
        return False
    before = segment["start"] - ordered[index - 1]["end"]
    after = ordered[index + 1]["start"] - segment["end"]
    return len(segment["text"]) <= 20 and min(before, after) >= 4 and max(before, after) >= 6


def decode_window(source: Path, start: float, end: float, *, channel: str | None = None):
    import av
    import numpy as np

    if channel not in {None,'left','right'}:
        raise ValueError('Audio review channel must be left or right.')
    chunks = []
    with av.open(str(source), metadata_errors='replace') as container:
        stream = container.streams.audio[0]
        origin = float(stream.start_time or 0) * stream.time_base
        begin, finish = max(0.0, start) + origin, end + origin
        container.seek(max(0, int(begin / stream.time_base)), stream=stream)
        resampler = av.AudioResampler(format="s16", layout="stereo" if channel else "mono", rate=16000)
        for frame in container.decode(audio=0):
            if frame.time is not None and frame.time > finish + 0.1:
                break
            for converted in resampler.resample(frame):
                time = converted.time
                if time is None:
                    continue
                samples = converted.to_ndarray().reshape(-1)
                if channel:
                    samples = samples.reshape(-1,2)[:,0 if channel=='left' else 1]
                first = max(0, round((begin - time) * 16000))
                last = min(len(samples), round((finish - time) * 16000))
                if last > first:
                    chunks.append(samples[first:last])
    if not chunks:
        raise ValueError(f"Could not decode audio region: {start:.2f}-{end:.2f}")
    return np.concatenate(chunks).astype(np.float32) / 32768.0


def speech_seconds(audio, *, threshold: float = .1) -> float:
    from faster_whisper.vad import get_speech_timestamps

    regions = get_speech_timestamps(audio, threshold=threshold, min_speech_duration_ms=100,
                                    min_silence_duration_ms=100, speech_pad_ms=0)
    return sum(item["end"] - item["start"] for item in regions) / 16000


def is_intro_candidate(segment: dict, segments: list[dict]) -> bool:
    # These are review candidates only; actual audio decides whether to suppress them.
    return (segment["start"] < 180 and re.search(r"\u3054\u8996\u8074|\u6700\u5f8c\u307e\u3067|\u305d\u308c\u3067\u306f\u307e\u305f", segment["text"]) is not None
            and any(segment["end"] < row["start"] < 180 and re.search(r"\u3053\u3093\u3070\u3093\u306f|\u3053\u3093\u306b\u3061\u306f|\u304a\u306f\u3088\u3046", row["text"]) for row in segments))


def closing_phrase(text: str) -> bool:
    key = ''.join(c for c in unicodedata.normalize('NFKC', text) if c.isalnum())
    return bool(re.fullmatch(r'(?:それでは|では|それじゃあ?)?(?:ご)?視(?:聴)?(?:ありがとう(?:ございました|ございます)?|感謝)?|おやすみ(?:なさい)?|(?:おわり|終わり|おしまい|終了)(?:です)?', key))


def weak_closing(segment: dict, cache: dict, speech: float) -> bool:
    originals = cache.get('refinement', {}).get('originals', {})
    details = segment.get('refinement', {})
    initial = originals.get(str(details.get('parent_id', segment.get('id'))), segment)
    probabilities = [w['probability'] for w in initial.get('words', []) if 'probability' in w]
    strong = (initial.get('avg_logprob', -2) > -.45 and initial.get('no_speech_prob', 1) < .3
              and probabilities and sum(probabilities) / len(probabilities) >= .75)
    weak = (initial.get('no_speech_prob', 0) >= .6 or initial.get('avg_logprob', 0) < -1.2
            or segment.get('audio_review', {}).get('speech_seconds', 1) < .1)
    return not strong and speech < .25 and (weak or speech < .08)


def unsafe_replacement(original: str, candidate: str) -> bool:
    from .sakura import has_unexpected_repetition
    from .source_checks import artifact
    from .subtitle_processing import contains_emoji

    return bool(artifact(candidate) or contains_emoji(candidate)
                or has_unexpected_repetition(candidate, original))


def restore_rejected_reviews(cache: dict, path: Path) -> None:
    """Restore legacy rows in which an accepted review replaced valid text with an artifact."""
    from . import cli
    from .source_checks import artifact
    from .transcript_refinement import SCORES, _clear_translation

    candidates = []
    for row in cache['segments']:
        previous = row.get('audio_review', {})
        original = row.get('original_asr')
        details = row.get('refinement', {})
        accepted_invalid = (previous.get('status') in {'reviewed', 'context_unresolved'}
                            and previous.get('recognized_text') == row['text'])
        filtered_invalid = (previous.get('status') == 'omitted'
                            and previous.get('reason') in {'extreme_repetition', 'malformed_text'}
                            and previous['reason'] == artifact(row['text']))
        if (original and (accepted_invalid or filtered_invalid)
                and details.get('parts', 1) == 1 and len(details.get('parent_ids', [])) <= 1
                and (row['start'], row['end']) == (original['start'], original['end'])
                and lexical_speech(original['text'])
                and not unsafe_replacement(original['text'], original['text'])
                and unsafe_replacement(original['text'], row['text'])):
            candidates.append(row)
    if not candidates:
        return
    old_path = path.with_name('task.before-audio-review.json')
    try:
        old_rows = json.loads(old_path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        old_rows = {}
    old_rows = ({row['id']: row for row in old_rows['segments']}
                if isinstance(old_rows, dict) and old_rows.get('file_hash') == cache.get('file_hash')
                and isinstance(old_rows.get('segments'), list) else {})
    backup = path.with_name('task.before-rejected-audio-review.json')
    if not backup.exists():
        cli.save_json(backup, cache)
    for row in candidates:
        original = row['original_asr']
        old = old_rows.get(row['id'], {})
        for key in (*SCORES, 'words'):
            row.pop(key, None)
        if all(old.get(key) == original[key] for key in ('text', 'start', 'end')):
            row.update({key: old[key] for key in (*SCORES, 'words') if key in old})
        row.update(original)
        row.pop('refinement', None)
        row.pop('source_review', None)
        _clear_translation(row)
        row['audio_review'].update(status='restored', context_checked=True,
                                   note='Restored the input of an earlier review that accepted an invalid candidate.')
    cli.save_json(path, cache)


class ReviewRecognizer:
    def __init__(self, config: dict, *, alternate: bool = False):
        self.config = config
        self.model = None
        self.alternate = alternate
        self.model_name = None

    def _load_model(self):
        if self.model is None:
            import ctranslate2
            from faster_whisper import WhisperModel
            from . import cli as main
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
            self.model_name = label
            self.model = WhisperModel(name, device=device, compute_type=compute,
                                      download_root=str(main.resolve_setting(self.config["download_root"])), local_files_only=local)

    def transcribe(self, audio, language: str, *, focus: tuple[float, float] | None = None, context: str = "") -> str:
        self._load_model()
        iterator, _ = self.model.transcribe(audio, language=language, beam_size=5, best_of=1,
                                           temperature=0.0, condition_on_previous_text=False,
                                           vad_filter=False, word_timestamps=focus is not None,
                                           initial_prompt=context or None)
        if focus is None:
            return " ".join(item.text.strip() for item in iterator if item.text.strip())
        words = []
        for item in iterator:
            for word in item.words or []:
                if word.end > focus[0] and word.start < focus[1]:
                    words.append(word.word)
        return "".join(words).strip()

    def timed(self, audio, language: str, *, context: str = '') -> list[dict]:
        from .transcript_refinement import recognition_fields
        self._load_model()
        iterator, _ = self.model.transcribe(audio, language=language, beam_size=5, best_of=1,
                                          temperature=0.0, condition_on_previous_text=False,
                                          vad_filter=False, word_timestamps=True, initial_prompt=context or None)
        return [{"start": row.start, "end": row.end, "text": row.text.strip(), **recognition_fields(row)}
                for row in iterator]

    def counting(self, audio, *, hinted: bool = True) -> list[dict]:
        """Decode a quiet count once, with a topic hint but no example sequence."""
        return self.short_clip(
            normalize_review_audio(audio, peak_target=.25, max_gain=8, amplify_only=True),
            context='カウントダウン。' if hinted else '',
        )

    def short_clip(self, audio, *, context: str = '') -> list[dict]:
        """Decode one short Japanese window without seeking through it again."""
        from .transcript_refinement import recognition_fields
        self._load_model()
        iterator, _ = self.model.transcribe(audio, language='ja', beam_size=5, best_of=1,
                    temperature=0.0, condition_on_previous_text=False, vad_filter=False, word_timestamps=True,
                    without_timestamps=True,
                    repetition_penalty=1.15,
                    initial_prompt=context or None)
        # This window is shorter than one decoder chunk. Consume it once;
        # repeated seeking through a stretched final word can otherwise stall.
        try:
            row = next(iterator, None)
            return [{'start':row.start,'end':row.end,'text':row.text.strip(),**recognition_fields(row)}] if row else []
        finally:
            iterator.close()


def normalize_review_audio(audio, *, peak_target: float, max_gain: float, amplify_only: bool = False):
    import numpy as np

    peak = float(np.percentile(np.abs(audio), 99.5)) if len(audio) else 0
    if peak <= .0001:
        return audio
    gain = min(max_gain, peak_target / peak)
    if amplify_only:
        gain = max(1, gain)
    return np.clip(audio * gain, -1, 1).astype(np.float32)


def gap_windows(segments: list[dict], speech: list[dict], duration: float) -> list[tuple[float, float]]:
    ordered = sorted(segments, key=lambda row: row["start"])
    gaps, cursor = [], 0.0
    for row in ordered:
        if row["start"] - cursor >= 4:
            gaps.append((cursor, row["start"]))
        cursor = max(cursor, row["end"])
    if duration - cursor >= 4:
        gaps.append((cursor, duration))
    windows = []
    for left, right in gaps:
        for region in speech:
            start, end = region["start"] / 16000, region["end"] / 16000
            if start >= left and end <= right:
                begin, finish = max(left, start - 3), min(right, end + 3)
                if windows and begin <= windows[-1][1] and windows[-1][0] >= left:
                    windows[-1] = (windows[-1][0], max(finish, windows[-1][1]))
                else:
                    windows.append((begin, finish))
    return [(start, min(end, start + 18)) for left, end in windows for start in _window_starts(left, end)]


def _window_starts(start: float, end: float):
    yield start
    while start + 18 < end:
        start += 16
        yield start


def review_gaps(source: Path, cache: dict, cache_path: Path, config: dict) -> list[dict]:
    """Recover lexical speech in untranscribed gaps using audio evidence only."""
    from . import cli as main
    if cache.get("language") != "ja" or config.get("quality", "high") != "high":
        return []
    previous = cache.get("gap_review", {})
    if previous.get("version") == GAP_REVIEW_VERSION and previous.get("complete"):
        return []
    if not previous or previous.get("version") != GAP_REVIEW_VERSION:
        import av
        from faster_whisper.vad import get_speech_timestamps
        with av.open(str(source), metadata_errors='replace') as container:
            duration = container.duration / av.time_base if container.duration else max(row["end"] for row in cache["segments"])
        audio = decode_window(source, 0, duration)
        speech = get_speech_timestamps(audio, threshold=.5, min_speech_duration_ms=150,
                                      min_silence_duration_ms=150, speech_pad_ms=80)
        windows = gap_windows(cache["segments"], speech, duration)
        backup = cache_path.with_name("task.before-gap-review.json")
        if not backup.exists():
            main.save_json(backup, cache)
        previous = {"version": GAP_REVIEW_VERSION, "windows": windows, "next": 0, "added_ids": [], "complete": False}
        cache["gap_review"] = previous
        main.save_json(cache_path, cache)
        del audio
    recognizer = ReviewRecognizer(config)
    added = []
    try:
        for index in range(previous["next"], len(previous["windows"])):
            start, end = previous["windows"][index]
            print(f"Checking transcript gap {index + 1}/{len(previous['windows'])} ({main.console_time(start)})...", flush=True)
            for row in recognizer.timed(decode_window(source, start, end), cache["language"]):
                from .source_checks import artifact
                left, right = max(start, start + row["start"]), min(end, start + row["end"])
                if (right <= left or row["avg_logprob"] < -1 or row["no_speech_prob"] >= .6
                        or artifact(row['text']) or row.get('compression_ratio', 0) > 2.4
                        or not lexical_speech(row["text"])
                        or any(min(right, old["end"]) - max(left, old["start"]) > .1 for old in cache["segments"])):
                    continue
                if closing_phrase(row['text']):
                    clip = decode_window(source, left, right)
                    if weak_closing(row, cache, speech_seconds(clip, threshold=.5)):
                        continue
                item = {"id": max((r["id"] for r in cache["segments"]), default=0) + 1,
                        "start": left, "end": right, "text": row["text"],
                        **{key: row[key] for key in ("avg_logprob", "no_speech_prob", "compression_ratio") if key in row},
                        "words": [{**word, "start": word["start"] + start, "end": word["end"] + start}
                                  for word in row.get("words", [])],
                        "gap_review": {"version": GAP_REVIEW_VERSION, "avg_logprob": row["avg_logprob"], "no_speech_prob": row["no_speech_prob"]}}
                cache["segments"].append(item)
                added.append(item)
                previous["added_ids"].append(item["id"])
            cache["segments"].sort(key=lambda row: (row["start"], row["end"], row["id"]))
            previous["next"] = index + 1
            main.save_json(cache_path, cache)
        previous["complete"] = True
        main.save_json(cache_path, cache)
    finally:
        recognizer.model = None
    return added


def review_task(source: Path, cache: dict, cache_path: Path, config: dict) -> list[dict]:
    from . import cli as main
    from .subtitle_processing import contains_emoji, is_pure_emoji
    from .sakura import is_untranslated_japanese
    from .dictionary_rules import source_text
    from .source_review import review_sources
    from .transcript_refinement import _clear_translation

    restore_rejected_reviews(cache, cache_path)

    safety_changes = review_sources(source, cache, cache_path, config)

    candidates = []
    for segment in cache["segments"]:
        if is_pure_emoji(segment["text"]):
            continue
        previous = segment.get("audio_review", {})
        if previous.get('status') == 'omitted':
            continue
        requested = segment.get("needs_audio_review", False)
        closing = closing_phrase(segment['text']) or closing_phrase(segment.get('original_asr', {}).get('text', ''))
        if closing and previous.get('version') == REVIEW_VERSION and previous.get('closing_checked') and not requested:
            continue
        if previous.get("version", 0) >= 2 and not requested and not closing:
            if previous.get("context_checked") or not context_candidate(segment, cache["segments"]):
                continue
        if previous.get("attempts", 0) >= 2 and not (closing and previous.get('version', 0) < REVIEW_VERSION):
            continue
        reason = None
        if closing:
            reason = 'closing_phrase'
        elif contains_emoji(segment["text"]) or contains_emoji(segment.get("zh", "")):
            reason = "mixed_emoji"
        elif requested or is_untranslated_japanese(source_text(segment), segment.get("model_zh", segment.get("zh", ""))):
            reason = "untranslated_japanese"
        elif previous.get("version", 0) < REVIEW_VERSION and previous.get("reason") in {"untranslated_japanese", "mixed_emoji"}:
            reason = previous["reason"]
        elif is_intro_candidate(segment, cache["segments"]):
            reason = "suspect_intro"
        elif not previous.get("version") and isolated_short(segment, cache["segments"]):
            reason = "isolated_short"
        elif not previous.get("context_checked") and context_candidate(segment, cache["segments"]):
            reason = "context_mismatch"
        if reason:
            candidates.append((segment, reason))
    if not candidates:
        return safety_changes
    backup = cache_path.with_name("task.before-audio-review.json")
    if not backup.exists():
        main.save_json(backup, cache)
    recognizer = ReviewRecognizer(config, alternate=True)
    changes = []
    try:
        for segment, reason in candidates:
            print(f"Checking audio region #{segment['id']} ({main.console_time(segment['start'])}; {reason})...", flush=True)
            padding = 4.0 if reason == "untranslated_japanese" else 2.0 if reason in {"context_mismatch", "isolated_short"} else 1.5 if reason == "mixed_emoji" else .3
            clip_start = max(0, segment["start"] - padding)
            audio = decode_window(source, clip_start, segment["end"] + padding)
            first = max(0, round((segment["start"] - clip_start) * 16000))
            last = min(len(audio), round((segment["end"] - clip_start) * 16000))
            speech = speech_seconds(audio[first:last], threshold=.5) if reason in {'isolated_short', 'closing_phrase'} else speech_seconds(audio[first:last])
            review = {"version": REVIEW_VERSION, "attempts": segment.get("audio_review", {}).get("attempts", 0) + 1,
                      "reason": reason, "speech_seconds": round(speech, 3)}
            segment.setdefault("original_asr", {key: segment[key] for key in ("text", "start", "end")})
            segment.pop("needs_audio_review", None)
            if reason == 'closing_phrase':
                review['closing_checked'] = True
                review['recognized_text'] = segment['text']
                review['status'] = 'omitted' if weak_closing(segment, cache, speech) else 'reviewed'
                if review['status'] == 'omitted':
                    review['note'] = 'Closing phrase lacked acoustic speech evidence and reliable original recognition.'
            elif reason == "isolated_short" and speech >= .1:
                review["status"] = "reviewed"
                review["recognized_text"] = segment["text"]
            elif speech < .1 and reason in {"suspect_intro", "mixed_emoji"}:
                review["status"] = "omitted"
            else:
                if reason in {"untranslated_japanese", "mixed_emoji", "context_mismatch", "isolated_short"}:
                    focus = (segment["start"] - clip_start - .1, segment["end"] - clip_start + .1)
                    text = recognizer.transcribe(audio, cache["language"], focus=focus,
                                                context=preceding_context(segment, cache["segments"]) if reason == "context_mismatch" else "")
                else:
                    text = recognizer.transcribe(audio, cache["language"])
                review["recognized_text"] = text
                if closing_phrase(text) and weak_closing(segment, cache, speech):
                    review['status'] = 'omitted'
                    review['closing_checked'] = True
                    review['note'] = 'Local re-listening produced a closing phrase without acoustic speech evidence.'
                elif reason == "isolated_short" and speech < .1 and not lexical_speech(text):
                    review["status"] = "omitted"
                    review["note"] = "No speech evidence; local window recognition found no lexical dialogue."
                elif text and not unsafe_replacement(segment['text'], text):
                    if text != segment["text"]:
                        segment["text"] = text
                        _clear_translation(segment)
                        for key in ("words", "avg_logprob", "no_speech_prob", "compression_ratio"):
                            segment.pop(key, None)
                        if segment.get("refinement"):
                            segment["refinement"]["status"] = "uncertain"
                            segment["refinement"]["audio_review_changed"] = True
                    elif reason in {"untranslated_japanese", "mixed_emoji", "context_mismatch"}:
                        segment.pop("zh", None)
                    review["status"] = "reviewed"
                elif reason == "mixed_emoji":
                    review["status"] = "omitted"
                    review["note"] = "No reliable text recovered from the corrupted region."
                else:
                    review["status"] = "unresolved"
                    if text:
                        review['note'] = 'Rejected invalid or repetitive audio review text and kept the prior transcript.'
            if reason == "context_mismatch":
                review["context_checked"] = True
                if context_candidate(segment, cache["segments"]):
                    review["status"] = "context_unresolved"
            segment["audio_review"] = review
            changes.append({"id": segment["id"], **review})
            main.save_json(cache_path, cache)
    finally:
        recognizer.model = None
    return safety_changes + changes
