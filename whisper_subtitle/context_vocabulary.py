"""Propose bounded acoustic vocabulary from persistent source topics and readings."""
from difflib import SequenceMatcher
from functools import lru_cache
import re
import unicodedata

from .source_checks import reading
from .subtitle_processing import kana_unit_key
from .word_boundaries import tokenizer

ANCHORS = (('フェラ',), ('おちんぽ', 'ちんぽ'), ('射精',), ('精液',), ('我慢汁',), ('勃起', 'ぼっき'))
VOCABULARY = ('亀頭', '敏感', '舌先', '射精', '精液', '濃厚精液', '濃厚な精液', '我慢汁', '興奮')
LITERAL_CONTEXT = ('医師', '病院', '診察', '検査', '診断', '治療', '感染', 'カメラ', '撮', '絵', '画家',
                   'スケッチ', '申し訳', '謝る', '反省', 'エンジン', '機械', '排気量')


def context_text(row: dict, rows: list[dict], seconds: int) -> str:
    return kana_unit_key(row['text'] + '\n' + '\n'.join(r['text'] for r in rows
                        if row['start'] - seconds <= r['end'] <= row['start'] and r['id'] != row['id']
                        and r.get('audio_review', {}).get('status') != 'omitted')[-8000:])


def topic_evidence(row: dict, rows: list[dict]) -> list[str]:
    context = context_text(row, rows, 480)
    return [group[0] for group in ANCHORS if any(kana_unit_key(word) in context for word in group)]


def near_reading(text: str) -> str:
    # Voicing normalization proposes candidates only; acceptance still uses actual model evidence.
    return ''.join(c for c in unicodedata.normalize('NFD', reading(text)) if not unicodedata.combining(c))


@lru_cache(maxsize=1024)
def noun_spans(text: str) -> tuple[str, ...]:
    tokens = list(tokenizer().tokenize(text))
    result = set()
    for i in range(len(tokens)):
        value = ''
        proper = False
        for t in tokens[i:i + 3]:
            pos = t.part_of_speech.split(',')
            if pos[0] not in {'名詞', '接頭詞'} or pos[2] == '人名' and pos[1] == '接尾':
                break
            proper |= pos[1] == '固有名詞'
            value += t.surface
            if (1 < len(value) <= 8 and re.search(r'[一-鿿]', value)
                    and (not proper or t.surface in {'液', '汁'})):
                result.add(value)
    return tuple(sorted(result, key=lambda x: (-len(x), x)))


def vocabulary_hints(row: dict, rows: list[dict], legacy: tuple) -> list[tuple[str, str]]:
    local = context_text(row, rows, 120)
    active = len(topic_evidence(row, rows)) >= 2
    literal = any(kana_unit_key(word) in local for word in LITERAL_CONTEXT)
    hints = []
    for suspects, target, required, excluded in legacy:
        scoped = any(kana_unit_key(word) in local for word in required)
        if target in VOCABULARY or target == 'フェラ':
            scoped |= active and not literal
        if not scoped or any(kana_unit_key(word) in local for word in excluded):
            continue
        for suspect in suspects:
            if suspect not in row['text']:
                continue
            if suspect=='ばっか' and not re.search(r'ここ[、,\s]*ばっかにな',row['text']):
                continue
            if suspect == 'お部屋' and not re.search(r'お部屋(?:なんて|を)?され', row['text']):
                continue
            hints.append((suspect, target))
    if active and not literal:
        proposals = []
        for source in noun_spans(row['text']):
            if source in VOCABULARY:
                continue
            original = near_reading(source)
            for target in VOCABULARY:
                if source in target or target in source:
                    continue
                score = SequenceMatcher(None, original, near_reading(target), autojunk=False).ratio()
                if score >= .75:
                    proposals.append((score, len(source), source, target))
        for _, _, source, target in sorted(proposals, reverse=True):
            if any(source in old or old in source for old, _ in hints):
                continue
            hints.append((source, target))
            if len(hints) >= 2:
                break
    return hints[:2]
