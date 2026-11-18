"""Conservative two-model confirmation for quiet gaps and short Japanese lines."""
from __future__ import annotations

from difflib import SequenceMatcher
from pathlib import Path
import re
import unicodedata

VERSION = 2


def alternate_available(config: dict) -> bool:
    from . import cli as main
    from faster_whisper.utils import download_model
    try:
        download_model('turbo', cache_dir=str(main.resolve_setting(config['download_root'])), local_files_only=True)
    except (OSError, ValueError):
        return False
    return True


def phonetic_key(text: str) -> str:
    text = unicodedata.normalize('NFKC', text)
    text = ''.join(chr(ord(c) - 0x60) if 0x30A1 <= ord(c) <= 0x30F6 else c for c in text)
    # Ignore pronunciation decorations only for agreement checks, never rewrite output.
    return ''.join(c.casefold() for c in text if c.isalnum() and c not in 'ーぁぃぅぇぉ')


def dialogue_key(text: str) -> str:
    text = unicodedata.normalize('NFKC', text)
    text = ''.join(chr(ord(c) - 0x60) if 0x30A1 <= ord(c) <= 0x30F6 else c for c in text)
    # Adding a laugh or breath alone does not justify retranslating correct dialogue.
    text = re.sub(r'^(?:[んぁあぅうぇえぉおはふへほーっ]+[、,，…。?？\s]+)+', '', text)
    return phonetic_key(text)


def plan_candidates(segments: list[dict], speech: list[dict]) -> list[dict]:
    from .audio_review import lexical_speech
    from .transcript_refinement import compact, low_confidence
    rows = sorted((r for r in segments if r.get('audio_review', {}).get('status') != 'omitted'), key=lambda r: r['start'])
    candidates = []
    for before, after in zip(rows, rows[1:]):
        start, end = before['end'], after['start']
        if not .8 <= end - start <= 12 or not (lexical_speech(before['text']) or lexical_speech(after['text'])):
            continue
        windows = []
        for region in speech:
            left, right = max(start, region['start'] / 16000), min(end, region['end'] / 16000)
            if not .12 <= right - left <= 2.5 or min(left - start, end - right) < .35:
                continue
            window = {'kind': 'gap', 'left': max(start, left - 1.5), 'right': min(end, right + 1.5),
                      'bounds': [start, end], 'speech': [left, right]}
            if windows and window['left'] < windows[-1]['right']:
                windows[-1]['right'] = max(windows[-1]['right'], window['right'])
                windows[-1]['speech'][1] = max(windows[-1]['speech'][1], right)
            else:
                windows.append(window)
        candidates.extend(windows)
    for row in rows:
        # A weak lexical token inside an otherwise protected long parent may conceal a quiet phrase.
        if (row.get('refinement', {}).get('source_protected') and lexical_speech(row['text'])
                and ''.join(w['word'] for w in row.get('words', [])) == row['text']):
            windows = []
            for index, word in enumerate(row.get('words', [])):
                if not compact(word['word']) or word.get('probability', 1) >= .2:
                    continue
                left, right = max(row['start'], word['start'] - 1.5), min(row['end'], word['end'] + 1.5)
                if not .8 <= right - left <= 5:
                    continue
                if windows and left < windows[-1]['right']:
                    continue
                windows.append({'kind': 'internal', 'id': row['id'], 'source': row['text'], 'word_index': index,
                                'left': left, 'right': right, 'focus': [left, right]})
            candidates.extend(windows)
        if (row.get('refinement') or not lexical_speech(row['text']) or not .3 <= row['end'] - row['start'] <= 4
                or not 4 <= len(compact(row['text'])) <= 32):
            continue
        if 'avg_logprob' in row and not (low_confidence(row) or row['avg_logprob'] < -.65):
            continue
        candidates.append({'kind': 'existing', 'id': row['id'], 'source': row['text'],
                           'left': max(0, row['start'] - 1.2), 'right': row['end'] + 1.2,
                           'focus': [row['start'], row['end']]})
    return candidates


