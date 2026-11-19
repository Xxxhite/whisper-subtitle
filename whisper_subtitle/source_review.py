"""Checkpoint local evidence before accepting malformed text or contextual spelling changes."""
from difflib import SequenceMatcher
from itertools import combinations
from pathlib import Path
import re

from .source_checks import artifact, implausible_duplicate, key, reading, word_confidence

VERSION = 5
WORD_FINAL_NASAL_HINT = ('精神', '精子')
SERVICE_NEAR_SOUND_HINT = ('魔女', 'マゾ')
QUIET_PHRASE_HINTS = {
    ('はっとこい', 'あったかい'), ('ドローン', 'とろーん'),
    ('安全と', 'ずっと'), ('隙間', '好き'), SERVICE_NEAR_SOUND_HINT,
}
# Vocabulary hints select acoustic checks; they never perform source replacements directly.
# Each spelling change needs independent acoustic evidence and matching surrounding words.
TERMS = (
    (('下先',), '舌先', ('耳', '舐', 'なめ'), ()),
    (('ひと先',), '舌先', ('耳', '舐', 'なめ'), ()),
    (('人の感触',), '舌の感触', ('舌を', '舌先', '舐', 'なめ'), ()),
    (('下を多くに',), '舌を奥に', ('浅いところ', '舐', 'なめ'), ('床', '下段')),
    (('出汁入れ',), '出し入れ', ('舌を', '舐', 'なめ'), ('料理', '昆布', '味噌汁', '鍋')),
    (('チラしたりしない',), 'じらしたりしない', ('我慢', 'エッチ', '気持ち', 'その分'), ('視線', 'チラ見', '覗')),
    (('息そうになった',), 'いきそうになった', ('エッチ', '我慢', '気持ち'), ('呼吸困難', '咳', '病院')),
    (('目奥まで',), 'ね、奥まで', ('吐いてる', '入ってる'), ('眼科', '視力', '目薬', '目の奥')),
    (('吐いてる',), '入ってる', ('奥まで', '中まで'), ('胃', '発熱', '吐き気', '悪心')),
    (('耳の実', '耳の目', '耳飲み'), '耳舐め', ('舐', 'なめ', '耳かき', 'エッチ'),
     ('果物', '果実', '木の実', '植物', '妖怪', '耳鼻科', '診察')),
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
    (('はっとこい',), 'あったかい', ('体温',), ()),
    (('ドローン',), 'とろーん', ('眠た', '眠そう', '眠く'), ('飛ばす', '飛行', '操縦', '撮影')),
    (('安全と',), 'ずっと', ('一緒だ', '一緒にいる'), ('安全と危険', '安全と衛生', '安全と安心')),
    (('魔女',), 'マゾ', ('ムラムラ', '仰向け', '抜いて', '我慢でき'),
     ('魔法', '魔術', '呪い', 'ハロウィン', '魔女狩り')),
)


def spelling_hints(row: dict, rows: list[dict]) -> list[tuple[str, str]]:
    from .context_vocabulary import vocabulary_hints
    hints = vocabulary_hints(row, rows, TERMS)
    text = row['text']
    # A repeated near-sound is plausible in quiet dialogue only when a nearby line establishes the word.
    if (re.fullmatch(r'(?:隙間[、。…\s]*|ね[えぇー][、。…\s]*){2,6}', text)
            and '隙間' in text and any(r is not row and row['start'] - 75 <= r['end'] <= row['end'] + 25
                                      and '好き' in r['text'] for r in rows)):
        hints = [('隙間', '好き'), *hints]
    required_phrases = {
        'ドローン': r'顔[、を\s]*ドローンって',
        '安全と': r'安全と[、\s]*一緒(?:だ|にい)',
        '魔女': r'魔女(?:じゃん|なんだから|だから|のお兄さん)',
    }
    hints = [hint for hint in hints if hint[0] not in required_phrases or re.search(required_phrases[hint[0]], text)]
    possessive = re.search(r'(?:君|きみ|あなた|お兄さん)の精神(?=[、。…\sを]|$)', row['text'])
    if possessive and row['text'].count('精神') == 1:
        neighbors = [item for item in rows if item is not row
                     and item.get('audio_review', {}).get('status') != 'omitted']
        before = '\n'.join(item['text'] for item in neighbors if row['start'] - 8 <= item['end'] <= row['start'])
        after = '\n'.join(item['text'] for item in neighbors if row['end'] <= item['start'] <= row['end'] + 8)
        before += '\n' + row['text'][:possessive.start()]
        after = row['text'][possessive.end():] + '\n' + after
        destination = r'[を、。…\sー]*(?:(?:私|わたし|僕|ぼく|俺)の)?(?:一番|いちばん)?(?:中|奥)に'
        if (re.search(r'(?:中|奥)に(?:出して|だして|射精して)', before)
                and re.match(destination + r'(?:ちょうだい|頂戴|入れて|出して|だして)', after)):
            return ([WORD_FINAL_NASAL_HINT] + hints)[:2]
    return hints[:2]


