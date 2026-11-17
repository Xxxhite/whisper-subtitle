"""Checkpoint local evidence before accepting malformed text or contextual spelling changes."""
from difflib import SequenceMatcher
from itertools import combinations
from pathlib import Path
import re

from .source_checks import artifact, implausible_duplicate, key, reading, word_confidence

VERSION = 5
# Vocabulary hints select acoustic checks; they never perform source replacements directly.
# Each spelling change must be returned by both models, with unchanged surrounding words.
TERMS = (
    (('下先',), '舌先', ('耳', '舐', 'なめ'), ()),
    (('ひと先',), '舌先', ('耳', '舐', 'なめ'), ()),
    (('女の口',), '序の口', ('まだ',), ()),
    (('写真', '写生', '謝罪', '処生'), '射精', ('勃起', 'ぼっき', 'おちん', 'しこしこ', 'しご', '我慢汁'), ('カメラ', '撮', '絵', '画家', '謝る', '謝罪会見', '申し訳')),
    (('幸運',), '興奮', ('息', '体', '勃起', 'ぼっき', 'エッチ'), ('宝くじ', 'くじ', '幸運を祈')),
    (('繊維器', '繊益', '鮮液', '清液'), '精液', ('勃起', 'ぼっき', 'おちん', '我慢汁', 'バックハグ'), ('繊維工', '機械', '医師', '検査')),
    (('肺炎',), '快感', ('気持ち', 'マッサージ', 'しこ', 'おちん'), ('病院', '医師', '咳', '発熱', '治療')),
    (('壺',), 'ズボン', ('ズボン',), ('花瓶', '陶器', '焼き物')),
    (('夫婦',), 'ふーふー', ('ふーふー', '吹'), ('結婚', '妻', '夫婦生活')),
    (('お部屋',), 'フェラ', ('フェラ', 'おちん', '射精'), ('ホテル', '予約', '掃除', '間取り')),
    (('銀貫', '貧感'), '敏感', ('耳', 'なぞ', '舐'), ('銀行', '銀貨', '通貨')),
    (('飲め', 'のめ'), '舐め', ('耳', 'なめ', '舐'), ('飲み物', 'お茶', '酒', '水を')),
    (('散らして',), 'じらして', ('エッチ', '気持ち', 'おちん', '我慢'), ('掃除', '花びら', '散布', '紙')),
    (('おまご', 'ごまおこ'), 'おまんこ', ('おちん', 'ちんちん', 'エッチ', '精子'), ('孫', '祖母', '祖父', '子供')),
    (('おちいち',), 'おちんちん', ('気持ち', 'エッチ', 'しこ', '我慢'), ()),
    (('ばっか',), '真っ赤', ('耳', 'キス'), ('働', '仕事')),
    (('ずらして',), 'じらして', ('我慢', 'おちん', '精子'), ('位置', '椅子', '机', '身体を', '体を')),
)


def spelling_hints(row: dict, rows: list[dict]) -> list[tuple[str, str]]:
    from .context_vocabulary import vocabulary_hints
    return vocabulary_hints(row, rows, TERMS)


def _initial(row: dict, cache: dict) -> dict:
    parent = row.get('refinement', {}).get('parent_id', row['id'])
    return cache.get('refinement', {}).get('originals', {}).get(str(parent), row)


def _selection(row: dict, cache: dict) -> tuple[str | None, list]:
    from .audio_review import closing_phrase
    if artifact(row['text']):
        return artifact(row['text']), []
    if implausible_duplicate(row, cache['segments']):
        return 'implausible_duplicate', []
    if closing_phrase(row['text']):
        return 'closing_evidence', []
    from .sakura import rhythmic_input
    from .subtitle_processing import sound_key
    from .counting import number
    if (row['end'] - row['start'] >= 6 and len(key(row['text'])) <= 4
            and re.fullmatch(r'[ぁ-ゖァ-ヺ一-鿿ー]+[.…。!?？!]*',row['text'])
            and number(row['text'], counting=True) is None
            and sound_key(row['text']) is None and not rhythmic_input(row['text'])):
        return 'sparse_timing', []
    if cache.get('language') == 'ja':
        if re.search(r'[\uac00-\ud7a3]', row['text']):
            return 'mixed_script', []
        from .subtitle_processing import repeated_kana, sound_key
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
    from .transcript_refinement import _clear_translation
    row.setdefault('original_asr', {k: row[k] for k in ('text', 'start', 'end')})
    row.update({k: v for k, v in replacement.items() if k in ('text', 'words', 'avg_logprob', 'no_speech_prob', 'compression_ratio')})
    row['words'] = [{**w, 'start': max(row['start'], w['start']), 'end': min(row['end'], w['end'])} for w in row['words']]
    _clear_translation(row)