def hypothesis(items: list[dict], window: dict) -> dict | None:
    from .subtitle_processing import contains_emoji
    from .transcript_refinement import compact
    from .sakura import has_unexpected_repetition
    words, scores = [], []
    for row in items:
        chosen = []
        for word in row.get('words', []):
            absolute = {**word, 'start': word['start'] + window['left'], 'end': word['end'] + window['left']}
            if 'focus' not in window or absolute['end'] > window['focus'][0] - .15 and absolute['start'] < window['focus'][1] + .15:
                chosen.append(absolute)
        if chosen:
            words.extend(chosen)
            scores.append(row)
    text = ''.join(w['word'] for w in words).strip()
    if not text or contains_emoji(text) or has_unexpected_repetition(text, '') or len(compact(text)) > 32:
        return None
    avg = sum(r.get('avg_logprob', -2) for r in scores) / len(scores)
    no_speech = max(r.get('no_speech_prob', 1) for r in scores)
    probabilities = [w['probability'] for w in words if 'probability' in w and compact(w['word'])]
    if avg < -1 or no_speech >= .6 or any(r.get('compression_ratio', 0) > 2.4 for r in scores):
        return None
    if not probabilities or sum(probabilities) / len(probabilities) < .35:
        return None
    return {'text': text, 'words': words, 'avg_logprob': avg, 'no_speech_prob': no_speech,
            'start': min(w['start'] for w in words), 'end': max(w['end'] for w in words)}


def confirmed(primary: dict | None, alternate: dict | None, window: dict) -> bool:
    from .audio_review import closing_phrase, lexical_speech
    if not primary or not alternate or phonetic_key(primary['text']) != phonetic_key(alternate['text']):
        return False
    key = phonetic_key(alternate['text'])
    if not key:
        return False
    if window['kind'] == 'internal':
        from .sakura import rhythmic_input
        if not 2 <= len(key) <= 12 or not lexical_speech(alternate['text']) or closing_phrase(alternate['text']) or rhythmic_input(alternate['text']):
            return False
        source = phonetic_key(window['source'])
        # Avoid inserting recognized fragments of words already in the retained sentence.
        if SequenceMatcher(None, source, key, autojunk=False).find_longest_match().size >= 2:
            return False
        return (min(primary['end'], alternate['end']) - max(primary['start'], alternate['start']) >= .12
                and all(h['avg_logprob'] >= -.8 and h['no_speech_prob'] < .3
                        and sum(w.get('probability', 0) for w in h['words']) / len(h['words']) >= .65
                        and window['left'] <= h['start'] < h['end'] <= window['right'] for h in (primary, alternate)))
    if window['kind'] == 'existing':
        return SequenceMatcher(None, phonetic_key(window['source']), key, autojunk=False).ratio() >= .5
    if closing_phrase(alternate['text']):
        return (window['speech'][1] - window['speech'][0] >= .5
                and all(h.get('no_speech_prob', 1) < .3 and h.get('avg_logprob', -2) > -.7 for h in (primary, alternate)))
    meaningful = lexical_speech(alternate['text']) or key in {'うん', 'はい', 'ううん', 'あれ', 'へえ'}
    meaningful |= key == 'ん' and all(any(c in h['text'] for c in '?？') for h in (primary, alternate))
    if not meaningful:
        return False
    left, right = window['speech']
    return all(min(h['end'], right) - max(h['start'], left) >= .08 for h in (primary, alternate))


def supplement(row: dict, recognized: dict, window: dict) -> bool:
    """Insert an independently confirmed phrase; retain every original source word."""
    from .transcript_refinement import _clear_translation, compact
    index = window['word_index']
    original = row['words']
    if any(compact(w['word']) and w.get('probability', 0) >= .65 and w['end'] - w['start'] <= 1.2
           and min(w['end'], recognized['end']) - max(w['start'], recognized['start']) >= .12 for w in original):
        # A differently spelled reading of an already aligned word is not missing dialogue.
        return False
    row.setdefault('original_asr', {k: row[k] for k in ('text', 'start', 'end')})
    added = [{**w} for w in recognized['words']]
    left = [{**w, 'end': min(w['end'], added[0]['start'])} for w in original[:index]]
    right = [{**w, 'start': max(w['start'], added[-1]['end']), 'end': max(w['end'], added[-1]['end'])} for w in original[index:]]
    # Punctuation may span a long silence in the original alignment.
    for w in left:
        w['start'] = min(w['start'], w['end'])
    row['words'] = left + added + right
    offset = sum(len(w['word']) for w in original[:index])
    row['text'] = row['text'][:offset] + recognized['text'] + '…' + row['text'][offset:]
    # Keep aligned text in sync with the inserted separator.
    row['words'][len(left) + len(added) - 1]['word'] += '…'
    _clear_translation(row)
    return True


