
from .storage import state_writer
"""Incremental coordinator usage; raw conversation text never enters analytics."""
import json
from pathlib import Path
import os
from .storage import Refused,atomic_json,digest,identifier,lock,now,read_json,state_home
from .telemetry import emit

KEYS={'input':'input_tokens','cached':'cached_input_tokens','output':'output_tokens','reasoning':'reasoning_output_tokens'}


@state_writer
def register(root,host,payload,run,project):
    if os.environ.get('OH_CHILD_ATTEMPT'):return
    name=payload.get('transcript_path');session=payload.get('session_id')
    if not name or not session:return  # Coverage remains explicitly unknown on this host.
    path=Path(name).expanduser().resolve()
    allowed=Path.home()/('.codex/sessions' if host=='codex' else '.claude/projects')
    if not path.is_relative_to(allowed) or not path.is_file():raise Refused('Unexpected host transcript path')
    key=digest({'host':host,'session':session});home=state_home()/'sources'
    with lock(home/(key+'.lock')):
        file=home/(key+'.json')
        if file.exists():
            old=read_json(file)
            if old['run']==run and old.get('end') is None:return
            if old.get('end') is None:old['end']=path.stat().st_size
            atomic_json(home/(key+'-'+old['attempt']+'.json'),old)
        offset=path.stat().st_size;totals=None;model=None;effort=None
        # One bounded tail read on registration establishes the pre-run baseline.
        with path.open('rb') as stream:
            stream.seek(max(0,offset-1024*1024))
            for line in stream:
                try:e=json.loads(line)
                except ValueError:continue
                p=e.get('payload',{})
                if e.get('type')=='turn_context':model=p.get('model');effort=p.get('effort')
                if p.get('type')=='token_count' and p.get('info'):totals=p['info'].get('total_token_usage')
        attempt=identifier()
        atomic_json(file,{'path':str(path),'host':host,'session':session,'run':run,'project':project,
            'offset':offset,'totals':totals,'attempt':attempt,'model':model,'effort':effort,'end':None})
        emit('attempt.started',project,run,attempt=attempt,role='orchestrator',phase='coordination',
             host=host,model=model,effort=effort)


@state_writer
def poll():
    home=state_home()/'sources'
    if not home.exists():return
    for file in home.glob('*.json'):
        with lock(file.with_suffix('.lock')):
            source=read_json(file);before=dict(source);path=Path(source['path'])
            if not path.exists():continue
            if path.stat().st_size<source['offset']:raise Refused('Coordinator transcript was truncated; usage requires reconciliation')
            maximum=min(path.stat().st_size,source['end'] if source['end'] is not None else path.stat().st_size,source['offset']+2*1024*1024)
            with path.open('rb') as stream:
                stream.seek(source['offset'])
                while stream.tell()<maximum:
                    at=stream.tell();line=stream.readline(maximum-at)
                    if source.get('skipping_record'):
                        source['offset']=stream.tell()
                        if line.endswith(b'\n'):source.pop('skipping_record',None)
                        continue
                    if not line.endswith(b'\n'):
                        if maximum-at>=2*1024*1024 and stream.tell()==maximum:
                            emit('collection.gap',source['project'],source['run'],reason='Oversized transcript record skipped; usage within it is unknown')
                            source['skipping_record']=True;source['offset']=stream.tell()
                        elif source['end'] is not None and stream.tell()>=source['end']:
                            emit('collection.gap',source['project'],source['run'],reason='Transcript ended inside a record; terminal usage is unknown')
                            source['offset']=source['end']
                        break
                    try:
                        event=json.loads(line)
                        if not isinstance(event,dict) or not isinstance(event.get('payload',{}),dict):raise ValueError('Invalid transcript record')
                    except ValueError:
                        emit('collection.gap',source['project'],source['run'],reason='Malformed transcript record skipped; usage within it is unknown')
                        source['offset']=stream.tell();continue
                    p=event.get('payload',{});usage=None
                    if event.get('type')=='turn_context':
                        source['model']=p.get('model');source['effort']=p.get('effort')
                    if source['host']=='codex' and p.get('type')=='token_count' and p.get('info'):
                        info=p['info'];total=info.get('total_token_usage') or {};old=source.get('totals')
                        if total and total!=old:
                            usage={key:(total.get(raw)-old.get(raw) if old and type(total.get(raw)) is int and type(old.get(raw)) is int and total[raw]>=old[raw] else None) for key,raw in KEYS.items()}
                            if old is None:usage={key:info.get('last_token_usage',{}).get(raw) for key,raw in KEYS.items()}
                            source['totals']=total
                            usage['context_tokens']=info.get('last_token_usage',{}).get('input_tokens')
                    elif source['host']=='claude' and event.get('type')=='assistant' and not event.get('isSidechain'):
                        message=event.get('message',{});u=message.get('usage') or {}
                        if u:
                            parts=[u.get('input_tokens'),u.get('cache_read_input_tokens'),u.get('cache_creation_input_tokens')]
                            usage={'input':sum(parts) if all(type(x) is int for x in parts) else None,
                              'cached':u.get('cache_read_input_tokens'),'output':u.get('output_tokens'),'reasoning':None}
                            source['model']=message.get('model');at=message.get('id',at)
                    if usage:
                        emit('usage',source['project'],source['run'],attempt=source['attempt'],
                             response_id=digest({'session':source['session'],'response':at}),
                             source='coordinator.'+source['host'],model=source.get('model'),**usage)
                    source['offset']=stream.tell()
            if source.get('end') is not None and source['offset']>=source['end']:
                archive=home/'completed';archive.mkdir(exist_ok=True)
                atomic_json(archive/file.name,source);file.unlink()
            elif source!=before:atomic_json(file,source)


@state_writer
def end_run(run):
    """Capture the byte boundary synchronously at the authority transition, never on idle."""
    home=state_home()/'sources'
    for file in home.glob('*.json'):
        with lock(file.with_suffix('.lock')):
            source=read_json(file)
            if source['run']!=run or source.get('end') is not None:continue
            path=Path(source['path'])
            source['end']=path.stat().st_size if path.exists() else source['offset']
            atomic_json(file,source)
