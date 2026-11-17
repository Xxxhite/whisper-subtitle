"""Shared checks for malformed ASR and acoustically implausible subtitle text."""
from functools import lru_cache
import re
import unicodedata


def key(text: str) -> str:
    return ''.join(c for c in unicodedata.normalize('NFKC', text) if c.isalnum() and c not in 'ー々ゝゞヽヾ')


def artifact(text: str) -> str | None:
    if '\ufffd' in text or any(unicodedata.category(c) == 'Cs' for c in text):
        return 'malformed_text'
    compact = key(text)
    if not compact:
        return 'decoration_only'
    if len(compact) >= 96 and re.search(r'(.{1,8}?)\1{15,}', compact):
        return 'extreme_repetition'
    return None


def implausible_duplicate(row: dict, rows: list[dict]) -> bool:
    compact = key(row['text'])
    duration = row['end'] - row['start']
    return (len(compact) >= 12 and duration > 0 and len(compact) / duration > 18
            and any(other['id'] != row['id'] and 0 < row['start'] - other['start'] < 90
                    and key(other['text']) == compact for other in rows))


@lru_cache(maxsize=1)
def _reader():
    from pykakasi import kakasi
    return kakasi()


@lru_cache(maxsize=2048)
def reading(text: str) -> str:
    """Use readings only for candidate comparison; source spelling stays intact."""
    from short_speech import phonetic_key
    return phonetic_key(''.join(part['hira'] for part in _reader().convert(text)))


def word_confidence(row: dict) -> float:
    values = [w.get('probability', 0) for w in row.get('words', []) if key(w['word'])]
    return sum(values) / len(values) if values else 0