def _initial(row: dict, cache: dict) -> dict:
    parent = row.get('refinement', {}).get('parent_id', row['id'])
    return cache.get('refinement', {}).get('originals', {}).get(str(parent), row)


def contextual_homophones(row: dict, rows: list[dict]) -> list[tuple[str, str]]:
    """Disambiguate identical readings using explicit surrounding words."""
    text = row['text']
    if re.search(r'初めてで使命あり[、…\s]*(?:コース|予約)', text):
        return [('使命', '指名')]
    if re.search(r'髪パンツ[を、\s]*履', text):
        return [('髪パンツ', '紙パンツ')]
    if 'バッキン' in text:
        nearby = '\n'.join(r['text'] for r in rows if row['start'] - 12 <= r['end']
                           and r['start'] <= row['end'] + 12 and r.get('audio_review', {}).get('status') != 'omitted')
        if re.search(r'[0-9０-９一二三四五六七八九十百千]+万円', nearby) and re.search(r'払えない|払って|払える', nearby):
            return [('バッキン', '罰金')]
    return []


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
    from .translation_checks import action_sound
    if (row['end'] - row['start'] >= 6 and len(key(row['text'])) <= 4
            and re.fullmatch(r'[ぁ-ゖァ-ヺ一-鿿ー]+[.…。!?？!]*',row['text'])
            and number(row['text'], counting=True) is None
            and sound_key(row['text']) is None and not rhythmic_input(row['text']) and not action_sound(row['text'])):
        return 'sparse_timing', []
    if cache.get('language') == 'ja':
        if re.search(r'[\uac00-\ud7a3]', row['text']):
            return 'mixed_script', []
        from .subtitle_processing import repeated_kana, sound_key
        if (row.get('refinement', {}).get('status') == 'uncertain' and row.get('avg_logprob', 0) < -1.2
                and re.fullmatch(r'[ァ-ヺー、,。.…\s]+', row['text'])
                and repeated_kana(row['text']) and sound_key(row['text']) is None):
            return 'uncertain_repetition', []
        homophones = contextual_homophones(row, cache['segments'])
        if homophones:
            return 'contextual_homophones', homophones
        hints = spelling_hints(row, cache['segments'])
        # Reuse an already gathered alternate hypothesis instead of repeating audio work.
        details = row.get('refinement', {})
        alternatives = details.get('alternate_recognized', [])
        primaries = details.get('recognized', [])
        distinct = (details.get('alternate_model') and details.get('primary_model')
                    and details['alternate_model'] != details['primary_model'])
        if (hints and WORD_FINAL_NASAL_HINT not in hints and distinct and details.get('parts', 1) == 1
                and len(alternatives) == len(primaries) == 1):
            alt, primary = alternatives[0], primaries[0]
            if (not artifact(alt['text']) and reading(alt['text']) == reading(primary['text'])
                    and key(alt['text']) != key(row['text']) and alt['avg_logprob'] >= primary['avg_logprob'] + .1
                    and word_confidence(alt) >= .65 and any(key(new) in key(alt['text']) for _, new in hints)):
                return 'cached_homophone', hints
        if hints:
            return 'contextual_spelling', hints
        if _weak_content_words(row) and sum(w.get('probability', 1) < .42 for w in row['words']) >= 3:
            return 'local_word_evidence', []
        alignment = row.get('alignment_review', {})
        if (alignment.get('status') == 'uncertain'
                and _local_word_replacement(row, list(alignment.get('passes', {}).values()))):
            return 'local_word_evidence', []
    return None, []


def _weak_content_words(row: dict) -> list[dict]:
    return [word for word in row.get('words', []) if word.get('probability', 1) < .42
            and re.search(r'[一-鿿]', word['word'])]


