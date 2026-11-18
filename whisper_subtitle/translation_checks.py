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


def climax_context(text: str) -> bool:
    return intimate_context(text) or ('エッチ' in text and bool(re.search(r'我慢|挿入|中に[出来]|腰を', text)))


def progressive_action_clause(source: str) -> bool:
    return bool(re.fullmatch(r'(?:入れ|進め|動かし|深め)てい(?:って|きます|こう)[、。…\s]*', source.strip()))


def climax_with_partner(source: str, context: str) -> bool:
    return (climax_context(source + '\n' + context)
            and bool(re.search(r'一緒に行こう|行って.{0,12}一緒に', source))
            and not re.search(r'学校|会社|病院|公園|駅|旅行|作業|計画|試験|仕事|上手く|うまく', source))


def normalize_contextual_actions(source: str, target: str, context: str) -> str:
    """Clarify an isolated literal movement phrase when the source context fixes its meaning."""
    if climax_with_partner(source, context):
        motion = r'一起[去走]' if re.search(r'行って.{0,12}一緒に', source) else r'一起走'
        target = re.sub(motion + r'(?=(?:吧|啦|吗|嘛|了)?(?:[。！？?？，、.…\s]|$))', '一起高潮', target)
        if re.search(r'行って.{0,12}一緒に', source):
            target = re.sub(r'[去走](?=(?:吧|啦|吗|嘛|了)?[，、,.…\s]+(?:和|跟|与)[我你]一起)', '高潮', target)
    return target


def explicit_question(source: str) -> bool:
    return bool(re.search(r'[ぁ-ゖァ-ヺ]', source)
                and re.fullmatch(r'[^。！？!?]{2,36}[?？]', source.strip()))


def physical_fit(source: str) -> bool:
    return bool(re.search(r'(?:舌|耳).{0,24}(?:はま|合|フィット).{0,24}相性', source))


def relaxed_expression(source: str) -> bool:
    return bool(re.search(r'(?:顔|表情).{0,10}(?:とろとろ|トロトロ)', source))


def alternating_tongue_motion(source: str) -> bool:
    return bool(re.search(r'舌.{0,10}(?:出し入れ|出たり入ったり)', source))


def favorite_ear_action(source: str) -> bool:
    return bool(re.search(r'(?:君|あなた|お客様|お兄さん)の(?:一番)?大?好きな耳(?:舐め|なめ|かき|掻き)', source))


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
    if re.search(r'行[くこきっ]|い[くこきっけ]',row['text']) and climax_context(history):
        terms=sorted(set(re.findall(r'おちんぽ|ちんちん|おまんこ|精液|射精|エッチ|気持ち|舐|我慢|興奮|挿入|中に[出来]|腰を',history)))
        before+='\n<topic_terms>'+','.join(terms)+'</topic_terms>'
    return before


def meaning_errors(source: str, target: str, context: str = '') -> list[str]:
    errors = []
    if progressive_action_clause(source) and re.search(r'不只是|不仅|不光|除了', target):
        errors.append('progressive_action_changed_to_added_clause')
    if favorite_ear_action(source) and re.search(r'喜欢的耳朵(?!按摩|清洁|护理)', target):
        errors.append('favorite_action_changed_to_body_part')
    if (explicit_question(source) and re.search(r'[一-鿿]', target)
            and not re.search(r'[?？]|[吗么嗎麼][。.…！!\s]*$', target)):
        errors.append('explicit_question_lost')
    if physical_fit(source) and re.search(r'天造地设|天生一对|命中注定|绝配的一对', target):
        errors.append('physical_fit_expanded_to_relationship')
    if relaxed_expression(source) and re.search(r'软绵绵|软乎乎|黏糊糊|粘糊糊', target):
        errors.append('facial_expression_translated_as_texture')
    if alternating_tongue_motion(source) and not re.search(r'进进出出|进出|往返|来回|反复|伸缩|进退', target):
        inward = bool(re.search(r'伸进|伸入|深入', target))
        outward = bool(re.search(r'伸出|抽出|收回|退出|缩回', target))
        if inward != outward:
            errors.append('alternating_motion_lost_direction')
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
    if (climax_context(source+'\n'+context)
            and re.search(r'(?:一緒に行こう|行って.{0,12}一緒に|いきそう|行きそう|いけそう)',source)
            and not re.search(r'学校|会社|病院|公園|駅|旅行|作業|計画|試験|仕事|上手く|うまく',source)
            and re.search(r'一起去|一起走|顺利进行|喘不过气|[去走](?:吧|啦)?[，、,.…\s]+(?:和|跟|与)[我你]一起',target)):
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
