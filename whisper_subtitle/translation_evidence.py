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

def _aligned_hypotheses(row, records):
    """Compare complete local utterances, excluding speech from the adjoining line."""
    for rec in records:
        for item in rec.get("items", []):
            words = [w for w in item.get("words", []) if re.search(r"\w", w["word"])]
            if len(item["text"]) > max(len(row["text"]) * 2 + 8, 24) or item.get("compression_ratio", 0) > 2.2:
                continue
            if not words or item.get("no_speech_prob", 1) >= .45 or item.get("avg_logprob", -2) < -1:
                continue
            start = words[0]["start"] + rec["left"]
            end = words[-1]["end"] + rec["left"]
            if (start < row["start"] - 1 or end > row["end"] + 1
                    or min(end, row["end"]) - max(start, row["start"]) < .45 * (row["end"] - row["start"])):
                continue
            yield {"model": rec["model"], "text": item["text"], "start": start, "end": end,
                   "words": words, "left": rec["left"]}


def _meaning_shape(text):
    tokens = list(tokenizer().tokenize(text))
    negative = any(t.base_form in {"ない", "ぬ"} and t.part_of_speech.startswith("助動詞") for t in tokens if t.surface != "ん") or "ません" in text
    question = bool(re.search(r"(?:です|ます|なの)か[。？?…]*$", text))
    persons = tuple(t.base_form for t in tokens if t.part_of_speech.startswith("名詞,代名詞")
                    and t.base_form in {"私", "僕", "俺", "君", "あなた", "彼", "彼女"})
    return negative, question, persons


