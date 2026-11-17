"""Review ambiguous short counts using audio; never complete a numeric sequence."""
from pathlib import Path
import copy
import re

from .counting import number, number_key, sessions
from .source_checks import key, artifact

VERSION = 1
DECISION_VERSION = 2


def archive_evidence(state: dict, path: Path) -> str | None:
    """Retain acoustic passes before a changed transcript replaces the review plan."""
    if not state.get('passes'):
        return None
    from . import cli
    backup=path.with_name('count-review-'+cli.fingerprint(state)+'.json')
    if not backup.exists():
        cli.save_json(backup,state)
    return backup.name


def signature(cache: dict, config: dict) -> str:
    from . import cli
    return cli.fingerprint([VERSION,cli.asr_settings(config),
            [(r['id'],r['start'],r['end'],r['text'],r.get('audio_review',{}).get('status')=='omitted') for r in cache['segments']]])


def plan(rows: list[dict], *, duration: float | None = None) -> list[dict]:
    from .subtitle_processing import sound_key
    valid=sorted((r for r in rows if r.get('audio_review',{}).get('status')!='omitted'),key=lambda r:r['start'])
    windows=[]
    for left,right in sessions(valid):
        right=min(right,duration if duration is not None else max(r['end'] for r in valid))
        local=[r for r in valid if left<=r['start']<=right]
        numeric=[r for r in local if number(r['text'],counting=True) is not None]
        clusters=[]
        for row in numeric:
            if (clusters and row['start']-clusters[-1][-1]['end']<=8
                    and row['end']-clusters[-1][0]['start']<=8
                    and number(row['text'],counting=True)>number(clusters[-1][-1]['text'],counting=True)):
                clusters[-1].append(row)
            else:clusters.append([row])
        selected=set()
        for group in clusters:
            if len(group)>1:
                selected.update(r['id'] for r in group)
                windows.append({'kind':'existing','ids':[r['id'] for r in group],
                       'left':max(left,group[0]['start']-3),'right':min(right,group[-1]['end']+2),
                       'focus':[group[0]['start']-1.5,group[-1]['end']+1.5]})
        for row in local:
            text=key(row['text'])
            if (row['id'] in selected or number(row['text'],counting=True) is not None
                    or len(text)>8 or row['end']-row['start']>8 or sound_key(row['text']) is not None
                    or not text or all(c in 'あいうえおぁぃぅぇぉんっはふへほ' for c in text)):
                continue
            ambiguous=bool(re.fullmatch(r'[いに][ぁ-ゖー]{1,5}',row['text'].strip('、。…!?？ ')))
            if row.get('avg_logprob',0)<-.8 or ambiguous:
                windows.append({'kind':'existing','ids':[row['id']], 'left':max(left,row['start']-3),
                                'right':min(right,row['end']+2),'focus':[row['start']-1.5,row['end']+1.5]})
        cursor=left
        for row in local+[{'start':right,'end':right}]:
            end=min(row['start'],right)
            if end-cursor>=4:
                start=cursor
                while start<end-1:
                    windows.append({'kind':'gap','ids':[], 'left':start,'right':min(end,start+8),
                                    'focus':[start,min(end,start+8)]})
                    start+=6
            cursor=max(cursor,row['end'])
    return sorted(windows,key=lambda w:(w['left'],w['right']))


def events(record: dict, window: dict, *, single: bool = True, soft: bool = False,
           devoiced: bool = False) -> list[dict]:
    result=[]
    for row in record.get('items',[]):
        if (artifact(row['text']) or row.get('avg_logprob',-2)<(-1.25 if soft else -.95)
                or row.get('no_speech_prob',1)>=(.3 if soft else .5)
                or row.get('compression_ratio',0)>2.4):continue
        tokens=re.findall(r'[0-9]+|[零一二三四五六七八九十]',row['text'])
        if single and len(set(tokens))>2:continue
        words=row.get('words',[])
        full=''.join(word['word'] for word in words)
        index=0
        while index<len(words):
            matches=[]
            for end in range(index,min(len(words),index+6)):
                text=''.join(w['word'] for w in words[index:end+1]).strip()
                value=number(text,counting=True)
                if value is None and devoiced and re.fullmatch(r'[こご][うおぉ]*',number_key(text)):
                    value=5
                if value is not None and 0<=value<=10:
                    matches.append((end,value))
                    if re.fullmatch(r'[0-9]+',number_key(words[index]['word'])):break
            if not matches:index+=1;continue
            end,value=matches[-1]
            group=words[index:end+1]
            offset=sum(len(word['word']) for word in words[:index])
            stop=offset+sum(len(word['word']) for word in group)
            before=full[offset-1:offset] if offset else ''
            after=full[stop:stop+1]
            if any(c and c.isalnum() and c not in 'んあいうえおぁぃぅぇぉはふ' for c in (before,after)):
                index=end+1;continue
            start=window['left']+group[0]['start'];finish=window['left']+group[-1]['end']
            lexical=[w for w in group if key(w['word'])]
            probability=sum(w.get('probability',0) for w in lexical)/len(lexical) if lexical else 0
            if (.12<=finish-start<=5 and probability>=(.12 if soft else .5)
                    and min(finish,window['focus'][1])-max(start,window['focus'][0])>=.12):
                result.append({'value':value,'start':start,'end':finish,'probability':probability})
            index=end+1
    return result