def _local_word_replacement(row: dict, passes: list[dict]) -> dict | None:
    from .audio_review import closing_phrase
    from .alignment_review import overlapping_words
    from .word_boundaries import tokenizer
    old = reading(row['text'])
    opening_sound = re.match(r'^([あぁえぇんうぅはふへほっー]+)[?？!！…。、,\s]+', row['text'])
    candidates = [(p['model'], focused(p['items'], row, p['left'])) for p in passes]
    for (model_a, a), (model_b, b) in combinations(candidates, 2):
        if not a or not b or not model_a or not model_b or model_a == model_b:
            continue
        new = reading(a['text'])
        if (new == old or new != reading(b['text']) or key(a['text']) != key(b['text'])
                or closing_phrase(a['text']) or overlapping_words(a['words']) or overlapping_words(b['words'])
                or SequenceMatcher(None, old, new, autojunk=False).ratio() < .65):
            continue
        if opening_sound and not new.startswith(reading(opening_sound[1])):
            continue
        opening_token = next(iter(tokenizer().tokenize(row['text'].strip())), None)
        if opening_token and len(new) >= 5:
            # Both crops can begin inside the same word. Agreement on its suffix
            # does not license deleting the missing syllable from the original.
            inside = old.find(new[:5])
            if 0 < inside < len(reading(opening_token.surface)):
                continue
        first_token = next(iter(tokenizer().tokenize(a['text'])), None)
        if first_token and first_token.part_of_speech.startswith('助詞') and not row['text'].startswith(first_token.surface):
            continue
        first_a, first_b = a['words'][0], b['words'][0]
        # A crop that starts after a complete opening cannot disprove it.
        cut = min(first_a['start'], first_b['start']) - .25
        prefix = ''.join(w['word'] for w in row.get('words', []) if w['end'] <= cut)
        if key(prefix) and not new.startswith(reading(prefix)):
            continue
        start_agrees = (abs(first_a['start'] - first_b['start']) <= .6
                        or key(first_a['word']) == key(first_b['word'])
                        and abs(first_a['end'] - first_b['end']) <= .15
                        and min(first_a['end'], first_b['end']) > max(first_a['start'], first_b['start']))
        if not start_agrees or abs(a['words'][-1]['end'] - b['words'][-1]['end']) > .6:
            continue
        weak_words = _weak_content_words(row)
        alignment_disagreement = row.get('alignment_review', {}).get('status') == 'uncertain'
        if alignment_disagreement or any(all(h['words'][0]['start'] <= w['start'] + .4
                                              and h['words'][-1]['end'] >= w['end'] - .4
                                              for h in (a, b)) for w in weak_words):
            return max((a, b), key=lambda h: h['words'][0]['start'])
    return None


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


def _term_interval(hypothesis: dict, term: str) -> tuple[float, float] | None:
    text = ''.join(word['word'] for word in hypothesis['words'])
    start = text.find(term)
    if start < 0 or text.count(term) != 1:
        return None
    cursor = 0
    group = []
    for word in hypothesis['words']:
        end = cursor + len(word['word'])
        if end > start and cursor < start + len(term):
            group.append(word)
        cursor = end
    return group[0]['start'], group[-1]['end']


def _aligned_ear_licking(expected: str, a: dict, b: dict) -> bool:
    """Check the observed one-vowel disagreement over the same Japanese noun."""
    for canonical, near in ((a, b), (b, a)):
        for term in ('耳舐め', '耳なめ'):
            if (term not in canonical['text'] or '耳の目' not in near['text']
                    or reading(canonical['text']) != expected
                    or reading(near['text'].replace('耳の目', term)) != expected):
                continue
            first = _term_interval(canonical, term)
            second = _term_interval(near, '耳の目')
            if (first and second and min(first[1], second[1]) - max(first[0], second[0])
                    >= max(.2, .7 * max(first[1] - first[0], second[1] - second[0]))):
                return True
    return False


def _word_intervals(words: list[dict], term: str) -> list[tuple[float, float]]:
    text = ''.join(w['word'] for w in words)
    offsets = []
    cursor = 0
    for word in words:
        end = cursor + len(word['word'])
        offsets.append((cursor, end, word))
        cursor = end
    intervals = []
    for match in re.finditer(re.escape(term), text):
        group = [word for start, end, word in offsets if end > match.start() and start < match.end()]
        if group and word_confidence({'words': group}) >= .5:
            intervals.append((group[0]['start'], group[-1]['end']))
    return intervals


