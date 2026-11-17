"""Checkpoint local evidence before accepting malformed text or contextual spelling changes."""
from difflib import SequenceMatcher
from pathlib import Path
import re

from source_checks import artifact, implausible_duplicate, key, reading, word_confidence

VERSION = 3
# Vocabulary hints select acoustic checks; they never perform source replacements directly.
# Each spelling change must be returned by both models, with unchanged surrounding words.
TERMS = (
    (('下先',), '舌先', ('耳', '舐', 'なめ'), ()),
    (('女の口',), '序の口', ('まだ',), ()),
    (('写真', '写生', '謝罪', '処生'), '射精', ('勃起', 'ぼっき', 'おちん', 'しこしこ', 'しご', '我慢汁'), ('カメラ', '撮', '絵', '画家', '謝る', '謝罪会見', '申し訳')),
    (('幸運',), '興奮', ('息', '体', '勃起', 'ぼっき', 'エッチ'), ('宝くじ', 'くじ', '幸運を祈')),
    (('繊維器', '繊益', '鮮液'), '精液', ('勃起', 'ぼっき', 'おちん', '我慢汁', 'バックハグ'), ('繊維工', '機械')),
    (('肺炎',), '快感', ('気持ち', 'マッサージ', 'しこ', 'おちん'), ('病院', '医師', '咳', '発熱', '治療')),
    (('壺',), 'ズボン', ('ズボン',), ('花瓶', '陶器', '焼き物')),
    (('夫婦',), 'ふーふー', ('ふーふー', '吹'), ('結婚', '妻', '夫婦生活')),
)


def spelling_hints(row: dict, rows: list[dict]) -> list[tuple[str, str]]:
    from subtitle_processing import kana_unit_key
    context = row['text'] + '\n' + '\n'.join(r['text'] for r in rows
              if row['start'] - 120 <= r['end'] <= row['start'] and r['id'] != row['id']
              and r.get('audio_review', {}).get('status') != 'omitted')[-2400:]
    context = kana_unit_key(context)
    return [(suspect, target) for suspects, target, required, excluded in TERMS
            if any(kana_unit_key(token) in context for token in required) and not any(kana_unit_key(token) in context for token in excluded)
            for suspect in suspects if suspect in row['text']]


def _initial(row: dict, cache: dict) -> dict:
    parent = row.get('refinement', {}).get('parent_id', row['id'])
    return cache.get('refinement', {}).get('originals', {}).get(str(parent), row)


def _selection(row: dict, cache: dict) -> tuple[str | None, list]:
    from audio_review import closing_phrase
    if artifact(row['text']):
        return artifact(row['text']), []
    if implausible_duplicate(row, cache['segments']):
        return 'implausible_duplicate', []
    if closing_phrase(row['text']):
        return 'closing_evidence', []
    if cache.get('language') == 'ja':
        if re.search(r'[\uac00-\ud7a3]', row['text']):
            return 'mixed_script', []
        from subtitle_processing import repeated_kana, sound_key
        if (row.get('refinement', {}).get('status') == 'uncertain' and row.get('avg_logprob', 0) < -1.2
                and re.fullmatch(r'[ァ-ヺー、,。.…\s]+', row['text'])
                and repeated_kana(row['text']) and sound_key(row['text']) is None):
            return 'uncertain_repetition', []
        hints = spelling_hints(row, cache['segments'])
        # Reuse an already gathered alternate hypothesis instead of repeating audio work.
        details = row.get('refinement', {})
        alternatives = details.get('alternate_recognized', [])
        primaries = details.get('recognized', [])
        distinct = (details.get('alternate_model') and details.get('primary_model')
                    and details['alternate_model'] != details['primary_model'])
        if hints and distinct and details.get('parts', 1) == 1 and len(alternatives) == len(primaries) == 1:
            alt, primary = alternatives[0], primaries[0]
            if (not artifact(alt['text']) and reading(alt['text']) == reading(primary['text'])
                    and key(alt['text']) != key(row['text']) and alt['avg_logprob'] >= primary['avg_logprob'] + .1
                    and word_confidence(alt) >= .65 and any(key(new) in key(alt['text']) for _, new in hints)):
                return 'cached_homophone', hints
        if hints:
            return 'contextual_spelling', hints
    return None, []


