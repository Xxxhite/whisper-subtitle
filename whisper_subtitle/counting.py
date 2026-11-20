"""Recognize explicit counting contexts and render standalone numbers locally."""
import re
import unicodedata

READINGS = {'ぜろ': 0, 'れい': 0, '零': 0, 'いち': 1, '一': 1, 'に': 2, '二': 2,
            'さん': 3, '三': 3, 'よん': 4, 'し': 4, '四': 4, 'ご': 5, '五': 5,
            'ろく': 6, '六': 6, 'なな': 7, 'しち': 7, '七': 7, 'はち': 8, '八': 8,
            'きゅう': 9, 'く': 9, '九': 9, 'じゅう': 10, '十': 10}


def number_key(text: str) -> str:
    value = unicodedata.normalize('NFKC', text).strip(' \t\n、,。.!！?？…~～「」『』"')
    return ''.join(chr(ord(c)-0x60) if 'ァ' <= c <= 'ヶ' else c for c in value).replace('ー', '')


def number(text: str, *, counting: bool = False) -> int | None:
    value = number_key(text)
    if re.fullmatch(r'[0-9]{1,4}', value):
        return int(value)
    if counting or value == 'ぜろ':
        return READINGS.get(value)
    return None


def sessions(rows: list[dict]) -> list[tuple[float, float]]:
    """Bound a declared count by an explicit zero or eight minutes."""
    result, active, deadline = [], None, 0
    for row in sorted(rows, key=lambda r: (r['start'], r['end'])):
        if row.get('audio_review', {}).get('status') == 'omitted':
            continue
        text = unicodedata.normalize('NFKC', row['text'])
        declaration = bool(re.search(r'数え(?:ていく|てから|るね|ます|ていき)|カウント(?:ダウン)?(?:だけ)?(?:する|します|していく|(?:を)?やり直し)', text))
        if active is not None and row['start'] > deadline:
            result.append((active, deadline))
            active = None
        if declaration and active is None:
            active = row['end']
        if declaration:
            deadline = row['end'] + 480
        if active is not None and row['start'] >= active:
            if number(text, counting=True) == 0 or re.search(r'(?:数え|カウント).{0,5}(?:やめ|止め|終わ)', text):
                result.append((active, row['end']))
                active = None
    if active is not None:
        result.append((active, deadline))
    return result


def in_session(row: dict, spans: list[tuple[float, float]]) -> bool:
    return any(left <= row['start'] <= right for left, right in spans)


def apply_translations(cache: dict, book) -> int:
    """Keep user rules authoritative while removing numeric LLM ambiguity."""
    from .dictionary_rules import source_text
    if cache.get('language') != 'ja':
        return 0
    spans = sessions(cache['segments'])
    changed = 0
    for row in cache['segments']:
        if row.get('translation_fragment') or row.get('audio_review', {}).get('status') == 'omitted':
            continue
        text = source_text(row)
        value = number(text, counting=in_session(row, spans))
        if value is None or any(number_key(g['source']) == number_key(text) for g in row.get('glossary_terms', [])):
            continue
        key = number_key(text)
        rendered = key if re.fullmatch(r'[0-9]{1,4}', key) else str(value)
        if row.get('model_zh') != rendered or not row.get('zh'):
            book.store(row, rendered, 'ja')
            row.pop('needs_audio_review', None)
            changed += 1
        row['numeric_translation'] = {'version': 1, 'value': rendered}
    return changed