def _confirmed_quiet_word(row: dict, hint: tuple[str, str], passes: dict) -> bool:
    old, new = hint
    if new not in {'あったかい', '好き', 'マゾ'}:
        return False
    old_intervals = _word_intervals(row.get('words', []), old)
    if len(old_intervals) != row['text'].count(old) or not old_intervals:
        return False
    pools = {}
    for label, alternatives in passes.items():
        pools[label] = []
        for evidence in alternatives:
            items = [r for r in evidence['items'] if r.get('avg_logprob', -2) >= -.95
                     and r.get('no_speech_prob', 1) < .4 and not artifact(r['text'])]
            if new == 'あったかい' and not any('体温' in r['text'] for r in items):
                continue
            words = [{**w, 'start': w['start'] + evidence['left'], 'end': w['end'] + evidence['left']}
                     for r in items for w in r.get('words', [])]
            exact = _word_intervals(words, new)
            intervals = exact
            if new == 'あったかい':
                intervals = exact + _word_intervals(words, 'はったかい')
            intervals = [interval for interval in intervals if any(
                min(interval[1], prior[1]) - max(interval[0], prior[0]) >= .25 for prior in old_intervals)]
            if len(intervals) >= len(old_intervals):
                pools[label].append((evidence['model'], sorted(intervals), bool(exact)))
    overlap = lambda a, b: min(a[1], b[1]) - max(a[0], b[0]) >= .25
    for name_a, a, exact_a in pools.get('primary', []):
        for name_b, b, exact_b in pools.get('alternate', []):
            if not name_a or not name_b or name_a == name_b or not (exact_a or exact_b):
                continue
            for aa in combinations(a, len(old_intervals)):
                for bb in combinations(b, len(old_intervals)):
                    if all(overlap(x, y) and overlap(x, z) and overlap(y, z)
                           for x, y, z in zip(old_intervals, aa, bb)):
                        return True
    return False


def confirmed_spellings(row: dict, hints: list, passes: dict, fallback_left: float) -> tuple:
    """Require distinct models to support each proposed word and the surrounding reading."""
    from .context_vocabulary import near_reading
    fold=lambda text:near_reading(text.replace('じ','ぢ').replace('ジ','ヂ'))
    pools = {}
    for label, variants in passes.items():
        pools[label] = [(p['model'], focused(p['items'], row, p.get('left', fallback_left))) for p in variants]
    for size in range(len(hints), 0, -1):
        for subset in combinations(hints, size):
            if size == 1 and subset[0] in QUIET_PHRASE_HINTS and _confirmed_quiet_word(row, subset[0], passes):
                return subset
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
            # The final nasal distinguishes two valid nouns even in otherwise identical sentences.
            if WORD_FINAL_NASAL_HINT in subset:
                continue
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
                if new == '耳舐め' and row['text'].count(old) == 1:
                    for model_a, a in pools.get('primary', []):
                        for model_b, b in pools.get('alternate', []):
                            if (a and b and model_a and model_b and model_a != model_b
                                    and _aligned_ear_licking(expected_reading, a, b)):
                                return subset
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


def _review_policy(reason: str, hints: list):
    if SERVICE_NEAR_SOUND_HINT in hints:
        return 'service-near-sound-v1'
    if set(hints) & QUIET_PHRASE_HINTS:
        return 'quiet-phrase-interval-v1'
    return VERSION if reason in {'closing_evidence', 'sparse_timing'} else 4