def confirmed_omitted_speech(row: dict, window: dict, passes: dict) -> bool:
    from .audio_review import lexical_speech

    primary = passes['primary']
    alternate = passes['alternate']
    if not primary['model'] or not alternate['model'] or primary['model'] == alternate['model']:
        return False
    a, b = (hypothesis(result['items'], window) for result in (primary, alternate))
    return bool(a and b and lexical_speech(a['text'])
                and dialogue_key(a['text']) == dialogue_key(b['text']) == dialogue_key(row['text'])
                and min(a['end'], b['end'], row['end']) - max(a['start'], b['start'], row['start']) >= .4)


def restore_omitted_speech(source: Path, cache: dict, path: Path, config: dict) -> None:
    import numpy as np
    from . import cli
    from .audio_review import ReviewRecognizer, decode_window, lexical_speech, normalize_review_audio
    from .transcript_refinement import VERSION as REFINEMENT_VERSION, _clear_translation, compact

    candidates = []
    for row in cache.get('segments', []):
        review = row.get('audio_review', {})
        if (review.get('status') == 'omitted' and review.get('reason') == 'isolated_short'
                and review.get('speech_seconds', 1) < .1 and not row.get('omitted_speech_review')
                and row.get('no_speech_prob', 1) < .35
                and 1.5 <= row['end'] - row['start'] <= 6
                and 4 <= len(compact(row['text'])) <= 22 and lexical_speech(row['text'])):
            candidates.append(row)
    if not candidates or not alternate_available(config):
        return
    backup = path.with_name('task.before-omitted-speech-review.json')
    if not backup.exists():
        cli.save_json(backup, cache)
    for row in candidates:
        later = (r['start'] for r in cache['segments'] if r['start'] >= row['end'] and r['id'] != row['id']
                 and r.get('audio_review', {}).get('status') != 'omitted')
        right = min(row['end'] + .65, min(later, default=row['end'] + .65))
        detail = {'status': 'uncertain', 'windows': []}
        print(f"Checking previously omitted quiet speech ({cli.console_time(row['start'])})...", flush=True)
        for offset in (.45, -.35):
            left = max(0, row['start'] + offset)
            channels = [decode_window(source, left, right, channel=side) for side in ('left', 'right')]
            track = max(channels, key=lambda audio: np.percentile(np.abs(audio), 99.5))
            clip = np.pad(normalize_review_audio(track, peak_target=.3, max_gain=16), (3200, 3200))
            window = {'left': left - .2, 'focus': [row['start'] - .15, right], 'right': right}
            passes = {}
            for label, alternate in [('primary', False), ('alternate', True)]:
                model = ReviewRecognizer(config, alternate=alternate)
                try:
                    items = model.short_clip(clip)
                    passes[label] = {'model': model.model_name, 'items': items}
                finally:
                    model.model = None
            detail['windows'].append({'window': window, 'passes': passes})
            if confirmed_omitted_speech(row, window, passes):
                detail['status'] = 'restored'
                row['audio_review'].update(status='restored',
                                           note='Two local models re-confirmed this quiet original line.')
                row.setdefault('refinement', {'version': REFINEMENT_VERSION, 'parent_id': row['id'],
                                              'status': 'unchanged', 'short_confirmed': True})
                _clear_translation(row)
                break
        row['omitted_speech_review'] = detail
        cli.save_json(path, cache)


