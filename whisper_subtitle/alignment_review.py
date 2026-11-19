"""Repair locally collapsed word alignments with independent timed hypotheses."""
from pathlib import Path
import copy
import re

from .source_checks import key,reading,artifact

VERSION=1
POLICY='complete-word-tails-v5'


def overlapping_words(words: list[dict]) -> bool:
    return any(a['end'] - b['start'] > .05 for a, b in zip(words, words[1:]))


def supported_clause_splice(row: dict, hypotheses: list[dict]) -> list[dict] | None:
    """Replace a complete final clause when both models agree at the same boundary."""
    primary, alternate = hypotheses
    if (reading(primary['text']) != reading(alternate['text'])
            or overlapping_words(primary['words']) or overlapping_words(alternate['words'])):
        return None
    starts = [h['words'][0]['start'] for h in hypotheses]
    ends = [h['words'][-1]['end'] for h in hypotheses]
    if max(starts) - min(starts) > .5 or max(ends) - min(ends) > .8:
        return None
    for index, word in enumerate(row['words'][:-1], 1):
        if not word['word'].rstrip().endswith(('。', '?', '？', '!', '！')):
            continue
        old_tail = reading(''.join(w['word'] for w in row['words'][index:]))
        if (min(starts) >= word['end'] and max(starts) <= row['words'][index]['start'] + 1
                and len(old_tail) >= 4 and reading(primary['text']).startswith(old_tail[:4])):
            prefix = row['words'][:index]
            if not overlapping_words(prefix):
                return prefix + copy.deepcopy(primary['words'])
    return None


def compact(text: str) -> str:
    return ''.join(c for c in text if c.isalnum() or c=='ー')


def usable(items: list[dict], left: float) -> dict | None:
    words=[]
    for item in items:
        if (artifact(item['text']) or item.get('avg_logprob',-2)<-.9
                or item.get('no_speech_prob',1)>=.4 or item.get('compression_ratio',0)>2.4):continue
        words.extend({**w,'start':w['start']+left,'end':w['end']+left} for w in item.get('words',[]))
    if not words:return None
    return {'words':words,'text':''.join(w['word'] for w in words)}


def tail_index(row: dict) -> int | None:
    words=row.get('words',[])
    if not words or compact(''.join(w['word'] for w in words))!=compact(row['text']):return None
    collapsed=[]
    for i in range(len(words)-1,-1,-1):
        w=words[i]
        if not key(w['word']):continue
        if w['end']-w['start']>.041:break
        collapsed.append(i)
    collapsed.reverse()
    if not collapsed:return None
    start=collapsed[0]
    suffix=[w for w in words[start:] if key(w['word'])]
    total=sum(len(key(w['word'])) for w in suffix)
    bad=sum(len(key(w['word'])) for w in suffix if w['end']-w['start']<=.04)
    if (len(collapsed)<3 or bad/max(1,total)<.6) and not (
            row.get('avg_logprob',0)<-1 and words[-1]['end']-words[-1]['start']<=.04 and total>=2):return None
    # Keep a kana word intact when only its last decoder pieces collapsed.
    while start and re.fullmatch(r'[ぁ-ゖァ-ヺー]+',words[start-1]['word']):
        start-=1
    from .word_boundaries import safe_offsets
    boundaries=safe_offsets(row['text'],'ja')
    while start and sum(len(w['word']) for w in words[:start]) not in boundaries:
        start-=1
    return start


def plan(row: dict, rows: list[dict]) -> dict | None:
    words=row.get('words',[])
    if not words:return None
    index=tail_index(row)
    prefix=(len(compact(row['text']))>=8 and words[0].get('probability',1)<.25
            and words[0]['end']-words[0]['start']<=.2 and len(compact(words[0]['word']))<=3)
    if index is None and not prefix:return None
    start=row['start'] if prefix else max(row['start'],words[index]['start']-2)
    return {'id':row['id'],'left':max(0,start-1.2),'right':row['end']+2,
            'tail_index':index,'prefix':prefix}


