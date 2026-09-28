from .storage import checkout_file

from .storage import state_writer
"""A hook payload is a locator. Only a native user transcript record grants work."""
import json
import os
from pathlib import Path
import re
from .storage import Refused,atomic_json,digest,git,lock,now,read_json,state_home


def pending_file(root):return checkout_file(root, 'oh-pending-human.json')


def refusal_file(root):return checkout_file(root, 'oh-last-refusal.json')


def refused_last(root):
    """After a typed command was refused, the next plain run says so once instead of acting on an older run."""
    path=refusal_file(root)
    if pending_file(root).exists() or not path.exists():return
    message=read_json(path)['refused'];path.unlink()
    raise Refused('Your last OH command was refused: '+message)


def stage(root,host,payload):
    if os.environ.get('OH_CHILD_ATTEMPT'):raise Refused('Delegated agent prompts cannot grant authority')
    from .workflow import human_event
    event=human_event(payload,host)  # shape only; no grant is issued here
    if not re.fullmatch(r'[a-zA-Z0-9_-]+',event['session']):raise Refused('Invalid native session identifier')
    locator={'host':host,'payload':payload,'event':event}
    path=pending_file(root)
    with lock(path.with_suffix('.lock')):
        if path.exists() and {k:v for k,v in read_json(path).items() if k!='staged_at'}!=locator:
            raise Refused('A prior human choice is pending verification; resolve it before another choice')
        if not path.exists():atomic_json(path,locator|{'staged_at':now()})
    return {'pending':True,'message':'Run OH to verify and apply this native human choice'}


def owner_transcript(human):
    """The saved transcript of the Claude conversation that owns the run."""
    allowed=(Path.home()/'.claude/projects').resolve()
    if human.get('transcript_path'):paths=[Path(human['transcript_path']).expanduser().resolve()]
    else:paths=[p.resolve() for p in allowed.glob('*/'+human['session']+'.jsonl')] if re.fullmatch(r'[a-zA-Z0-9_-]+',human['session']) else []
    if len(paths)!=1 or not paths[0].is_relative_to(allowed) or not paths[0].is_file():return None
    return paths[0]


def latest_click(path,session,root,question):
    """The person's latest answer to exactly this menu in the owner's transcript: the model's question-tool call
    (without answers of its own) and the answer the host returned for it. None when there is no such click."""
    asked={};answered={}
    with path.open('rb') as stream:
        stream.seek(max(0,path.stat().st_size-8*1024*1024))
        for line in stream:
            try:x=json.loads(line)
            except ValueError:continue
            if not isinstance(x,dict) or x.get('isSidechain') or x.get('sessionId')!=session:continue
            if x.get('promptSource')=='sdk' or x.get('turnOrigin')=='sdk' or x.get('entrypoint')=='sdk-cli':continue
            if not Path(x.get('cwd','')).resolve().is_relative_to(Path(root).resolve()):continue  # the agent may cd into subfolders
            content=(x.get('message') or {}).get('content')
            if not isinstance(content,list):continue
            for c in content:
                if not isinstance(c,dict):continue
                if x.get('type')=='assistant' and c.get('type')=='tool_use' and c.get('name')=='AskUserQuestion':
                    request=c.get('input');raw=(x.get('wireToolInputs') or {}).get(c.get('id'),request)
                    if request=={'questions':[question]} and raw==request:
                        asked[c.get('id')]=digest(x)
                elif x.get('type')=='user' and c.get('type')=='tool_result' and c.get('tool_use_id') in asked and not c.get('is_error'):
                    result=x.get('toolUseResult');answers=result.get('answers') if isinstance(result,dict) else None
                    answer=answers.get(question['question']) if isinstance(answers,dict) else None
                    if isinstance(answer,str):
                        use=c['tool_use_id'];answered.pop(use,None)
                        answered[use]={'host':'claude','session':session,'turn':use,'prompt':answer,'via':'question',
                            'at':x.get('timestamp'),'record_hashes':sorted({asked[use],digest(x)}),'transcript_path':str(path)}
    return list(answered.values())[-1] if answered else None


def newer(at,than):
    """Whether transcript time `at` is later than OH time `than`; unknown times never are."""
    from datetime import datetime
    try:return datetime.fromisoformat(str(at).replace('Z','+00:00'))>datetime.fromisoformat(str(than).replace('Z','+00:00'))
    except ValueError:return False


@state_writer
def click(root):
    """Apply the person's click on the menu OH is waiting on, read from the owner's own Claude transcript. Nothing
    is staged, so no other conversation, forged hook call or older click can stand in for it."""
    from .workflow import active_file
    if not active_file(root).exists():return None
    with lock(pending_file(root).with_suffix('.lock')):return _click(root)


