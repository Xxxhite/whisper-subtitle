"""Recheck weak Japanese speech adjacent to a collapsed or very short fragment."""
from pathlib import Path
import re

from .source_checks import key, reading, word_confidence

VERSION = 1
PADDING = .2


def collapsed_fragment(row: dict) -> bool:
    duration = row['end'] - row['start']
    words = [w for w in row.get('words', []) if key(w['word'])]
    return (0 < duration <= .7 and len(key(row['text'])) >= max(8, 24 * duration)
            and row.get('avg_logprob', 0) <= -1.5 and len(words) >= 4
            and sum(w['end'] - w['start'] <= .041 for w in words) >= .6 * len(words))


def plan(rows: list[dict]) -> list[tuple[dict, dict, float]]:
    ordered = sorted(rows, key=lambda r: (r['start'], r['end'], r['id']))
    planned = []
    for row, following in zip(ordered, ordered[1:]):
        details = row.get('refinement', {})
        if details.get('status') != 'uncertain' or not 2.5 <= row['end'] - row['start'] <= 14:
            continue
        if not -.05 <= following['start'] - row['end'] <= .18:
            continue
        if not collapsed_fragment(following):
            child = following.get('refinement', {})
            elapsed = following['end'] - following['start']
            words = [w for w in row.get('words', []) if key(w['word'])]
            if (child.get('part') != 1 or child.get('parts', 1) < 2 or elapsed > 2
                    or row.get('no_speech_prob', 0) < .6
                    or sum(w['end'] - w['start'] <= .041 for w in words) < 3):
                continue
        elif row.get('avg_logprob', 0) > -1.5:
            continue
        planned.append((row, following, following['end'] + .3))
    return planned


def evidence(items: list[dict], left: float, right: float, source: str) -> dict | None:
    from .audio_review import closing_phrase, lexical_speech, unsafe_replacement

    if len(items) != 1:
        return None
    item = items[0]
    text = item['text']
    if (item.get('avg_logprob', -2) < -.65 or item.get('no_speech_prob', 1) >= .4
            or item.get('compression_ratio', 0) > 2.4 or word_confidence(item) < .65
            or not lexical_speech(text) or not 6 <= len(key(text)) <= 72
            or closing_phrase(text) or unsafe_replacement(source, text)):
        return None
    offset = left - PADDING
    words = [{**w, 'start': max(left, offset + w['start']), 'end': min(right, offset + w['end'])}
             for w in item.get('words', [])]
    if (not words or any(w['end'] < w['start'] for w in words)
            or any(b['start'] < a['end'] - .01 for a, b in zip(words, words[1:]))):
        return None
    return {**item, 'start': words[0]['start'], 'end': words[-1]['end'], 'words': words}


def confirmed(row: dict, following: dict, passes: dict, left: float, right: float) -> dict | None:
    if not all(passes[k]['model'] for k in ('primary', 'alternate')) or passes['primary']['model'] == passes['alternate']['model']:
        return None
    primary, alternate = (evidence(passes[k]['items'], left, right, row['text'])
                          for k in ('primary', 'alternate'))
    if not primary or not alternate:
        return None
    first, second = reading(primary['text']), reading(alternate['text'])
    if len(re.findall(r'[?？]+', primary['text'])) < len(re.findall(r'[?？]+', row['text'])):
        return None
    if min(primary['end'], alternate['end']) - max(primary['start'], alternate['start']) < 1:
        return None
    if min(primary['end'], alternate['end'], row['end']) - max(primary['start'], alternate['start'], row['start']) < 1:
        return None
    if collapsed_fragment(following):
        # The shorter result must end at a sentence boundary before the bad fragment.
        if (primary['end'] > following['start'] + .05 or not primary['text'].endswith(('。', '！', '？', '!', '?'))
                or not (first == second or second.startswith(first) and len(second) - len(first) <= 6)):
            return None
    else:
        # The recovered continuation must occupy the same audio as the short neighboring text.
        if (first != second or reading(following['text']) in first or primary['end'] > following['end']
                or min(primary['end'], alternate['end'], following['end'])
                - max(primary['start'], alternate['start'], following['start'])
                < max(.45, (following['end'] - following['start']) / 2)):
            return None
    return primary


def review_weak_sequences(source: Path, cache: dict, path: Path, config: dict) -> None:
    import numpy as np
    from . import cli
    from .audio_review import ReviewRecognizer, decode_window, normalize_review_audio
    from .short_speech import alternate_available
    from .subtitle_processing import eligible_segments
    from .transcript_refinement import SCORES, _clear_translation

    if (cache.get('language') != 'ja' or config.get('quality', 'high') != 'high'
            or cli.asr_settings(config)['model'] != 'large-v2'):
        return
    candidates = []
    for row, following, right in plan(eligible_segments(cache)):
        signature = cli.fingerprint([VERSION, row['id'], row['text'], row['start'], row['end'],
                                     following['id'], following['text'], following['start'], right])
        if row.get('weak_sequence_review', {}).get('signature') != signature:
            candidates.append((row, following, right, signature))
    if not candidates or not alternate_available(config):
        return
    backup = path.with_name('task.before-weak-sequence-review.json')
    if not backup.exists():
        cli.save_json(backup, cache)
    for row, following, right, signature in candidates:
        if following.get('audio_review', {}).get('status') == 'omitted' or row.get('audio_review', {}).get('status') == 'omitted':
            continue
        detail = {'signature': signature, 'status': 'uncertain', 'passes': []}
        print(f"Checking weak neighboring speech ({cli.console_time(row['start'])})...", flush=True)
        # The second crop reduces lead-in noise without extending into a later subtitle.
        for offset in (-.2, .4):
            left = max(0, row['start'] + offset)
            tracks = [decode_window(source, left, right, channel=side) for side in ('left', 'right')]
            track = max(tracks, key=lambda audio: np.percentile(np.abs(audio), 99.5))
            pad = round(PADDING * 16000)
            clip = np.pad(normalize_review_audio(track, peak_target=.3, max_gain=16), (pad, pad))
            passes = {}
            for label, alternate in [('primary', False), ('alternate', True)]:
                recognizer = ReviewRecognizer(config, alternate=alternate)
                try:
                    items = recognizer.short_clip(clip)
                    passes[label] = {'model': recognizer.model_name, 'items': items}
                finally:
                    recognizer.model = None
            detail['passes'].append({'left': left, 'right': right, **passes})
            replacement = confirmed(row, following, passes, left, right)
            if not replacement:
                continue
            previous_end = max((r['end'] for r in eligible_segments(cache)
                                if r['id'] != row['id'] and r['start'] < row['start']), default=0)
            if replacement['start'] < previous_end:
                continue
            row.setdefault('original_asr', {k: row[k] for k in ('text', 'start', 'end')})
            row.update({k: replacement[k] for k in ('text', 'start', 'end', 'words', *SCORES) if k in replacement})
            _clear_translation(row)
            detail['status'] = 'recovered'
            following['audio_review'] = {'status': 'omitted', 'reason': 'weak_neighbor_replaced',
                'note': 'Independent local decodes recovered the dialogue across this unreliable fragment.'}
            break
        row['weak_sequence_review'] = detail
        cache['segments'].sort(key=lambda r: (r['start'], r['end'], r['id']))
        cli.save_json(path, cache)