def supported_prefix(row: dict, hypotheses: list[dict], rows: list[dict]) -> dict | None:
    old=row['words'][0]['word'];anchor=compact(row['text'])[len(compact(old)):][:4]
    if len(anchor)<4:return None
    proposals=[]
    for h in hypotheses:
        text=compact(h['text']);position=text.find(anchor)
        if not 1<=position<=8:return None
        value=text[:position]
        selected=[];cursor=0
        for w in h['words']:
            end=cursor+len(compact(w['word']))
            if cursor<position and end>0:selected.append(w)
            cursor=end
        lexical=[w for w in selected if key(w['word'])]
        probability=sum(w.get('probability',0) for w in lexical)/len(lexical) if lexical else 0
        if not lexical or probability<.6:return None
        proposals.append((value,selected[0]['start'],selected[-1]['end'],probability))
    a,b=proposals
    previous=max((max((w['end'] for w in r.get('words',[]) if key(w['word'])),default=r['end'])
                  for r in rows if r['id']!=row['id'] and r['end']<=row['start']),default=0)
    if (a[0]!=b[0] or a[0]==compact(old) or min(a[2],b[2])-max(a[1],b[1])<.12
            or max(a[1],b[1])<previous or min(a[1],b[1])<row['start']-1.5):return None
    return {'old':old,'new':a[0],'start':max(a[1],b[1]),'end':max(a[2],b[2])}


def supported_tail(row: dict,index: int,hypotheses: list[dict]) -> tuple[dict,dict] | None:
    start=row['words'][index]['start']-.2
    result=[]
    for h in hypotheses:
        words=[w for w in h['words'] if min(w['end'],row['end']+2)-max(w['start'],start)>=min(.1,max(.02,(w['end']-w['start'])/2))]
        lexical=[w for w in words if key(w['word'])]
        if (not lexical or not 2<=len(key(''.join(w['word'] for w in words)))<=24
                or sum(w.get('probability',0) for w in lexical)/len(lexical)<.6
                or sum(w['end']-w['start']<=.04 for w in lexical)/len(lexical)>.4):return None
        result.append({'text':''.join(w['word'] for w in words).strip(),'words':words})
    a,b=result
    if reading(a['text'])!=reading(b['text']):return None
    if min(a['words'][-1]['end'],b['words'][-1]['end'])-max(a['words'][0]['start'],b['words'][0]['start'])<.12:return None
    return a,b


def borrowed_partial(row: dict,index: int,hypotheses: list[dict],rows: list[dict]) -> bool:
    from .word_boundaries import safe_offsets
    tail=''.join(w['word'] for w in row['words'][index:])
    for following in rows:
        if following['id']==row['id'] or not 0<=following['start']-row['end']<=.35:continue
        boundaries=sorted(safe_offsets(following['text'],'ja'))
        wanted=next((following['text'][:end] for end in boundaries if len(key(following['text'][:end]))>=2),'')
        if not wanted or len(wanted)>8:continue
        source_sound,target_sound=reading(tail),reading(wanted)
        if source_sound==target_sound or len(source_sound)>len(target_sound):continue
        common=0
        for a,b in zip(source_sound,target_sound):
            if a!=b:break
            common+=1
        if common<2:continue
        matches=[]
        for h in hypotheses:
            found=[]
            for begin in range(len(h['words'])):
                for end in range(begin,min(len(h['words']),begin+7)):
                    words=h['words'][begin:end+1]
                    if reading(''.join(w['word'] for w in words))!=target_sound:continue
                    if min(words[-1]['end'],following['end'])-max(words[0]['start'],following['start'])<.12:continue
                    lexical=[w for w in words if key(w['word'])]
                    if not lexical or sum(w.get('probability',0) for w in lexical)/len(lexical)<.6:continue
                    found.append((words[0]['start'],words[-1]['end']))
            matches.append(found)
        if all(matches) and any(min(a[1],b[1])-max(a[0],b[0])>=.12 for a in matches[0] for b in matches[1]):return True
    return False