def review_sources(source: Path, cache: dict, path: Path, config: dict) -> list[dict]:
    from . import cli as main
    from .audio_review import ReviewRecognizer, decode_window, speech_seconds, closing_phrase, weak_closing, normalize_review_audio
    from .short_speech import alternate_available
    if cache.get('language') != 'ja' or config.get('quality', 'high') != 'high':
        return []
    selected = []
    for row in cache['segments']:
        if row.get('audio_review', {}).get('status') == 'omitted':
            continue
        reason, hints = _selection(row, cache)
        policy = _review_policy(reason, hints)
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
        elif reason == 'contextual_homophones':
            review['original_text'] = row['text']
            for old, new in hints:
                while old in row['text']:
                    apply_spelling(row, old, new)
            review['status'] = 'recovered'
        elif reason == 'cached_homophone':
            candidate = row['refinement']['alternate_recognized'][0]
            for old, new in hints:
                if key(new) in key(candidate['text']):
                    review['original_text'] = row['text']
                    apply_spelling(row, old, new)
                    review['status'] = 'recovered'
                    break
        elif reason == 'local_word_evidence':
            review['status'] = 'unresolved'
            passes = list(row.get('alignment_review', {}).get('passes', {}).values())
            replacement = _local_word_replacement(row, passes)
            if replacement is None and can_compare and _weak_content_words(row):
                left, right = max(0, row['start'] - .8), row['end'] + .8
                channels = {channel: normalize_review_audio(decode_window(source, left, right, channel=channel),
                            peak_target=.25, max_gain=5, amplify_only=True) for channel in ('left', 'right')}
                for alternate in (False, True):
                    recognizer = ReviewRecognizer(config, alternate=alternate)
                    try:
                        for channel, audio in channels.items():
                            items = recognizer.short_clip(audio)
                            evidence = {'model': recognizer.model_name, 'items': items, 'left': left}
                            review['passes'][f'{alternate}:{channel}'] = evidence
                            passes.append(evidence)
                    finally:
                        recognizer.model = None
                replacement = _local_word_replacement(row, passes)
            if replacement:
                review['original_text'] = row['text']
                _apply(row, replacement)
                review['status'] = 'recovered'
            review['waiting_for_alternate'] = not can_compare and not replacement
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
            if (reason == 'closing_evidence' and row.get('gap_review') and row['end'] - row['start'] < .25
                    and not speech and not speech_seconds(audio, threshold=.5)):
                review['status'] = 'omitted'
            elif reason == 'closing_evidence' and not suspect_closing:
                pass
            elif can_compare:
                prompt = '、'.join(sorted({target for old, target in hints if (old, target) not in QUIET_PHRASE_HINTS}))
                previous = row.get('source_review', {})
                quiet_hint = bool(set(hints) & QUIET_PHRASE_HINTS)
                evidence_policies = [4] if quiet_hint else [2]
                if SERVICE_NEAR_SOUND_HINT in hints:
                    evidence_policies.append('quiet-phrase-interval-v1')
                reusable = (reason == 'contextual_spelling' and previous.get('signature') in
                            {main.fingerprint([row['text'], row['start'], row['end'], hints, policy]) for policy in evidence_policies}
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
                    if reusable and quiet_hint:
                        for field in ('retry_passes', 'channel_passes'):
                            if field in previous:
                                review[field] = previous[field]
                        for saved in [review.get('retry_passes', {}), *review.get('channel_passes', {}).values()]:
                            for label, evidence in saved.items():
                                pools[label].append(evidence)
                    matched = confirmed_spellings(row, hints, pools, left)
                    if len(matched) < len(hints) and 'retry_passes' not in review:
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
                    if len(matched)<len(hints) and 'channel_passes' not in review:
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
                    if SERVICE_NEAR_SOUND_HINT in hints and SERVICE_NEAR_SOUND_HINT not in matched:
                        import numpy as np
                        clip_left = max(0, row['start'] - .4)
                        channels = [decode_window(source, clip_left, row['end'] + 1.4, channel=channel)
                                    for channel in ('left', 'right')]
                        clip = max(channels, key=lambda audio: np.percentile(np.abs(audio), 99.5))
                        clip = np.pad(normalize_review_audio(clip, peak_target=.3, max_gain=10, amplify_only=True), (3200, 3200))
                        review['focused_passes'] = {}
                        for label, alternate in [('primary', False), ('alternate', True)]:
                            recognizer = ReviewRecognizer(config, alternate=alternate)
                            try:
                                items = recognizer.short_clip(clip)
                                evidence = {'model': recognizer.model_name, 'items': items, 'left': clip_left - .2}
                                review['focused_passes'][label] = evidence
                                pools[label].append(evidence)
                            finally:
                                recognizer.model = None
                        matched = confirmed_spellings(row, hints, pools, left)
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
        policy = _review_policy(reason, hints)
        review['signature'] = main.fingerprint([row['text'], row['start'], row['end'], spelling_hints(row, cache['segments']) if reason == 'contextual_spelling' else [], policy])
        row['source_review'] = review
        changes.append({'id': row['id'], **review})
        main.save_json(path, cache)
    return changes