def candidate(root):
    """The person's latest click on the menu this run waits on, with that menu, or None. Nothing is applied."""
    from .gates import ask,describe
    from .workflow import load_run
    journal,state=load_run(root)
    gate=describe(journal,state) if state['host']=='claude' else None
    path=owner_transcript(state['human']) if gate else None
    found=latest_click(path,state['human']['session'],root,ask(gate)['questions'][0]) if path else None
    if not found or used_file(root,found).exists():return None
    return gate,found,path


def used_file(root,event):
    from .storage import project
    return state_home()/'projects'/project(root)['id']/'human-events'/(digest({k:event[k] for k in ('host','session','turn','prompt')})+'.json')


def _click(root,chosen=None):
    from .gates import apply,pick
    chosen=chosen or candidate(root)
    if not chosen:return None
    gate,found,_=chosen;used=used_file(root,found)
    try:result=apply(root,found|{'prompt':pick(gate,found['prompt'])},gate['id'])
    except Refused as exc:
        # Said once; the same click is then set aside, so it never blocks the next one.
        atomic_json(used,{'source':found,'refused':str(exc)},immutable=True)
        raise
    atomic_json(used,{'source':found,'result':result},immutable=True)
    return result


def saved_after(path,session,moment):
    """Whether the owner's transcript already holds a record of this session saved after `moment`: a typed turn
    staged at `moment` and still missing then can no longer verify."""
    with path.open('rb') as stream:
        stream.seek(max(0,path.stat().st_size-1024*1024))
        for line in stream:
            try:x=json.loads(line)
            except ValueError:continue
            if isinstance(x,dict) and x.get('sessionId')==session and newer(x.get('timestamp'),moment):return True
    return False


def attest(host,payload,root=None):
    from .workflow import human_event
    event=human_event(payload,host)
    allowed=(Path.home()/('.codex/sessions' if host=='codex' else '.claude/projects')).resolve()
    if payload.get('transcript_path'):
        paths=[Path(payload['transcript_path']).expanduser().resolve()]
    else:paths=list(allowed.rglob('*'+event['session']+'*.jsonl'))
    if len(paths)!=1 or not paths[0].is_relative_to(allowed) or not paths[0].is_file():
        raise Refused('The native human transcript is not available yet; retry OH after the host finishes saving this turn')
    path=paths[0];matches=[];times=[];turn=None;session=None;source=None
    with path.open('rb') as stream:
        first=stream.readline()
        stream.seek(max(len(first),path.stat().st_size-8*1024*1024))
        import itertools
        for line in itertools.chain([first],stream):
            try:x=json.loads(line)
            except ValueError:continue
            p=x.get('payload',{})
            if host=='codex':
                if x.get('type')=='session_meta':
                    session=p.get('id');source=p.get('source')
                    if root is not None and not Path(p.get('cwd','')).resolve().is_relative_to(Path(root).resolve()):raise Refused('Human turn belongs to another project checkout')
                if p.get('type')=='task_started':turn=p.get('turn_id')
                # exec/subagent input is model-delegated work, not a new human grant.
                if isinstance(source,dict) or source in ('exec','subagent'):continue
                if session!=event['session'] or turn!=event['turn']:continue
                if x.get('type')=='event_msg' and p.get('type')=='user_message':
                    text=p.get('message')
                elif x.get('type')=='response_item' and p.get('role')=='user':
                    text='\n'.join(c.get('text','') for c in p.get('content',[]) if c.get('type') in ('input_text','text'))
                else:continue
            else:
                if x.get('type')!='user' or x.get('isSidechain') or x.get('promptSource')=='sdk' or x.get('turnOrigin')=='sdk' or x.get('entrypoint')=='sdk-cli':continue
                if x.get('sessionId')!=event['session'] or x.get('promptId')!=event['turn']:continue
                if root is not None and not Path(x.get('cwd','')).resolve().is_relative_to(Path(root).resolve()):raise Refused('Human turn belongs to another project checkout')
                message=x.get('message',{})
                if message.get('role')!='user':continue
                text=message.get('content')
                if isinstance(text,list):text='\n'.join(c.get('text','') for c in text if c.get('type')=='text')
            if isinstance(text,str) and text.strip()==event['prompt']:
                matches.append(digest(x))
                if x.get('timestamp'):times.append(x['timestamp'])
    if not matches:raise Refused('No matching native human turn is saved yet; no authority was granted. Retry OH after the host saves it.')
    # Codex can retain the same turn as both event_msg and response_item; the native turn ID
    # and exact text collapse them into one source, with both evidence hashes retained.
    return event|{'at':min(times) if times else None,'record_hashes':sorted(set(matches)),'transcript_path':str(path)}


