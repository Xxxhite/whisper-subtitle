"""Keep recognition evidence and refine long subtitles before translation."""
from __future__ import annotations

import copy
import math
import re
from difflib import SequenceMatcher
from pathlib import Path

VERSION = 1
SCORES = ('avg_logprob', 'no_speech_prob', 'compression_ratio')


def recognition_fields(item, *, offset: float = 0) -> dict:
    result = {}
    for key in SCORES:
        value = getattr(item, key, None)
        if isinstance(value, (int, float)) and math.isfinite(value):
            result[key] = float(value)
    words = []
    for word in getattr(item, 'words', None) or []:
        start, end = float(word.start) + offset, float(word.end) + offset
        if not math.isfinite(start + end) or end < start or not word.word:
            continue
        record = {'start': max(0, start), 'end': max(0, end), 'word': word.word}
        probability = getattr(word, 'probability', None)
        if isinstance(probability, (int, float)) and math.isfinite(probability) and 0 <= probability <= 1:
            record['probability'] = float(probability)
        words.append(record)
    if words:
        result['words'] = words
    return result


def compact(text: str) -> str:
    return ''.join(char.casefold() for char in text if char.isalnum())


def low_confidence(row: dict) -> bool:
    probabilities = [word['probability'] for word in row.get('words', []) if 'probability' in word]
    return (row.get('avg_logprob', 0) < -.8 or row.get('no_speech_prob', 0) >= .6
            or row.get('compression_ratio', 0) > 2.4
            or len(probabilities) >= 3 and sum(probabilities) / len(probabilities) < .45)


def added_repetitions(source: str, target: str) -> bool:
    before, after = compact(source), compact(target)
    return any(after.count(match[1]) > before.count(match[1])
               for match in re.finditer(r'(.{1,8}?)\1{2,}', before))


def split_words(row: dict, *, maximum: float = 12, pause: float = .9) -> list[dict]:
    """Split only at aligned token boundaries, preserving every source character."""
    words = copy.deepcopy(row.get('words', []))
    if not words or row['end'] - row['start'] <= maximum:
        return []
    if compact(''.join(word['word'] for word in words)) != compact(row['text']):
        return []
    previous = row['start']
    for word in words:
        word['start'] = max(row['start'], previous, word['start'])
        word['end'] = min(row['end'], max(word['start'], word['end']))
        if word['end'] < word['start']:
            return []
        previous = word['end']
    groups, begin, index = [], 0, 0
    while index < len(words):
        duration = words[index]['end'] - words[begin]['start']
        if duration > maximum and index > begin:
            choices = [j for j in range(begin, index) if words[j]['end'] - words[begin]['start'] >= 2
                       and (words[j + 1]['start'] - words[j]['end'] >= .18
                            or re.search(r'[、，,。！？!?…]$', words[j]['word']))]
            end = choices[-1] if choices else index - 1
            groups.append(words[begin:end + 1])
            begin, index = end + 1, end + 1
            continue
        gap = words[index + 1]['start'] - words[index]['end'] if index + 1 < len(words) else 0
        phrase = ''.join(word['word'] for word in words[begin:index + 1]).strip()
        complete = bool(re.search(r'[。！？!?]$', phrase))
        dangling = bool(re.search(r'[、，,のをがはにでとへやも]$', phrase))
        boundary = (gap >= pause and (complete or len(compact(phrase)) >= 6 and not dangling)
                    or duration >= 2 and complete)
        if boundary and index + 1 < len(words):
            groups.append(words[begin:index + 1])
            begin = index + 1
        index += 1
    if begin < len(words):
        groups.append(words[begin:])
    # Attach zero-length decoder artifacts to the preceding or following group.
    merged = []
    for group in groups:
        if merged and group[-1]['end'] <= group[0]['start']:
            merged[-1].extend(group)
        else:
            merged.append(group)
    if len(merged) > 1 and merged[0][-1]['end'] <= merged[0][0]['start']:
        first = merged.pop(0)
        merged[0] = first + merged[0]
    parts = [{'start': group[0]['start'], 'end': group[-1]['end'],
              'text': ''.join(word['word'] for word in group).strip(), 'words': group}
             for group in merged]
    return parts if len(parts) > 1 and all(part['end'] > part['start'] and part['text'] for part in parts) else []


