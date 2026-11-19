"""Identify a timed, translatable phrase when independent decoders dispute its noun."""
import re

from .source_checks import reading
from .translation_checks import uncertain_source
from .word_boundaries import tokenizer


def _records(row, rows):
    review = row.get('source_review', {})
    if review.get('reason') == 'local_word_evidence':
        yield from review.get('passes', {}).values()
    detail = row.get('refinement', {})
    if (detail.get('status') != 'uncertain' or detail.get('parts', 1) != 1
            or detail.get('parent_id') != row['id'] or detail.get('parent_ids')):
        return
    # Older single-parent reviews used .3 seconds of padding bounded by the previous line.
    left = detail.get('window_start')
    if left is None:
        left = max(0, row['start'] - .3, max((r['end'] for r in rows if r is not row
                   and r['end'] <= row['start']), default=0))
    for field, model in [('recognized', 'primary_model'), ('alternate_recognized', 'alternate_model')]:
        if detail.get(field) and detail.get(model):
            yield {'items': detail[field], 'model': detail[model], 'left': left}


def _noun(tokens, index):
    token = tokens[index]
    if not token.part_of_speech.startswith('名詞'):
        return ''
    if index and token.part_of_speech.startswith('名詞,接尾') and tokens[index - 1].part_of_speech.startswith('名詞'):
        return tokens[index - 1].surface + token.surface
    return token.surface


def _phrase_evidence(record, phrase, start, last_start, end):
    wanted = reading(phrase)
    for item in record['items']:
        if item.get('avg_logprob', -2) < -1 or item.get('no_speech_prob', 1) >= .55:
            continue
        words = item.get('words', [])
        for first in range(1, len(words)):
            if abs(record['left'] + words[first]['start'] - start) > .55:
                continue
            for stop in range(first + 1, len(words) + 1):
                group = words[first:stop]
                end_delta = abs(record['left'] + group[-1]['end'] - end)
                same_final_onset = abs(record['left'] + group[-1]['start'] - last_start) <= .35
                if end_delta > .55 and not (end - last_start >= 1 and same_final_onset and end_delta <= 1):
                    continue
                text = ''.join(w['word'] for w in group)
                if reading(text) != wanted or min(w.get('probability', 0) for w in group) < .45:
                    continue
                if sum(w['probability'] for w in group) / len(group) < .72:
                    continue
                prefix = ''.join(w['word'] for w in words[:first]).strip()
                tokens = list(tokenizer().tokenize(prefix))
                name = _noun(tokens, len(tokens) - 1) if tokens else ''
                if not re.search('[一-鿿]', name):
                    continue
                remaining = len(name)
                probabilities = []
                for w in reversed(words[:first]):
                    probabilities.append(w.get('probability', 0))
                    remaining -= len(w['word'].strip())
                    if remaining <= 0:
                        break
                return {'model': record['model'], 'noun': name, 'min_probability': min(probabilities)}
    return None


def supported_fragment(row: dict, rows: list[dict]) -> dict | None:
    if not uncertain_source(row) or not 6 <= len(row['text']) <= 32 or row['end'] - row['start'] > 8:
        return None
    words = row.get('words', [])
    if ''.join(w['word'] for w in words) != row['text']:
        return None
    records = [p for p in _records(row, rows) if p.get('model') and 'left' in p]
    if len({p['model'] for p in records}) < 2:
        return None
    # Offset pairs keep the comparison on complete ASR tokens and in the same audio interval.
    boundaries, offset = {0: 0}, 0
    for index, word in enumerate(words, 1):
        offset += len(word['word'])
        boundaries[offset] = index
    source = row['text']
    if re.search(r'[?？]', source):
        return None
    cursor = 0
    tokens = list(tokenizer().tokenize(source))
    for index, token in enumerate(tokens):
        position = source.find(token.surface, cursor)
        if position < 0:
            return None
        cursor = position + len(token.surface)
        noun = _noun(tokens, index)
        cut = cursor
        if not re.fullmatch('[一-鿿]{2,}', noun) or cut - len(noun) > 6:
            continue
        if cut not in boundaries or cut == len(source) or re.search(r'ない|ません|ずに', source[:cut]):
            continue
        suffix = source[cut:]
        if not any(t.part_of_speech.startswith('動詞,自立') for t in tokens[index + 1:index + 3]):
            continue
        clause = re.split(r'[、。！？!?…]', suffix, maxsplit=1)[0]
        for size in range(len(clause), 3, -1):
            phrase = clause[:size]
            if size != len(clause) and not phrase.endswith(('ように', 'だけで')):
                continue
            # Whisper often attaches punctuation to the last spoken token.
            finish = cut + size
            while finish < len(source) and source[finish] in '、。！？!?…':
                finish += 1
            if finish not in boundaries:
                continue
            tail = words[boundaries[finish]:]
            if tail and (not any(w.get('probability', 1) < .3 for w in tail)
                         or re.search(r'ない|ません|[?？]', source[finish:])):
                continue
            start = words[boundaries[cut]]['start']
            last = words[boundaries[finish] - 1]
            end = last['end']
            evidence = [e for p in records if (e := _phrase_evidence(p, phrase, start, last['start'], end))]
            if (len({e['model'] for e in evidence}) < 2 or len({reading(e['noun']) for e in evidence}) < 2
                    or any(reading(e['noun']) == reading(noun) and e['min_probability'] >= .45 for e in evidence)):
                continue
            return {'source': phrase, 'noun': noun, 'start': start, 'end': end, 'evidence': evidence}
    return None