def unsupported_burst(original: list[dict], passes: dict, window: dict, speech: float) -> bool:
    """Reject a subsecond numeric burst only after both local decoders fail it."""
    if len(original)<3:return False
    left=min(r['start'] for r in original);right=max(r['end'] for r in original)
    if right-left>1.6 or speech>=.3 or speech/max(.1,right-left)>=.2:return False
    if (not passes['primary']['model'] or not passes['alternate']['model']
            or passes['primary']['model']==passes['alternate']['model']):return False
    for record in passes.values():
        for mode in ['guided','plain']:
            for event in events(record.get(mode,{}),window,single=mode!='plain'):
                if any(number(row['text'],counting=True)==event['value']
                       and min(row['end'],event['end'])-max(row['start'],event['start'])>.08 for row in original):
                    return False
    return True


def confirmed(passes: dict, window: dict, original: list[dict]) -> list[dict]:
    a,b=passes['primary'],passes['alternate']
    if not a['model'] or not b['model'] or a['model']==b['model']:return []
    result=[]
    burst=len(original)>1 and all(number(r['text'],counting=True) is not None for r in original)
    for soft in [False,True]:
        if soft and not original:continue
        primary=events(a['guided'],window,soft=soft,devoiced=burst)
        alternate=events(b['guided'],window,soft=soft,devoiced=burst)
        plain_a=events(a.get('plain',{}),window,single=False,soft=soft,devoiced=burst)
        plain_b=events(b.get('plain',{}),window,single=False,soft=soft,devoiced=burst)
        for x in primary:
            for y in alternate:
                if x['value']!=y['value'] or min(x['end'],y['end'])-max(x['start'],y['start'])<.12:continue
                support=lambda p:p['value']==x['value'] and min(p['end'],x['end'])-max(p['start'],x['start'])>.08
                existing=any(number(r['text'],counting=True)==x['value']
                             and min(r['end'],x['end'])-max(r['start'],x['start'])>.08 for r in original)
                if not existing and not any(support(p) for p in plain_a+plain_b):continue
                if soft:
                    if max(x['probability'],y['probability'])<.6:continue
                    if existing:
                        if not any(support(p) and p['probability']>=.6 for p in plain_a+plain_b):continue
                    elif (not burst or min(x['probability'],y['probability'])<.35
                          or not all(any(support(p) and p['probability']>=.35 for p in pool) for pool in [plain_a,plain_b])):
                        continue
                event={'value':x['value'],'start':min(x['start'],y['start']),'end':max(x['end'],y['end']),'soft':soft}
                if not any(e['value']==event['value'] and min(e['end'],event['end'])>max(e['start'],event['start']) for e in result):
                    result.append(event)
        if result:break
    return sorted(result,key=lambda e:e['start'])