def original_segments(cache: dict) -> list[dict]:
    originals = cache.get('refinement', {}).get('originals', {})
    result, seen = [], set()
    for row in cache['segments']:
        details = row.get('refinement', {})
        for identifier in details.get('parent_ids', [details.get('parent_id', row['id'])]):
            parent = str(identifier)
            if parent in seen:
                continue
            seen.add(parent)
            raw = originals.get(parent, row)
            result.append({**raw, **raw.get('original_asr', {})})
    return sorted(result, key=lambda row: (row['start'], row['end']))


def _clear_translation(row: dict) -> None:
    for key in ('zh', 'model_zh', 'translation_text', 'rule_input_signature', 'rule_matches', 'glossary_terms', 'format_normalized'):
        row.pop(key, None)


def _candidate(row: dict, language: str) -> bool:
    from audio_review import lexical_speech
    from subtitle_processing import contains_emoji, sound_key
    if row.get('audio_review', {}).get('status') == 'omitted' or contains_emoji(row['text']):
        return False
    return (lexical_speech(row['text']) if language == 'ja' else sound_key(row['text']) is None)


def _reviewed(parent: dict, recognized: list[dict], left: float) -> dict | None:
    from audio_review import lexical_speech
    from subtitle_processing import contains_emoji
    from sakura import has_unexpected_repetition
    rows = [row for row in recognized if row['end'] > row['start'] and row.get('words')]
    if not rows:
        return None
    words = []
    for row in rows:
        for original in row['words']:
            word = {**original, 'start': original['start'] + left, 'end': original['end'] + left}
            midpoint = (word['start'] + word['end']) / 2
            if parent['start'] - .1 <= midpoint <= parent['end'] + .1:
                word['start'] = max(parent['start'], word['start'])
                word['end'] = min(parent['end'], word['end'])
                if word['end'] >= word['start']:
                    words.append(word)
    text = ''.join(word['word'] for word in words).strip()
    if not text or contains_emoji(text) or not lexical_speech(text):
        return None
    weights = [max(.1, row['end'] - row['start']) for row in rows]
    avg = sum(row.get('avg_logprob', -2) * weight for row, weight in zip(rows, weights)) / sum(weights)
    speech = sum(row.get('no_speech_prob', 1) * weight for row, weight in zip(rows, weights)) / sum(weights)
    similarity = SequenceMatcher(None, compact(parent['text']), compact(text), autojunk=False).ratio()
    if (avg < -.8 or speech >= .6 or len(compact(text)) < .45 * len(compact(parent['text']))
            or len(compact(text)) > max(32, 2 * len(compact(parent['text'])))
            or has_unexpected_repetition(text, parent['text']) or similarity < .55
            or added_repetitions(parent['text'], text)
            or any(row.get('compression_ratio', 0) > 2.4 for row in rows)
            or avg < parent.get('avg_logprob', -2) - .15):
        return None
    result = {'text': text, 'words': words, 'avg_logprob': avg, 'no_speech_prob': speech}
    if any('compression_ratio' in row for row in rows):
        result['compression_ratio'] = max(row.get('compression_ratio', 0) for row in rows)
    return result