def review_short_speech(source: Path, cache: dict, cache_path: Path, config: dict) -> list[int]:
    from . import cli as main
    from .audio_review import ReviewRecognizer, decode_window
    from .transcript_refinement import VERSION as REFINEMENT_VERSION, _clear_translation
    if cache.get('language') != 'ja' or config.get('quality', 'high') != 'high' or main.asr_settings(config)['model'] != 'large-v2':
        return []
    restore_omitted_speech(source, cache, cache_path, config)
    state = cache.get('short_speech', {})
    if state.get('version') == VERSION and state.get('complete'):
        return []
    if not alternate_available(config):
        print('Short speech review skipped: a local turbo model is required for independent confirmation.', flush=True)
        return []
    if state.get('version') != VERSION:
        import av
        from faster_whisper.vad import get_speech_timestamps
        with av.open(str(source)) as container:
            duration = container.duration / av.time_base if container.duration else max(r['end'] for r in cache['segments'])
        speech = get_speech_timestamps(decode_window(source, 0, duration), threshold=.35,
                                      min_speech_duration_ms=100, min_silence_duration_ms=100, speech_pad_ms=0)
        previous = state
        candidates = plan_candidates(cache['segments'], speech)
        if previous.get('version') == 1 and previous.get('complete'):
            candidates = [w for w in candidates if w['kind'] == 'internal']
        state = {'version': VERSION, 'candidates': candidates,
                 'passes': {}, 'applied': 0, 'added_ids': previous.get('added_ids', []),
                 'changed_ids': previous.get('changed_ids', []), 'complete': False}
        backup = cache_path.with_name(f'task.before-short-review-v{VERSION}.json' if previous else 'task.before-short-review.json')
        if not backup.exists():
            main.save_json(backup, cache)
        cache['short_speech'] = state
        main.save_json(cache_path, cache)
    for label, alternate in [('primary', False), ('alternate', True)]:
        progress = state['passes'].setdefault(label, {'results': [], 'model': None})
        recognizer = ReviewRecognizer(config, alternate=alternate)
        try:
            for index in range(len(progress['results']), len(state['candidates'])):
                window = state['candidates'][index]
                print(f"Checking short speech {index + 1}/{len(state['candidates'])} ({label}; {main.console_time(window['left'])})...", flush=True)
                items = recognizer.timed(decode_window(source, window['left'], window['right']), 'ja')
                progress['model'] = recognizer.model_name
                progress['results'].append(items)
                main.save_json(cache_path, cache)
        finally:
            recognizer.model = None
    distinct = (state['passes']['primary']['model'] and state['passes']['alternate']['model']
                and state['passes']['primary']['model'] != state['passes']['alternate']['model'])
    state['distinct_models'] = bool(distinct)
    for index in range(state['applied'], len(state['candidates'])):
        window = state['candidates'][index]
        a = hypothesis(state['passes']['primary']['results'][index], window)
        b = hypothesis(state['passes']['alternate']['results'][index], window)
        accepted = distinct and confirmed(a, b, window)
        evidence = {'version': VERSION, 'candidate': index, 'status': 'uncertain',
                    'primary': a['text'] if a else '', 'alternate': b['text'] if b else ''}
        if window['kind'] == 'gap':
            if accepted:
                start = max(window['bounds'][0], b['start'], window['speech'][0] - .35)
                end = min(window['bounds'][1], max(b['end'], window['speech'][1] + .2))
                if end > start and not any(min(end, row['end']) - max(start, row['start']) > .05 for row in cache['segments']):
                    identifier = max([r['id'] for r in cache['segments']] + [int(k) for k in cache.get('refinement', {}).get('originals', {})]) + 1
                    evidence['status'] = 'recovered'
                    row = {**b, 'id': identifier, 'start': start, 'end': end, 'short_review': evidence,
                           'refinement': {'version': REFINEMENT_VERSION, 'parent_id': identifier, 'status': 'unchanged', 'short_confirmed': True}}
                    row['words'] = [{**w, 'start': max(start, w['start']), 'end': min(end, w['end'])} for w in b['words']
                                    if w['end'] >= start and w['start'] <= end]
                    cache['segments'].append(row)
                    cache['segments'].sort(key=lambda r: (r['start'], r['end'], r['id']))
                    state['added_ids'].append(identifier)
        elif window['kind'] == 'internal':
            row = next((r for r in cache['segments'] if r['id'] == window['id']), None)
            if row and row['text'] == window['source']:
                if accepted and supplement(row, b, window):
                    evidence.update(status='supplemented', inserted=b['text'], kind='internal')
                    state['changed_ids'].append(row['id'])
                row['short_review'] = evidence
        else:
            row = next((r for r in cache['segments'] if r['id'] == window['id']), None)
            if row and row['text'] == window['source']:
                if accepted and dialogue_key(row['text']) != dialogue_key(b['text']):
                    row.setdefault('original_asr', {k: row[k] for k in ('text', 'start', 'end')})
                    _clear_translation(row)
                    row['text'] = b['text']
                    for key in ('words', 'avg_logprob', 'no_speech_prob', 'compression_ratio'):
                        row.pop(key, None)
                    row['avg_logprob'] = b['avg_logprob']
                    row['no_speech_prob'] = b['no_speech_prob']
                    row['words'] = [{**w, 'start': max(row['start'], w['start']), 'end': min(row['end'], w['end'])}
                                    for w in b['words'] if w['end'] >= row['start'] and w['start'] <= row['end']]
                    evidence['status'] = 'revised'
                    state['changed_ids'].append(row['id'])
                elif accepted:
                    evidence['status'] = 'confirmed'
                row['short_review'] = evidence
        state['applied'] = index + 1
        main.save_json(cache_path, cache)
    state['complete'] = True
    main.save_json(cache_path, cache)
    return state['added_ids'] + state['changed_ids']