@state_writer
def materialize(root):
    from .workflow import active_file
    path=pending_file(root)
    if not path.exists():
        desktop_pending(root)
        if not path.exists():return click(root)
    with lock(path.with_suffix('.lock')):
        locator=read_json(path)
        # The person's latest answer wins, typed or clicked, by the host's own transcript times.
        chosen=candidate(root) if active_file(root).exists() else None
        try:event=attest(locator['host'],locator['payload'],root)
        except Refused:
            if not chosen:raise
            from datetime import datetime,timezone
            staged=locator.get('staged_at') or datetime.fromtimestamp(path.stat().st_mtime,timezone.utc).isoformat()
            # A click made after this typed choice was staged wins; so does any click once the typed turn can no
            # longer verify (the transcript has moved past it). An older click never displaces a typed choice
            # the host is still saving.
            if not newer(chosen[1].get('at'),staged) and not saved_after(chosen[2],chosen[1]['session'],staged):raise
            path.unlink();return _click(root,chosen)
        used=used_file(root,event)
        if used.exists():
            path.unlink();record=read_json(used)
            if 'refused' in record:raise Refused(record['refused'])
            return record['result']
        if chosen and newer(chosen[1].get('at'),event.get('at')):
            # Clicked after typing: the typed turn is spent without effect.
            atomic_json(used,{'source':event,'refused':'Superseded by a later click on the same menu.'},immutable=True)
            path.unlink();return _click(root,chosen)
        from .cli import host_hook
        try:
            result=host_hook(root,locator['host'],locator['payload'],verified=event)
            if result is None:raise Refused('This input is not a supported native OH transition')
        except Exception as exc:
            # The human's turn was verified and answered with this refusal: it is spent, so the next typed command
            # isn't blocked behind it. Replaying the same turn gives the same refusal, and the next plain `oh run`
            # says the command has to be typed again instead of showing an older run.
            message=(str(exc) if isinstance(exc,Refused) else f'OH could not carry out this command ({type(exc).__name__}: {exc})').strip()
            message+=' OH answered this command; type it again once this is fixed.'
            atomic_json(used,{'source':event,'refused':message},immutable=True)
            atomic_json(refusal_file(root),{'refused':message});path.unlink()
            raise Refused(message) from exc
        refusal_file(root).unlink(missing_ok=True)
        atomic_json(used,{'source':event,'result':result},immutable=True)
        from .transcripts import register
        from .workflow import load_run
        if active_file(root).exists():
            _,run=load_run(root)
            if run['status']=='running':register(root,locator['host'],locator['payload']|{'transcript_path':event['transcript_path']},run['id'],run['project'])
        path.unlink()
        return result


def desktop_pending(root):
    """No-argument fallback: use only the latest native Desktop human turn."""
    if os.environ.get('OH_CHILD_ATTEMPT'):return
    session=os.environ.get('CODEX_THREAD_ID') or os.environ.get('CODEX_SESSION_ID')
    if not session or not re.fullmatch(r'[a-zA-Z0-9_-]+',session):return
    files=list((Path.home()/'.codex/sessions').rglob('*'+session+'*.jsonl'))
    if len(files)!=1:return
    path=files[0];meta=None;turn=None;prompt=None
    # The first record establishes origin; a bounded tail locates the current turn.
    with path.open('rb') as stream:
        first=stream.readline()
        try:meta=json.loads(first).get('payload',{})
        except ValueError:return
        if meta.get('id')!=session or meta.get('source')!='vscode' or meta.get('originator')!='Codex Desktop':return
        if Path(meta.get('cwd','')).resolve()!=Path(root).resolve():return
        stream.seek(max(0,path.stat().st_size-4*1024*1024))
        for line in stream:
            try:item=json.loads(line)
            except ValueError:continue
            payload=item.get('payload',{})
            if item.get('type')=='event_msg' and payload.get('type')=='task_started':turn=payload.get('turn_id');prompt=None
            if item.get('type')=='event_msg' and payload.get('type')=='user_message':prompt=payload.get('message')
    if not turn or not isinstance(prompt,str):return
    from .entry import command
    text=prompt.strip()
    if not command(text):return
    payload={'hook_event_name':'UserPromptSubmit','session_id':session,'turn_id':turn,'prompt':text,'transcript_path':str(path)}
    attest('codex',payload,root)
    source=digest({'host':'codex','session':session,'turn':turn,'prompt':text})
    from .storage import project
    if (state_home()/'projects'/project(root)['id']/'human-events'/(source+'.json')).exists():return
    from .entry import receive
    receive(root,'codex',payload)