def assess_translation(row, rows):
    """Select a supported phrase, a timed placeholder, or a report-only interval."""
    review = row.get("source_review", {})
    unresolved = review.get("status") == "unresolved"
    if not unresolved and not uncertain_source(row):
        return None
    if (row.get("audio_review", {}).get("status") == "omitted" or not row.get("words")
            or row.get("count_review", {}).get("status") == "recovered"):
        return None
    from .counting import number
    from .subtitle_processing import repeated_kana
    units = re.findall(r"[ぁ-ヺ一-鿿0-9０-９]+", row["text"])
    if (re.fullmatch(r"(.{1,4})\1+", "".join(units)) or (len(units) > 1 and len(set(units)) == 1)
            or number(row["text"], counting=True) is not None or repeated_kana(row["text"])):
        return None
    if len(row["text"]) > 32 or row["end"] - row["start"] > 14:
        return None
    records = list(_records(row, rows))
    if unresolved and review.get("reason") != "local_word_evidence":
        records.extend(review.get("passes", {}).values())
    records = [r for r in records if r.get("model") and "left" in r]
    if len({r["model"] for r in records}) < 2:
        return None
    observations = list(_aligned_hypotheses(row, records))
    evidence = [{k: h[k] for k in ("model", "text", "start", "end")} for h in observations]
    def decision(mode, reason):
        return dict(mode=mode, source="", start=row["start"], end=row["end"], reason=reason, evidence=evidence)

    if (not observations and unresolved and review.get("speech_ratio", 1) < .1
            and row.get("no_speech_prob", 0) >= .6
            and all(not any(i.get("no_speech_prob", 0) < .6 for i in r.get("items", [])) for r in records)):
        result = decision("omit", "Neither acoustic pass confirmed speech in the low-voice interval.")
        result["evidence"] = [{"model": r["model"], "text": " / ".join(i["text"] for i in r.get("items", []))}
                              for r in records]
        return result

    from difflib import SequenceMatcher
    pairs = [(a, b) for n, a in enumerate(observations) for b in observations[n + 1:]
             if a["model"] != b["model"] and min(a["end"], b["end"]) > max(a["start"], b["start"])]
    def meaning_conflict(a, b):
        neg_a, question_a, who_a = _meaning_shape(a["text"])
        neg_b, question_b, who_b = _meaning_shape(b["text"])
        different = neg_a != neg_b or question_a != question_b or (who_a and who_b and who_a != who_b)
        if not different:
            return False
        def predicates(text):
            return {t.base_form for t in tokenizer().tokenize(text)
                    if t.part_of_speech.startswith(("動詞,自立", "形容詞,自立", "名詞,形容動詞語幹"))}
        return (bool(predicates(a["text"]) & predicates(b["text"]))
                and SequenceMatcher(None, reading(a["text"]), reading(b["text"])).ratio() >= .55)

    if pairs and all(meaning_conflict(a, b) for a, b in pairs):
        return decision("unclear", "Aligned speech hypotheses disagree on negation, question, or participant.")

    fragment = supported_fragment(row, rows)
    if fragment:
        fragment.update(mode="partial", before=True, after=fragment["end"] < row["words"][-1]["end"] - .05)
        return fragment
    weak = [w for w in row["words"] if w.get("probability", 1) < .42 and re.search(r"[一-鿿ぁ-ヺ]", w["word"])]
    if not pairs or not weak:
        return None
    # Only keep a self-contained predicate. Never carry a disputed modifier or noun into it.
    source = row["text"]
    words = row["words"]
    if "".join(w["word"] for w in words) != source:
        return None
    lexical_starts = set()
    offset = 0
    for token in tokenizer().tokenize(source):
        lexical_starts.add(offset)
        offset += len(token.surface)
    for n in range(1, len(words)):
        phrase = "".join(w["word"] for w in words[n:])
        plain = re.sub(r"[^\w]", "", phrase)
        # Do not drop an otherwise reliable clause along with one doubtful word.
        if len(source) - len(phrase) > 8 or re.search(r"[。！？!?]", source[:-len(phrase)]):
            continue
        if len(source) - len(phrase) not in lexical_starts or len(plain) < 3 or not any(w in weak for w in words[:n]):
            continue
        tokens = list(tokenizer().tokenize(plain))
        if not tokens or not tokens[0].part_of_speech.startswith(("名詞", "動詞,自立", "形容詞,自立")):
            continue
        if tokens[0].base_form in {"くださる", "しまう", "よう", "する", "みたい"}:
            continue
        if not any(t.part_of_speech.startswith(("助動詞", "動詞,自立", "形容詞,自立")) for t in tokens):
            continue
        # The final lexical token often has punctuation/silence attached. Use the onset
        # of the ending as an additional timing anchor when comparing the same suffix.
        def prefix(h):
            for j in range(1, len(h["words"])):
                group = h["words"][j:]
                text = "".join(w["word"] for w in group)
                if re.sub(r"[^\w]", "", text) != plain:
                    continue
                if (abs(group[-1]["start"] + h["left"] - words[-1]["start"]) <= .65
                        and group[0]["end"] + h["left"] > words[n]["start"]
                        and sum(w.get("probability", 0) for w in group) / len(group) >= .7
                        and min(w.get("probability", 0) for w in group) >= .25):
                    return reading("".join(w["word"] for w in h["words"][:j]))
            return ""
        for a, b in pairs:
            left, right = prefix(a), prefix(b)
            if left and right and SequenceMatcher(None, left, right).ratio() < .8 and _meaning_shape(a["text"]) == _meaning_shape(b["text"]):
                result = decision("partial", "Independent models agree on the timed predicate but disagree before it.")
                result.update(source=phrase, start=words[n]["start"], before=True, after=False)
                return result
    for n, word in enumerate(words[:-1], 1):
        if not re.search(r"[。！？!?]$", word["word"]) or not any(w in weak for w in words[n:]):
            continue
        phrase = "".join(w["word"] for w in words[:n])
        if len(reading(phrase)) < 3:
            continue
        def remainder(h):
            for k, w in enumerate(h["words"][:-1], 1):
                prefix_text = "".join(t["word"] for t in h["words"][:k])
                if (reading(prefix_text) == reading(phrase)
                        and abs(w["end"] + h["left"] - word["end"]) <= .55):
                    return reading("".join(t["word"] for t in h["words"][k:]))
            return ""
        for a, b in pairs:
            first, second = remainder(a), remainder(b)
            if first and second and first != second:
                result = decision("partial", "The opening clause is confirmed; the following words disagree.")
                result.update(source=phrase, end=word["end"], before=False, after=True)
                return result
    if (pairs and all(reading(row["text"]) != reading(h["text"]) for h in observations)
            and all(SequenceMatcher(None, reading(a["text"]), reading(b["text"])).ratio() < .45 for a,b in pairs)
            and sum(w.get("probability", 1) < .42 for w in words) >= 2):
        return decision("unclear", "Speech is present, but no reliable wording could be aligned between models.")
    return None