def apply_spelling(row: dict, old: str, new: str) -> None:
    """Change only the acoustically confirmed spelling, preserving the surrounding source."""
    from .transcript_refinement import _clear_translation
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


def confirmed_spellings(row: dict, hints: list, passes: dict, fallback_left: float) -> tuple:
    """Require distinct models to support each proposed word and the surrounding reading."""
    from .context_vocabulary import near_reading
    fold=lambda text:near_reading(text.replace('じ','ぢ').replace('ジ','ヂ'))
    pools = {}
    for label, variants in passes.items():
        pools[label] = [(p['model'], focused(p['items'], row, p.get('left', fallback_left))) for p in variants]
    for size in range(len(hints), 0, -1):
        for subset in combinations(hints, size):
            expected = row['text']
            for old, new in subset:
                expected = expected.replace(old, new)
            expected_reading = reading(expected)
            accepted = {}
            for label, pool in pools.items():
                accepted[label] = []
                for model, h in pool:
                    if (h and model and all(key(new) in key(h['text']) for _, new in subset)
                            and SequenceMatcher(None, expected_reading, reading(h['text']), autojunk=False).ratio() >= .88):
                        accepted[label].append((model, h))
            for a in accepted.get('primary', []):
                for b in accepted.get('alternate', []):
                    if a[0] != b[0] and SequenceMatcher(None, reading(a[1]['text']), reading(b[1]['text']), autojunk=False).ratio() >= .94:
                        if all(min(key(a[1]['text']).count(key(new)),key(b[1]['text']).count(key(new)))>=row['text'].count(old) for old,new in subset):
                            return subset
            # Whispered voicing can differ while both readings support the same contextual word.
            for model_a, a in pools.get('primary', []):
                for model_b, b in pools.get('alternate', []):
                    if not a or not b or not model_a or model_a == model_b:
                        continue
                    if not all(key(new) in key(a['text']) or key(new) in key(b['text']) for _, new in subset):
                        continue
                    if any(reading(old)==reading(new) and not (key(new) in key(a['text']) and key(new) in key(b['text'])) for old,new in subset):
                        continue
                    if (all(SequenceMatcher(None, fold(expected), fold(h['text']), autojunk=False).ratio() >= .96 for h in (a,b))
                            and SequenceMatcher(None, fold(a['text']), fold(b['text']), autojunk=False).ratio() >= .98):
                        if all(max(key(a['text']).count(key(new)),key(b['text']).count(key(new)))>=row['text'].count(old) for old,new in subset):
                            return subset
            if size==1:
                old,new=subset[0]
                position=row['text'].find(old)
                expected_window=reading(row['text'][max(0,position-6):position]+new+row['text'][position+len(old):position+len(old)+6])
                ear=(new=='舐め' and re.search(r'耳[、,\s]*'+re.escape(old),row['text']))
                def local(h):
                    choices=[new,old] if reading(old)!=reading(new) and fold(old)==fold(new) else [new]
                    if ear:choices+=['飲め','のめ']
                    result=[]
                    for token in choices:
                        for match in re.finditer(re.escape(token),h['text']):
                            text=h['text'][max(0,match.start()-6):match.start()]+new+h['text'][match.end():match.end()+6]
                            result.append((text,token==new))
                    return result
                for model_a,a in pools.get('primary',[]):
                    for model_b,b in pools.get('alternate',[]):
                        if not a or not b or not model_a or model_a==model_b:continue
                        for text_a,canonical_a in local(a):
                            for text_b,canonical_b in local(b):
                                if not(canonical_a or canonical_b):continue
                                if max(key(a['text']).count(key(new)),key(b['text']).count(key(new)))<row['text'].count(old):continue
                                if (all(SequenceMatcher(None,fold(expected_window),fold(t),autojunk=False).ratio()>=.9 for t in [text_a,text_b])
                                        and SequenceMatcher(None,fold(text_a),fold(text_b),autojunk=False).ratio()>=.94):
                                    return subset
    return ()