def focused(items: list[dict], row: dict, left: float) -> dict | None:
    words, evidence = [], []
    for item in items:
        chosen = [{**w, 'start': w['start'] + left, 'end': w['end'] + left} for w in item.get('words', [])
                  if min(row['end'], left + w['end']) - max(row['start'], left + w['start'])
                  >= min(.15, max(.01, (w['end'] - w['start']) / 2))]
        if chosen:
            words.extend(chosen)
            evidence.append(item)
    text = ''.join(w['word'] for w in words).strip()
    if not words or artifact(text) or len(key(text)) > 96:
        return None
    result = {'text': text, 'words': words, 'avg_logprob': sum(r.get('avg_logprob', -2) for r in evidence) / len(evidence),
              'no_speech_prob': max(r.get('no_speech_prob', 1) for r in evidence)}
    if (result['avg_logprob'] < -.85 or result['no_speech_prob'] >= .6 or word_confidence(result) < .55
            or any(r.get('compression_ratio', 0) > 2.4 for r in evidence)):
        return None
    return result


def _apply(row: dict, replacement: dict) -> None:
    from transcript_refinement import _clear_translation
    row.setdefault('original_asr', {k: row[k] for k in ('text', 'start', 'end')})
    row.update({k: v for k, v in replacement.items() if k in ('text', 'words', 'avg_logprob', 'no_speech_prob', 'compression_ratio')})
    row['words'] = [{**w, 'start': max(row['start'], w['start']), 'end': min(row['end'], w['end'])} for w in row['words']]
    _clear_translation(row)


def apply_spelling(row: dict, old: str, new: str) -> None:
    """Change only the acoustically confirmed spelling, preserving the surrounding source."""
    from transcript_refinement import _clear_translation
    row.setdefault('original_asr', {k: row[k] for k in ('text', 'start', 'end')})
    offset = row['text'].find(old)
    words = row.get('words', [])
    if ''.join(w['word'] for w in words) == row['text']:
        first, last, cursor, begin = None, None, 0, 0
        for i, w in enumerate(words):
            end = cursor + len(w['word'])
            if end > offset and cursor < offset + len(old):
                if first is None:
                    first, begin = i, cursor
                last = i
            cursor = end
        if first is not None:
            group = words[first:last + 1]
            value = ''.join(w['word'] for w in group)
            local = offset - begin
            replacement = {**group[0], 'word': value[:local] + new + value[local + len(old):], 'end': group[-1]['end']}
            row['words'] = words[:first] + [replacement] + words[last + 1:]
    else:
        row.pop('words', None)
    row['text'] = row['text'][:offset] + new + row['text'][offset + len(old):]
    _clear_translation(row)


