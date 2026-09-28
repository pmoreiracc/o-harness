from .storage import checkout_file

from .storage import state_writer
"""A hook payload is a locator. Only a native user transcript record grants work."""
import json
import os
from pathlib import Path
import re
from .storage import Refused,atomic_json,digest,git,lock,read_json,state_home


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
        if path.exists() and read_json(path)!=locator:
            raise Refused('A prior human choice is pending verification; resolve it before another choice')
        atomic_json(path,locator)
    return {'pending':True,'message':'Run OH to verify and apply this native human choice'}


def stage_click(root,host,payload):
    """A Claude question-tool answer on an OH menu. The hook payload only locates it; `run` reads the click
    from Claude's own transcript before anything happens."""
    if os.environ.get('OH_CHILD_ATTEMPT'):raise Refused('Delegated agent prompts cannot grant authority')
    if host!='claude' or payload.get('hook_event_name')!='PostToolUse' or payload.get('tool_name')!='AskUserQuestion':
        raise Refused('Only Claude\'s question tool carries OH menu clicks')
    session=payload.get('session_id');use=payload.get('tool_use_id')
    if not isinstance(session,str) or not re.fullmatch(r'[a-zA-Z0-9_-]+',session) or not isinstance(use,str) or not re.fullmatch(r'[a-zA-Z0-9_-]+',use):
        raise Refused('A host session and tool call ID are required')
    from .workflow import active_file
    if not active_file(root).exists():return None
    locator={'host':host,'kind':'click','payload':{k:payload.get(k) for k in ('session_id','tool_use_id','transcript_path')}}
    path=pending_file(root)
    with lock(path.with_suffix('.lock')):
        if path.exists() and read_json(path)!=locator:
            raise Refused('A prior human choice is pending verification; run OH `run` first, then ask again')
        atomic_json(path,locator)
    return {'pending':True,'message':'Run OH `run` to verify and apply this click'}


def attest_click(payload,root=None):
    """The click as Claude saved it: the model's question-tool call, without prefilled answers, and the
    answer the host returned for that call. Both records belong to this session and checkout."""
    session=payload['session_id'];use=payload['tool_use_id']
    allowed=(Path.home()/'.claude/projects').resolve()
    path=Path(payload.get('transcript_path') or '').expanduser().resolve()
    if not path.is_relative_to(allowed) or not path.is_file():
        raise Refused('The native human transcript is not available yet; retry OH after the host finishes saving this turn')
    asked=answered=None;hashes=[];at=None
    with path.open('rb') as stream:
        stream.seek(max(0,path.stat().st_size-8*1024*1024))
        for line in stream:
            try:x=json.loads(line)
            except ValueError:continue
            if not isinstance(x,dict) or x.get('isSidechain') or x.get('sessionId')!=session:continue
            if x.get('promptSource')=='sdk' or x.get('turnOrigin')=='sdk' or x.get('entrypoint')=='sdk-cli':continue
            content=(x.get('message') or {}).get('content')
            if not isinstance(content,list):continue
            if x.get('type')=='assistant':
                found=[c for c in content if isinstance(c,dict) and c.get('type')=='tool_use' and c.get('id')==use]
            elif x.get('type')=='user':
                found=[c for c in content if isinstance(c,dict) and c.get('type')=='tool_result' and c.get('tool_use_id')==use]
            else:continue
            if not found:continue
            if root is not None and Path(x.get('cwd','')).resolve()!=Path(root).resolve():raise Refused('Human turn belongs to another project checkout')
            if x['type']=='assistant':asked=found[0]
            else:
                if found[0].get('is_error'):raise Refused('The question was refused before it was shown; ask again')
                answered=x.get('toolUseResult');at=x.get('timestamp')
            hashes.append(digest(x))
    if asked is None or answered is None:raise Refused('No saved answer to that menu yet; no choice was made. Retry OH after the host saves it.')
    request=asked.get('input') if asked.get('name')=='AskUserQuestion' else None
    if not isinstance(request,dict) or 'answers' in request:
        raise Refused('That answer was written by the model, not clicked by the person; nothing was chosen. Ask again.')
    questions=request.get('questions')
    if not isinstance(questions,list) or len(questions)!=1 or not isinstance(questions[0],dict):raise Refused('An OH menu asks exactly one question')
    answers=answered.get('answers') if isinstance(answered,dict) else None
    answer=answers.get(questions[0].get('question')) if isinstance(answers,dict) else None
    if not isinstance(answer,str):raise Refused('The menu came back without an answer; ask again.')
    return {'host':'claude','session':session,'turn':use,'prompt':answer,'question':questions[0],'via':'question',
            'at':at,'record_hashes':sorted(set(hashes)),'transcript_path':str(path)}


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
                    if root is not None and Path(p.get('cwd','')).resolve()!=Path(root).resolve():raise Refused('Human turn belongs to another project checkout')
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
                if root is not None and Path(x.get('cwd','')).resolve()!=Path(root).resolve():raise Refused('Human turn belongs to another project checkout')
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
    path=pending_file(root)
    if not path.exists():
        desktop_pending(root)
        if not path.exists():return None
    with lock(path.with_suffix('.lock')):
        locator=read_json(path);click=locator.get('kind')=='click'
        event=attest_click(locator['payload'],root) if click else attest(locator['host'],locator['payload'],root)
        source=digest({k:event[k] for k in ('host','session','turn','prompt')})
        from .storage import project
        used=state_home()/'projects'/project(root)['id']/'human-events'/(source+'.json')
        if used.exists():
            path.unlink();record=read_json(used)
            if 'refused' in record:raise Refused(record['refused'])
            return record['result']
        from .cli import host_hook
        try:
            result=clicked(root,event) if click else host_hook(root,locator['host'],locator['payload'],verified=event)
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
        from .workflow import active_file,load_run
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


def clicked(root,event):
    """Apply a verified click: the question must be exactly the menu OH is showing now."""
    from .gates import apply,ask,current,pick
    gate=current(root)
    if not gate or ask(gate)['questions'][0]!=event['question']:
        raise Refused('That menu is not the one OH is waiting on (it changed, or the question was altered). Run OH `status` and ask again.')
    return apply(root,event|{'prompt':pick(gate,event['prompt'])},gate['id'])