def refine(source: Path, cache: dict, cache_path: Path, config: dict) -> list[int]:
    """Checkpoint each reviewed parent; keep old IDs and unaffected translations."""
    import main
    from audio_review import ReviewRecognizer, decode_window
    if config.get('quality', 'high') != 'high':
        return []
    candidates = [row for row in cache['segments'] if _candidate(row, cache['language'])
                  and row.get('refinement', {}).get('version') != VERSION
                  and (row['end'] - row['start'] > 15 or low_confidence(row) or row.get('words') and row['end'] - row['start'] > 8)]
    if not candidates:
        return []
    backup = cache_path.with_name('task.before-transcript-refinement.json')
    if not backup.exists():
        main.save_json(backup, cache)
    state = cache.setdefault('refinement', {'version': VERSION, 'originals': {}})
    recognizer = ReviewRecognizer(config, alternate=True)
    changed = []
    try:
        for parent in candidates:
            if parent not in cache['segments']:
                continue
            original = copy.deepcopy(parent)
            reasons = []
            if parent['end'] - parent['start'] > 15:
                reasons.append('long_segment')
            if low_confidence(parent):
                reasons.append('low_confidence')
            review = {'version': VERSION, 'parent_id': parent['id'], 'reasons': reasons, 'status': 'unchanged'}
            if reasons:
                print(f"Refining audio #{parent['id']} ({main.console_time(parent['start'])}; {', '.join(reasons)})...", flush=True)
                following = sorted((r for r in cache['segments'] if r['id'] != parent['id'] and r['start'] >= parent['end']), key=lambda r: r['start'])
                neighbor = following[0] if following else None
                join = (neighbor and not neighbor.get('refinement') and _candidate(neighbor, cache['language'])
                        and 'long_segment' in reasons and neighbor['start'] - parent['end'] <= .35
                        and neighbor['end'] - neighbor['start'] <= 6 and neighbor['end'] - parent['start'] <= 32)
                focus = {**parent, 'end': neighbor['end'], 'text': parent['text'] + ' ' + neighbor['text']} if join else parent
                before = max((r['end'] for r in cache['segments'] if r['id'] != parent['id'] and r['end'] <= focus['start']), default=0)
                after = min((r['start'] for r in cache['segments'] if r['id'] != parent['id'] and r['start'] >= focus['end']), default=focus['end'] + .3)
                left, right = max(before, focus['start'] - .3, 0), min(after, focus['end'] + .3)
                recognized = recognizer.timed(decode_window(source, left, right), cache['language'])
                replacement = _reviewed(focus, recognized, left)
                if replacement is None and main.asr_settings(config)['model'] == 'large-v2':
                    review['alternate_recognized'] = recognized
                    # Release the alternate model before loading the primary model.
                    recognizer.model = None
                    recognizer.alternate = False
                    recognized = recognizer.timed(decode_window(source, left, right), cache['language'])
                    replacement = _reviewed(focus, recognized, left)
                    recognizer.model = None
                    recognizer.alternate = True
                    review['primary_fallback'] = True
                review['recognized'] = recognized
                if replacement:
                    if join:
                        state['originals'].setdefault(str(neighbor['id']), copy.deepcopy(neighbor))
                        review['parent_ids'] = [parent['id'], neighbor['id']]
                        cache['segments'] = [r for r in cache['segments'] if r['id'] != neighbor['id']]
                        parent['end'] = neighbor['end']
                    if join or compact(replacement['text']) != compact(parent['text']):
                        review['similarity'] = round(SequenceMatcher(None, compact(focus['text']), compact(replacement['text']), autojunk=False).ratio(), 3)
                        review['status'] = 'revised'
                        _clear_translation(parent)
                    else:
                        replacement['text'] = parent['text']
                    parent.update(replacement)
                else:
                    review['status'] = 'uncertain'
            state['originals'].setdefault(str(parent['id']), original)
            parts = split_words(parent)
            if parts:
                next_id = max([row['id'] for row in cache['segments']] + [int(key) for key in state['originals']]) + 1
                children = []
                for index, part in enumerate(parts):
                    child = {**parent, **part, 'id': parent['id'] if index == 0 else next_id + index - 1}
                    _clear_translation(child)
                    child.pop('original_asr', None)
                    child['refinement'] = {**review, 'part': index + 1, 'parts': len(parts)}
                    children.append(child)
                cache['segments'] = [row for row in cache['segments'] if row['id'] != parent['id']] + children
                cache['segments'].sort(key=lambda row: (row['start'], row['end'], row['id']))
                changed.append(parent['id'])
            else:
                parent['refinement'] = review
                if review['status'] == 'revised':
                    changed.append(parent['id'])
            main.save_json(cache_path, cache)
    finally:
        recognizer.model = None
    return changed