def review_counts(source: Path, cache: dict, path: Path, config: dict) -> None:
    from . import cli
    from .audio_review import ReviewRecognizer,decode_window,speech_seconds
    from .short_speech import alternate_available
    from .transcript_refinement import _clear_translation
    if (cache.get('language')!='ja' or config.get('quality','high')!='high'
            or cli.asr_settings(config)['model']!='large-v2' or not alternate_available(config)):return
    current=signature(cache,config)
    state=cache.get('count_review',{})
    if state.get('complete') and state.get('signature')==current and state.get('decision_version')==DECISION_VERSION:return
    if state.get('signature')!=current:
        import av
        with av.open(str(source)) as container:
            duration=container.duration/av.time_base if container.duration else max(r['end'] for r in cache['segments'])
        windows=plan(cache['segments'],duration=duration)
        if not windows:return
        backup=path.with_name('task.before-count-review-v1.json')
        if not backup.exists():cli.save_json(backup,cache)
        history=list(state.get('previous_evidence',[]))
        archived=archive_evidence(state,path)
        if archived and archived not in history:history.append(archived)
        state={'version':VERSION,'signature':current,'windows':windows,'passes':{},'complete':False,
               'previous_evidence':history}
        cache['count_review']=state;cli.save_json(path,cache)
    windows=state['windows']
    for label,alternate in [('primary',False),('alternate',True)]:
        results=state['passes'].setdefault(label,{})
        recognizer=ReviewRecognizer(config,alternate=alternate)
        try:
            for i,w in enumerate(windows):
                if str(i) in results:continue
                print(f"Checking count {i+1}/{len(windows)} ({label}; {cli.console_time(w['left'])})...",flush=True)
                audio=decode_window(source,w['left'],w['right'])
                guided={'items':recognizer.counting(audio)}
                plain={'items':recognizer.counting(audio,hinted=False)} if events(guided,w) or len(w['ids'])>=2 else {'items':[]}
                results[str(i)]={'model':recognizer.model_name,'guided':guided,'plain':plain}
                cli.save_json(path,cache)
        finally:recognizer.model=None
    changes=[]
    for i,w in enumerate(windows):
        originals=[r for r in cache['segments'] if r['id'] in w['ids']]
        passes={label:state['passes'][label][str(i)] for label in ['primary','alternate']}
        values=confirmed(passes,w,originals)
        evidence={'window':copy.deepcopy(w),'passes':copy.deepcopy(passes),
                  'originals':[{k:r[k] for k in ['id','text','start','end']} for r in originals]}
        if not values and len(originals)>=3:
            audio=decode_window(source,min(r['start'] for r in originals),max(r['end'] for r in originals))
            speech=speech_seconds(audio,threshold=.5)
            if unsupported_burst(originals,passes,w,speech):
                for row in originals:
                    row['audio_review']={'version':4,'status':'omitted','reason':'unsupported_numeric_burst',
                        'note':'Rapid numeric output lacked speech coverage and independent acoustic confirmation.'}
                    row['count_review']={'version':VERSION,'status':'omitted'}
                continue
        for row in originals:
            row['count_review']={'version':VERSION,'status':'uncertain'}
        # Only replace a short existing cluster with one independently supported event.
        for event in values:
            others=[r for r in cache['segments'] if r['id'] not in w['ids'] and r.get('audio_review',{}).get('status')!='omitted']
            overlap=[r for r in others if min(event['end'],r['end'])-max(event['start'],r['start'])>.1]
            vocal=lambda r:bool(key(r['text'])) and all(c in 'あいうえおぁぃぅぇぉんっはふへほ' for c in key(r['text']))
            if overlap and (w['kind']=='gap' or not all(vocal(r) for r in overlap)):continue
            if w['kind']=='gap':
                if any(abs(r['start']-event['start'])<.5 for r in others):continue
                row={'id':max(r['id'] for r in cache['segments'])+1}
                cache['segments'].append(row)
            else:
                if len(values)!=1:continue
                row=originals[0]
                row.setdefault('original_asr',{k:row[k] for k in ['text','start','end']})
                for extra in originals[1:]+overlap:
                    extra['audio_review']={'version':4,'status':'omitted','reason':'numeric_cluster',
                                           'note':'A two-model acoustic count replaced this overlapping numeric cluster.'}
                    extra['count_review']={'version':VERSION,'status':'superseded'}
            row.update(text=str(event['value']),start=event['start'],end=event['end'],
                       words=[{'word':str(event['value']),'start':event['start'],'end':event['end']}],
                       count_review={'version':VERSION,'status':'recovered','value':event['value'],'soft':event['soft'],
                                     'evidence':copy.deepcopy(evidence)})
            _clear_translation(row);changes.append(row['id'])
    cache['segments'].sort(key=lambda r:(r['start'],r['end'],r['id']))
    state.update(complete=True,changed_ids=sorted(set(state.get('changed_ids',[])+changes)),
                 decision_version=DECISION_VERSION,signature=signature(cache,config))
    cli.save_json(path,cache)
