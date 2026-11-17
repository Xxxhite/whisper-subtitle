"""Conservative source-conditioned checks for clearly changed translation relationships."""
import re


def meaning_errors(source: str, target: str) -> list[str]:
    errors = []
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
    return errors