def review_sources(source: Path, cache: dict, path: Path, config: dict) -> list[dict]:
    from . import cli as main
    from .audio_review import ReviewRecognizer, decode_window, speech_seconds, closing_phrase, weak_closing
    from .short_speech import alternate_available
    if cache.get('language') != 'ja' or config.get('quality', 'high') != 'high':
        return []
    selected = []
    for row in cache['segments']:
        if row.get('audio_review', {}).get('status') == 'omitted':
            continue
        reason, hints = _selection(row, cache)
        policy = VERSION if reason in {'closing_evidence', 'sparse_timing'} else 4
        signature = main.fingerprint([row['text'], row['start'], row['end'], hints, policy])
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
            if reason == 'sparse_timing':
                strong |= (row.get('avg_logprob', -2) > -.45 and row.get('no_speech_prob', 1) < .3
                           and word_confidence(row) >= .75)
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
                            review['passes'][label] = {'model': recognizer.model_name, 'items': items, 'left': left}
                        finally:
                            recognizer.model = None
                a = focused(review['passes']['primary']['items'], row, left)
                b = focused(review['passes']['alternate']['items'], row, left)
                distinct = bool(review['passes']['primary']['model'] and review['passes']['alternate']['model']
                                and review['passes']['primary']['model'] != review['passes']['alternate']['model'])
                agree = bool(a and b and distinct and SequenceMatcher(None, reading(a['text']), reading(b['text']), autojunk=False).ratio() >= .94)
                if reason == 'closing_evidence':
                    review['status'] = 'retained' if agree and closing_phrase(a['text']) and closing_phrase(b['text']) and ratio >= .2 else 'omitted'
                elif reason == 'sparse_timing':
                    matched = (agree and reading(a['text']) == reading(row['text'])
                               and all(.1 <= h['words'][-1]['end'] - h['words'][0]['start'] <= 5 for h in (a, b))
                               and min(a['words'][-1]['end'], b['words'][-1]['end'])
                               - max(a['words'][0]['start'], b['words'][0]['start']) >= .1)
                    if matched:
                        start = max(row['start'], min(a['words'][0]['start'], b['words'][0]['start']))
                        end = min(row['end'], max(a['words'][-1]['end'], b['words'][-1]['end']))
                        if .1 <= end - start <= 5:
                            row.setdefault('original_asr', {k: row[k] for k in ('text', 'start', 'end')})
                            review['original_time'] = [row['start'], row['end']]
                            row.update(start=start, end=end, words=[{'word':row['text'],'start':start,'end':end}])
                            review['status'] = 'retimed'
                    elif (word_confidence(row) >= .75
                          and any(h and reading(row['text']) in reading(h['text']) for h in (a, b))):
                        review['status'] = 'retained'
                    elif not strong and speech < .5 and ratio < .15:
                        review['status'] = 'omitted'
                    else:
                        review['status'] = 'unresolved'
                elif reason == 'contextual_spelling':
                    review['status'] = 'unresolved'
                    from .context_vocabulary import topic_evidence
                    review['topic_evidence'] = topic_evidence(row, cache['segments'])
                    pools = {label: [p] for label, p in review['passes'].items()}
                    matched = confirmed_spellings(row, hints, pools, left)
                    if len(matched) < len(hints):
                        retry_left = max(0, row['start'] - 1.4)
                        retry_audio = decode_window(source, retry_left, row['end'] + 1.4)
                        review['retry_passes'] = {}
                        for label, alternate in [('primary', False), ('alternate', True)]:
                            recognizer = ReviewRecognizer(config, alternate=alternate)
                            try:
                                items = recognizer.timed(retry_audio, 'ja', context=prompt)
                                p = {'model': recognizer.model_name, 'items': items, 'left': retry_left}
                                review['retry_passes'][label] = p
                                pools[label].append(p)
                            finally:
                                recognizer.model = None
                        matched = confirmed_spellings(row, hints, pools, left)
                    if len(matched)<len(hints):
                        import numpy as np
                        review['channel_passes']={}
                        for channel in ['left','right']:
                            channel_left=max(0,row['start']-1)
                            clip=decode_window(source,channel_left,row['end']+1,channel=channel)
                            peak=float(np.percentile(np.abs(clip),99.5)) if len(clip) else 0
                            if peak>.0001:clip=np.clip(clip*min(8,max(1,.25/peak)),-1,1).astype(np.float32)
                            review['channel_passes'][channel]={}
                            for label,alternate in [('primary',False),('alternate',True)]:
                                recognizer=ReviewRecognizer(config,alternate=alternate)
                                try:
                                    items=recognizer.timed(clip,'ja',context=prompt)
                                    evidence={'model':recognizer.model_name,'items':items,'left':channel_left}
                                    review['channel_passes'][channel][label]=evidence;pools[label].append(evidence)
                                finally:recognizer.model=None
                            matched=confirmed_spellings(row,hints,pools,left)
                            if len(matched)==len(hints):break
                    if matched:
                        review['original_text'] = row['text']
                        review['confirmed_hints'] = list(matched)
                        for old, new in matched:
                            while old in row['text']:
                                apply_spelling(row, old, new)
                        review['status'] = 'recovered'
                        review['remaining_hints'] = [pair for pair in hints if pair not in matched]
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
        policy = VERSION if reason in {'closing_evidence', 'sparse_timing'} else 4
        review['signature'] = main.fingerprint([row['text'], row['start'], row['end'], spelling_hints(row, cache['segments']) if reason == 'contextual_spelling' else [], policy])
        row['source_review'] = review
        changes.append({'id': row['id'], **review})
        main.save_json(path, cache)
    return changes