def review_sources(source: Path, cache: dict, path: Path, config: dict) -> list[dict]:
    import main
    from audio_review import ReviewRecognizer, decode_window, speech_seconds, closing_phrase, weak_closing
    from short_speech import alternate_available
    if cache.get('language') != 'ja' or config.get('quality', 'high') != 'high':
        return []
    selected = []
    for row in cache['segments']:
        if row.get('audio_review', {}).get('status') == 'omitted':
            continue
        reason, hints = _selection(row, cache)
        signature = main.fingerprint([row['text'], row['start'], row['end'], hints, VERSION])
        previous = row.get('source_review', {})
        if not reason or previous.get('signature') == signature and not previous.get('waiting_for_alternate'):
            continue
        selected.append((row, reason, hints, signature))
    if not selected:
        return []
    backup = path.with_name(f'task.before-source-review-v{VERSION}.json')
    if not backup.exists():
        main.save_json(backup, cache)
    can_compare = main.asr_settings(config)['model'] == 'large-v2' and alternate_available(config)
    changes = []
    for row, reason, hints, signature in selected:
        print(f"Verifying source #{row['id']} ({main.console_time(row['start'])}; {reason})...", flush=True)
        review = {'version': VERSION, 'reason': reason, 'signature': signature, 'status': 'retained', 'passes': {}}
        if reason == 'decoration_only':
            review['status'] = 'omitted'
        elif reason == 'cached_homophone':
            candidate = row['refinement']['alternate_recognized'][0]
            for old, new in hints:
                if key(new) in key(candidate['text']):
                    review['original_text'] = row['text']
                    apply_spelling(row, old, new)
                    review['status'] = 'recovered'
                    break
        else:
            left, right = max(0, row['start'] - .8), row['end'] + .8
            audio = decode_window(source, left, right)
            span = audio[max(0, round((row['start'] - left) * 16000)):round((row['end'] - left) * 16000)]
            speech = speech_seconds(span, threshold=.5)
            ratio = speech / max(.1, row['end'] - row['start'])
            review.update(speech_seconds=round(speech, 3), speech_ratio=round(ratio, 3))
            initial = _initial(row, cache)
            strong = (initial.get('avg_logprob', -2) > -.45 and initial.get('no_speech_prob', 1) < .3
                      and word_confidence(initial) >= .75)
            suspect_closing = reason == 'closing_evidence' and not strong and (weak_closing(row, cache, speech)
                              or ratio < .25 and (row.get('gap_review') or initial.get('avg_logprob', 0) < -.65 or initial.get('no_speech_prob', 0) > .3))
            if reason == 'closing_evidence' and not suspect_closing:
                pass
            elif can_compare:
                prompt = '、'.join(sorted({target for _, target in hints}))
                previous = row.get('source_review', {})
                reusable = (reason == 'contextual_spelling' and previous.get('signature') ==
                            main.fingerprint([row['text'], row['start'], row['end'], hints, 2])
                            and set(previous.get('passes', {})) == {'primary', 'alternate'})
                if reusable:
                    review['passes'] = previous['passes']
                    review['reused_acoustic_passes'] = True
                else:
                    for label, alternate in [('primary', False), ('alternate', True)]:
                        recognizer = ReviewRecognizer(config, alternate=alternate)
                        try:
                            items = recognizer.timed(audio, 'ja', context=prompt)
                            review['passes'][label] = {'model': recognizer.model_name, 'items': items}
                        finally:
                            recognizer.model = None
                a = focused(review['passes']['primary']['items'], row, left)
                b = focused(review['passes']['alternate']['items'], row, left)
                distinct = bool(review['passes']['primary']['model'] and review['passes']['alternate']['model']
                                and review['passes']['primary']['model'] != review['passes']['alternate']['model'])
                agree = bool(a and b and distinct and SequenceMatcher(None, reading(a['text']), reading(b['text']), autojunk=False).ratio() >= .94)
                if reason == 'closing_evidence':
                    review['status'] = 'retained' if agree and closing_phrase(a['text']) and closing_phrase(b['text']) and ratio >= .2 else 'omitted'
                elif reason == 'contextual_spelling':
                    review['status'] = 'unresolved'
                    if agree:
                        for old, new in hints:
                            expected = reading(row['text'].replace(old, new, 1))
                            if all(key(new) in key(h['text']) and SequenceMatcher(None, expected, reading(h['text']), autojunk=False).ratio() >= .88 for h in (a, b)):
                                review['original_text'] = row['text']
                                apply_spelling(row, old, new)
                                review['status'] = 'recovered'
                                break
                elif (agree and not closing_phrase(a['text']) and not closing_phrase(b['text'])
                      and key(a['text']) == key(b['text']) and len(key(b['text'])) >= 2
                      and not spelling_hints({**row, 'text': b['text']}, cache['segments'])):
                    review['original_text'] = row['text']
                    _apply(row, b)
                    review['status'] = 'recovered'
                else:
                    review['status'] = 'unresolved' if reason == 'mixed_script' else 'omitted'
            else:
                review['status'] = 'unresolved'
                review['waiting_for_alternate'] = True
        if review['status'] == 'omitted':
            row.setdefault('original_asr', {k: row[k] for k in ('text', 'start', 'end')})
            row['audio_review'] = {'version': 4, 'status': 'omitted', 'reason': reason,
                                   'note': 'Source verification rejected an artifact or unconfirmed low-evidence phrase.'}
        elif reason == 'closing_evidence':
            row['audio_review'] = {**row.get('audio_review', {}), 'version': 4, 'status': 'reviewed', 'closing_checked': True}
        # A successful recovery checkpoints its current source so the next run can reuse it.
        review['signature'] = main.fingerprint([row['text'], row['start'], row['end'], spelling_hints(row, cache['segments']) if reason == 'contextual_spelling' else [], VERSION])
        row['source_review'] = review
        changes.append({'id': row['id'], **review})
        main.save_json(path, cache)
    return changes
