"""Protect lexical units while mapping ASR token times to subtitle boundaries."""
from functools import lru_cache
import re


@lru_cache(maxsize=1)
def tokenizer():
    try:
        from janome.tokenizer import Tokenizer
    except ImportError as exc:
        raise RuntimeError('Japanese word splitting requires Janome. Install requirements.txt first.') from exc
    return Tokenizer()


def safe_offsets(text: str, language: str | None = None, terms: tuple[str, ...] = ()) -> set[int]:
    """Return character offsets between complete words, including attached grammar."""
    japanese = language == 'ja' or language is None and bool(re.search(r'[ぁ-ゖァ-ヺ]', text))
    allowed = set(range(1, len(text) + 1))
    if japanese:
        allowed = {len(text)}
        cursor, previous = 0, None
        for token in tokenizer().tokenize(text):
            if token.surface.isspace():
                continue
            start = text.find(token.surface, cursor)
            if start < 0:
                return {len(text)}
            end = start + len(token.surface)
            pos = token.part_of_speech.split(',')
            allowed.add(end)
            attached = pos[0] in {'助詞', '助動詞', '記号'} or pos[1] in {'接尾', '非自立'}
            if attached or previous and previous[0] == '接頭詞':
                allowed.discard(start)
                allowed.discard(cursor)
            if previous and previous[0] == '助詞' and previous[1] == '連体化':
                allowed.discard(start)
                allowed.discard(cursor)
            if previous and previous[0] == '副詞' and pos[0] in {'動詞', '形容詞'}:
                allowed.discard(start)
                allowed.discard(cursor)
            if previous and (previous[0] == '名詞' and token.base_form in {'する', 'いたす', 'なさる'}
                             or previous[0] == '形容詞' and token.base_form in {'なる', 'する'}):
                allowed.discard(start)
                allowed.discard(cursor)
            cursor, previous = end, pos
    # Latin words and configured terms may span several Whisper tokens.
    spans = [m.span() for m in re.finditer(r"[A-Za-z]+(?:['’-][A-Za-z]+)*", text)]
    # Rhythmic kana may be unknown words to the tokenizer. Keep each repeated unit intact.
    if japanese:
        for match in re.finditer(r'([ぁ-ゖァ-ヺー]{2,8}?)\1{2,}', text):
            size = len(match[1])
            for start in range(match.start(), match.end(), size):
                spans.append((start, start + size))
                allowed.add(start + size)
    for term in terms:
        if not term:
            continue
        start = 0
        while (start := text.find(term, start)) >= 0:
            spans.append((start, start + len(term)))
            start += 1
    for start, end in spans:
        allowed.difference_update(range(start + 1, end))
    return allowed


def safe_token_ends(words: list[dict], language: str | None = None, terms: tuple[str, ...] = ()) -> set[int]:
    text = ''.join(w['word'] for w in words)
    allowed = safe_offsets(text, language, terms)
    ends, offset = set(), 0
    for i, word in enumerate(words):
        offset += len(word['word'])
        if offset in allowed:
            ends.add(i)
    return ends
