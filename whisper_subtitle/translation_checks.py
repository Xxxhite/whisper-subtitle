"""Conservative source-conditioned checks for clearly changed translation relationships."""
import re
import unicodedata
from difflib import SequenceMatcher


def action_sound(source: str) -> bool:
    text=unicodedata.normalize('NFKC',source)
    text=''.join(chr(ord(c)-0x60) if 'ァ'<=c<='ヶ' else c for c in text)
    text=''.join(c for c in text if c.isalnum() and c!='ー')
    return bool(re.fullmatch(r'(?:ぎゅ|ちゅ)(?:う|っ)*',text))


def intimate_context(text: str) -> bool:
    return bool(re.search(r'おちん|ちんちん|ちんぽ|おまんこ|精液|射精',text)
                and re.search(r'エッチ|気持ち|舐|なめ|我慢|興奮',text))


def normalize_participants(source: str, target: str) -> str:
    """Keep an omitted receiver omitted instead of inventing a participant."""
    if (re.search(r'耳.{0,14}(?:なぞられ|舐められ|なめられ|触れられ)',source)
            and not re.search(r'私|わたし|僕|ぼく|俺|彼|彼女|君|あなた|お客様|お兄さん',source)):
        target=re.sub(r'([让令使])[我他她](?:的)?(?=身子|身体|浑身)',r'\1',target)
    return target


def context_for(row: dict, rows: list[dict]) -> str:
    from .audio_review import preceding_context
    before=preceding_context(row,rows)
    following=[r['text'] for r in rows if row['end']<=r['start']<=row['end']+10 and r['id']!=row['id']
               and r.get('audio_review',{}).get('status')!='omitted'][:1]
    if following:before+='\n<following_source>\n'+following[0][:180]+'\n</following_source>'
    history='\n'.join(r['text'] for r in rows if row['start']-480<=r['end']<=row['start']
                      and r.get('audio_review',{}).get('status')!='omitted')
    if re.search(r'行[くこきっ]|い[くこきっ]',row['text']) and intimate_context(history):
        terms=sorted(set(re.findall(r'おちんぽ|ちんちん|おまんこ|精液|射精|エッチ|気持ち|舐|我慢|興奮',history)))
        before+='\n<topic_terms>'+','.join(terms)+'</topic_terms>'
    return before


def meaning_errors(source: str, target: str, context: str = '') -> list[str]:
    errors = []
    if normalize_participants(source,target)!=target:
        errors.append('unsupported_passive_participant')
    if action_sound(source) and re.search(r'我|[你您]|他|她|它',target):
        errors.append('unsupported_action_participants')
    fragment=re.search(r'([ぁ-ゖァ-ヺー]+ーっと)[、。.…\s]*$',source)
    if fragment:
        from .word_boundaries import tokenizer
        from .source_checks import reading
        person=lambda text:any(t.part_of_speech.startswith('名詞,固有名詞,人名') for t in tokenizer().tokenize(text))
        sound=lambda text:reading(text).replace('っ','')
        invented=any(person(match[0]) and SequenceMatcher(None,sound(fragment[1]),sound(match[0]),autojunk=False).ratio()>=.75
                     for match in re.finditer(r'[一-鿿]{2,4}',target))
        if invented and not person(source):errors.append('adverb_changed_to_person_name')
    service_question=bool(re.search(r'(?:舐め|なめ)て[ほ欲]しい(?:ですか)?[?？]',source))
    if (service_question
            and re.search(r'(?:想|想要)(?:再|也|多|好好|继续|舔舔|舔一舔)*舔',target)
            and not re.search(r'让|叫|请|我|人家|对方',target)):
        errors.append('desired_service_changed_to_listener_action')
    if (service_question
            and not re.search(r'(?:君|あなた|お兄さん|お客様)に',source)
            and re.search(r'(?:想|想要)(?:让|叫|请)[你您]',target)):
        errors.append('desired_service_changed_to_provider')
    if (re.search(r'耳.{0,14}(?:なぞられ|舐められ|なめられ|触れられ)',source)
            and not re.search(r'彼|彼女|あの人|その人|友達',source+'\n'+context)
            and re.search(r'让[他她]|[他她](?:的身子|变得|一颤)',target)):
        errors.append('listener_service_changed_to_third_person')
    if (intimate_context(source+'\n'+context) and re.search(r'(?:一緒に行こう|いきそう|行きそう)',source)
            and not re.search(r'学校|会社|病院|公園|駅|旅行|作業|計画|試験|仕事|上手く|うまく',source)
            and re.search(r'一起去|顺利进行',target)):
        errors.append('contextual_action_changed_to_literal_motion')
    if re.search(r'(?:お客様|あなた|君)のような', source) and re.search(r'像我(?:一样|这样|那么)', target):
        errors.append('listener_simile_changed_to_speaker')
    if '私のような' in source and re.search(r'像[你您](?:一样|这样|那么)', target):
        errors.append('speaker_simile_changed_to_listener')
    if '腰を上げ' in source and not re.search(r'立[つっちて]', source) and re.search(r'站起|站立|起身', target):
        errors.append('local_motion_changed_to_standing')
    listener_ear = re.search(r'(?:お客様|あなた|君|お兄さん)の(?:お)?耳', source)
    service_action = re.search(r'あげ|差し上げ|しちゃいましょう|なめられて|舐められて', source)
    if ('耳' in source and (listener_ear or service_action)
            and not re.search(r'(?:私|わたし|僕|ぼく|俺)の(?:右|左|両|お)?耳', source)
            and re.search(r'我(?:的)?耳(?:边|旁|畔|垂|朵|道|郭|孔|内)', target)):
        errors.append('unsupported_speaker_ear_ownership')
    if (re.search(r'(?:として|ので|ですが)[、，…。\sー]*$', source) and not re.search(r'[?？]', source)
            and re.search(r'[?？]', target)):
        errors.append('declarative_clause_changed_to_question')
    if '我慢' in source and '被忍耐' in target:
        errors.append('literal_ungrammatical_causative')
    if 'いやらしい' in source and re.search(r'息|声', source) and re.search(r'讨厌|恶心', target):
        errors.append('sensual_tone_changed_to_disgust')
    if (re.search(r'てもらいたい(?:ですか|んですか|の)', source)
            and not re.search(r'(?:あなた|君|お兄さん)に[^。]*てもらいたい', source)
            and re.search(r'(?:想|希望|要)(?:让|叫|请)[你您]', target)):
        errors.append('beneficiary_changed_to_actor')
    if (re.search(r'してあげたら', source)
            and not re.search(r'(?:あなた|君|お兄さん)が[^。]*してあげたら', source)
            and re.search(r'(?:真的|要是|如果)[^，。！？?]{0,10}让[你您](?!享受|体验|舒服|感受|得到|获得|满意|开心|快乐|高兴)', target)):
        errors.append('giver_changed_to_recipient')
    if (re.search(r'(?:音|声)[^。]{0,12}(?:だけで|を頼りに)', source) and '想像' in source
            and not re.search(r'(?:音|声)を想像', source)
            and re.search(r'想象[^，。！？?]{0,24}(?:声音|声)', target)):
        errors.append('imagined_object_changed_to_sound')
    return errors