def review_alignment(source: Path,cache: dict,path: Path,config: dict) -> None:
    from . import cli
    from .audio_review import ReviewRecognizer,decode_window,speech_seconds
    from .short_speech import alternate_available,dialogue_key
    from .transcript_refinement import _clear_translation
    if (cache.get('language')!='ja' or config.get('quality','high')!='high'
            or cli.asr_settings(config)['model']!='large-v2' or not alternate_available(config)):return
    selected=[]
    for row in cache['segments']:
        if row.get('audio_review',{}).get('status')=='omitted':continue
        old = row.get('alignment_review', {})
        if (old.get('status') == 'recovered' and old.get('borrowed_word_removed') is False
                and not old.get('splice_rechecked') and overlapping_words(row.get('words', []))):
            selected.append((row, None, None))
            continue
        window=plan(row,cache['segments'])
        if not window:continue
        signature=cli.fingerprint([VERSION,POLICY,row['text'],row['start'],row['end'],row['words']])
        if row.get('alignment_review',{}).get('signature')==signature:continue
        selected.append((row,window,signature))
    if not selected:return
    backup=path.with_name('task.before-alignment-splice-recheck.json' if any(w is None for _, w, _ in selected)
                          else 'task.before-alignment-review-v1.json')
    if not backup.exists():cli.save_json(backup,cache)
    for row,w,signature in selected:
        if w is None:
            old = row['alignment_review']
            passes = list(old['passes'].values())
            hypotheses = [usable(p['items'], p['left']) for p in passes]
            replacement = (supported_clause_splice(row, hypotheses) if len(passes) == 2
                           and passes[0]['model'] != passes[1]['model'] and all(hypotheses) else None)
            if replacement:
                row.update(words=replacement, text=''.join(x['word'] for x in replacement).strip(),
                           end=replacement[-1]['end'])
                _clear_translation(row)
            else:
                old['status'] = 'uncertain'
            old['splice_rechecked'] = True
            old['signature'] = cli.fingerprint([VERSION,POLICY,row['text'],row['start'],row['end'],row['words']])
            cli.save_json(path,cache)
            continue
        print(f"Checking word alignment #{row['id']} ({cli.console_time(row['start'])})...",flush=True)
        details={'version':VERSION,'signature':signature,'status':'uncertain','passes':{}}
        old=row.get('alignment_review',{})
        old_signatures={cli.fingerprint([VERSION,policy,row['text'],row['start'],row['end'],row['words']])
                        for policy in ['kana-boundaries-v2','collapsed-suffix-v3','partial-boundaries-v4',POLICY]}
        if old.get('signature') in old_signatures and set(old.get('passes',{}))=={'primary','alternate'}:
            details['passes']=copy.deepcopy(old['passes']);details['reused_evidence']=True
        else:
            audio=decode_window(source,w['left'],w['right'])
            for label,alternate in [('primary',False),('alternate',True)]:
                model=ReviewRecognizer(config,alternate=alternate)
                try:
                    items=model.timed(audio,'ja')
                    details['passes'][label]={'model':model.model_name,'items':items,'left':w['left']}
                finally:model.model=None
        h=[usable(details['passes'][label]['items'],details['passes'][label]['left']) for label in ['primary','alternate']]
        distinct=details['passes']['primary']['model']!=details['passes']['alternate']['model']
        if distinct and all(h):
            prefix=supported_prefix(row,h,cache['segments']) if w['prefix'] else None
            if prefix:
                for preceding in cache['segments']:
                    if preceding['id']==row['id'] or not preceding['start']<prefix['start']<preceding['end']<=row['start']:continue
                    last=max((w['end'] for w in preceding.get('words',[]) if key(w['word'])),default=preceding['end'])
                    if last<=prefix['start']:
                        preceding.setdefault('original_asr',{k:preceding[k] for k in ['text','start','end']})
                        preceding['end']=prefix['start']
                row.setdefault('original_asr',{k:row[k] for k in ['text','start','end']})
                row['text']=prefix['new']+row['text'][len(prefix['old']):]
                row['words'][0]={**row['words'][0],'word':prefix['new'],'start':prefix['start'],'end':prefix['end']}
                row['start']=min(row['start'],prefix['start']);_clear_translation(row)
                details.update(status='recovered',prefix=prefix)
            if w['tail_index'] is not None:
                index=w['tail_index'];replacement=supported_tail(row,index,h)
                if replacement:
                    candidate=replacement[0];text=candidate['text'];start=candidate['words'][0]['start'];end=candidate['words'][-1]['end']
                    following=[r for r in cache['segments'] if r['id']!=row['id'] and r['start']>=row['end']-.05 and r.get('audio_review',{}).get('status')!='omitted']
                    borrowed=any(reading(compact(r['text'])[:len(compact(text))])==reading(text)
                                 and min(r['end'],end)-max(r['start'],start)>.12 for r in following)
                    previous=row['words'][:index]
                    same_word=(reading(''.join(w['word'] for w in row['words'][index:]))==reading(text)
                               or borrowed_partial(row,index,h,cache['segments']))
                    if previous and (borrowed and same_word or not borrowed and not any(min(r['end'],end)-max(r['start'],start)>.12 for r in following)):
                        joined = previous if borrowed else previous + copy.deepcopy(candidate['words'])
                        if overlapping_words(joined):
                            joined = supported_clause_splice(row, h)
                        if joined and not any(min(r['end'], joined[-1]['end']) - max(r['start'], joined[0]['start']) > .12 for r in following):
                            row.setdefault('original_asr',{k:row[k] for k in ['text','start','end']})
                            row['words']=joined
                            row['text']=''.join(x['word'] for x in row['words']).strip()
                            row['end']=row['words'][-1]['end'];_clear_translation(row)
                            details.update(status='recovered',borrowed_word_removed=borrowed)
                elif index and borrowed_partial(row,index,h,cache['segments']):
                    row.setdefault('original_asr',{k:row[k] for k in ['text','start','end']})
                    row['words']=row['words'][:index];row['text']=''.join(x['word'] for x in row['words']).strip()
                    row['end']=row['words'][-1]['end'];_clear_translation(row)
                    details.update(status='recovered',borrowed_word_removed=True)
        # A collapsed repetition of recent dialogue needs evidence in its own interval.
        end_of=lambda r:max((w['end'] for w in r.get('words',[]) if key(w['word'])),default=r['end'])
        previous=[r for r in cache['segments'] if r['id']!=row['id'] and 0<row['start']-end_of(r)<30]
        duplicate_key=lambda text:dialogue_key(text).lstrip('ん')
        from .sakura import rhythmic_input
        duplicate=(not rhythmic_input(row['text']) and len(duplicate_key(row['text']))>=4
                   and any(duplicate_key(row['text'])==duplicate_key(r['text']) for r in previous))
        if duplicate and w['tail_index'] is not None and details['status']=='uncertain' and distinct:
            from .source_review import focused
            evidence=[focused(p['items'],row,p['left']) for p in details['passes'].values()]
            confirmed=all(x and duplicate_key(row['text']) in duplicate_key(x['text']) for x in evidence)
            speech=speech_seconds(decode_window(source,row['start'],row['end']),threshold=.5)
            details['speech_seconds']=round(speech,3)
            if not confirmed and speech<.5 and speech/max(.1,row['end']-row['start'])<.25:
                row['audio_review']={'version':4,'status':'omitted','reason':'collapsed_duplicate',
                      'note':'Collapsed duplicate had no independent confirmation in its own audio interval.'}
                details['status']='omitted'
        details['signature']=cli.fingerprint([VERSION,POLICY,row['text'],row['start'],row['end'],row.get('words',[])])
        row['alignment_review']=details;cli.save_json(path,cache)
