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
        if path.exists() and read_json(path)!=locator:
            raise Refused('A prior human choice is pending verification; resolve it before another choice')
        atomic_json(path,locator)
    return {'pending':True,'message':'Run OH to verify and apply this native human choice'}


def owner_transcript(human):
    """The saved transcript of the Claude conversation that owns the run."""
    allowed=(Path.home()/'.claude/projects').resolve()
    if human.get('transcript_path'):paths=[Path(human['transcript_path']).expanduser().resolve()]
    else:paths=[p.resolve() for p in allowed.glob('*/'+human['session']+'.jsonl')] if re.fullmatch(r'[a-zA-Z0-9_-]+',human['session']) else []
    if len(paths)!=1 or not paths[0].is_relative_to(allowed) or not paths[0].is_file():return None
    return paths[0]


def within(cwd,root):
    """Whether a saved working folder is this checkout or one of its folders, not a checkout nested inside it."""
    cwd=Path(cwd or '').resolve();root=Path(root).resolve()
    if not cwd.is_relative_to(root):return False
    return not any((folder/'.git').exists() for folder in [cwd,*cwd.parents] if folder!=root and folder.is_relative_to(root))


def human(x):
    """A record the person produced, not another agent, a notification or an automated SDK caller. Claude marks
    what a person typed with origin kind "human" (the desktop app also marks it promptSource "sdk"); records
    without an origin, such as tool results, count unless they carry an automation marker."""
    if x.get('isSidechain') or x.get('isMeta'):return False
    origin=x.get('origin') if isinstance(x.get('origin'),dict) else {}
    if origin.get('kind') is not None:return origin['kind']=='human' and x.get('turnOrigin') in (None,'human')
    return x.get('turnOrigin') is None and x.get('promptSource') not in ('sdk','system') and x.get('entrypoint')!='sdk-cli'


def latest_answer(path,session,root,question,since,hint=None):
    """The person's single latest answer to the current menu in the owner's transcript: a click on exactly this
    menu (the model's question-tool call without answers of its own, and the answer the host returned), or a
    choice they typed after the menu appeared. None when there is none."""
    from .entry import command
    asked={};latest=None;hinted=None
    with path.open('rb') as stream:
        stream.seek(max(0,path.stat().st_size-8*1024*1024))
        for line in stream:
            try:x=json.loads(line)
            except ValueError:continue
            if not isinstance(x,dict) or x.get('sessionId')!=session:continue
            if hint and x.get('promptId')==hint and x.get('type')=='user' and x.get('timestamp'):hinted=hinted or x['timestamp']
            if not human(x):continue
            if not within(x.get('cwd'),root):continue  # the agent may cd into the checkout's folders
            content=(x.get('message') or {}).get('content')
            if x.get('type')=='user' and (isinstance(content,str) or isinstance(content,list) and content and all(isinstance(c,dict) and c.get('type')=='text' for c in content)):
                text=(content if isinstance(content,str) else '\n'.join(c.get('text','') for c in content)).strip()
                parsed=command(text)
                if parsed and parsed[0]=='choice' and x.get('promptId') and newer(x.get('timestamp'),since):
                    latest={'host':'claude','session':session,'turn':x['promptId'],'prompt':text,'via':'typed',
                        'at':x.get('timestamp'),'record_hashes':[digest(x)],'transcript_path':str(path)}
                continue
            if not isinstance(content,list):continue
            for c in content:
                if not isinstance(c,dict):continue
                if x.get('type')=='assistant' and c.get('type')=='tool_use' and c.get('name')=='AskUserQuestion':
                    request=c.get('input');raw=(x.get('wireToolInputs') or {}).get(c.get('id'),request)
                    if request=={'questions':[question]} and raw==request:asked[c.get('id')]=digest(x)
                elif x.get('type')=='user' and c.get('type')=='tool_result' and c.get('tool_use_id') in asked and not c.get('is_error'):
                    result=x.get('toolUseResult');answers=result.get('answers') if isinstance(result,dict) else None
                    answer=answers.get(question['question']) if isinstance(answers,dict) else None
                    if isinstance(answer,str):
                        use=c['tool_use_id']
                        latest={'host':'claude','session':session,'turn':use,'prompt':answer,'via':'question',
                            'at':x.get('timestamp'),'record_hashes':sorted({asked[use],digest(x)}),'transcript_path':str(path)}
    return latest,hinted


def newer(at,than):
    """Whether time `at` is later than `than`; unknown times never are."""
    from datetime import datetime
    try:return datetime.fromisoformat(str(at).replace('Z','+00:00'))>datetime.fromisoformat(str(than).replace('Z','+00:00'))
    except (ValueError,TypeError):return False


def used_file(root,event):
    from .storage import project
    return state_home()/'projects'/project(root)['id']/'human-events'/(digest({k:event[k] for k in ('host','session','turn','prompt')})+'.json')


def menu_waiting(root):
    """The menu a Claude run waits on, with the run, or None."""
    from .gates import describe
    from .workflow import active_file,load_run
    if not active_file(root).exists():return None
    journal,state=load_run(root)
    gate=describe(journal,state) if state['host']=='claude' else None
    return (gate,state,journal.records()[-1]['at']) if gate else None


def answer(root,hint=None):
    """Apply the person's latest answer to the menu the run waits on, read from the owner's own transcript.
    Only that single latest answer counts: once it is applied or refused, no earlier answer can take its place,
    and applying it moves the menu on so every earlier answer is out of date. `hint` is a typed menu word the
    prompt hook saw: if it can't be read as that latest answer, nothing is applied."""
    from .gates import apply,ask,pick
    waiting=menu_waiting(root)
    if not waiting:return None
    gate,state,since=waiting
    path=owner_transcript(state['human'])
    found,hinted=latest_answer(path,state['human']['session'],root,ask(gate)['questions'][0],since,hint) if path else (None,None)
    if hint and (not found or found['turn']!=hint and (not hinted or not newer(found.get('at'),hinted))):
        # The person typed a menu word OH can't read as their latest answer: apply nothing rather than an older one.
        if found and not used_file(root,found).exists():
            atomic_json(used_file(root,found),{'source':found,'refused':'Set aside: a later typed choice could not be read.'},immutable=True)
        raise Refused('OH could not read your typed choice from the conversation, so nothing was applied. Choose again from the menu, or type it again.')
    if not found:return None
    used=used_file(root,found)
    if used.exists():return None
    try:
        choice=pick(gate,found['prompt']) if found['via']=='question' else found['prompt']
        result=apply(root,found|{'prompt':choice},gate['id'])
    except Refused as exc:
        # Said once; this answer is then spent, and it stays the latest, so nothing older applies instead.
        atomic_json(used,{'source':found,'refused':str(exc)},immutable=True)
        raise
    atomic_json(used,{'source':found,'result':result},immutable=True)
    answered(root,'claude',found['session'],str(path))
    return result


def answered(root,host,session,transcript):
    """What the typed path does after a human choice applies: forget an older refusal, and count the owner
    conversation's usage toward this run when it is running again."""
    from .transcripts import register
    from .workflow import load_run
    refusal_file(root).unlink(missing_ok=True)
    _,run=load_run(root)
    if run['status']=='running' and transcript:
        register(root,host,{'session_id':session,'transcript_path':transcript},run['id'],run['project'])


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
                    if root is not None and not within(p.get('cwd'),root):raise Refused('Human turn belongs to another project checkout')
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
                if x.get('type')!='user' or not human(x):continue
                if x.get('sessionId')!=event['session'] or x.get('promptId')!=event['turn']:continue
                if root is not None and not within(x.get('cwd'),root):raise Refused('Human turn belongs to another project checkout')
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
    if not path.exists():desktop_pending(root)  # stages under the same lock, so before taking it
    with lock(path.with_suffix('.lock')):
        if path.exists() and bare_choice(read_json(path)) and menu_waiting(root):
            # A menu answer typed in Claude is read from the transcript like a click, so the person's latest
            # answer wins whichever way they gave it; the hook's locator only said that one was typed. Wait
            # while Claude may still be saving that turn, so an older click never wins over it.
            locator=read_json(path)
            if not settled(root,locator,path):
                raise Refused('Your typed choice is not saved in the conversation yet; run OH again in a moment')
            path.unlink();return answer(root,hint=locator['event']['turn'])
        if not path.exists():return answer(root)
        locator=read_json(path);event=attest(locator['host'],locator['payload'],root)
        used=used_file(root,event)
        if used.exists():
            path.unlink();record=read_json(used)
            if 'refused' in record:raise Refused(record['refused'])
            return record['result']
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


def bare_choice(locator,host='claude'):
    """A typed menu word (continue, approve, refine: ...), not a command."""
    from .entry import command
    parsed=command((locator.get('event') or {}).get('prompt'))
    return locator.get('host')==host and bool(parsed) and parsed[0]=='choice'


def settled(root,locator,path):
    """Whether the owner's transcript already holds this typed turn, or has moved past the moment it was staged
    without it (then it never will)."""
    from datetime import datetime,timezone
    _,state,_=menu_waiting(root)
    transcript=owner_transcript(state['human'])
    if not transcript:return True
    staged=datetime.fromtimestamp(path.stat().st_mtime,timezone.utc).isoformat()
    turn=locator['event'].get('turn');session=state['human']['session']
    with transcript.open('rb') as stream:
        stream.seek(max(0,transcript.stat().st_size-8*1024*1024))
        for line in stream:
            try:x=json.loads(line)
            except ValueError:continue
            if isinstance(x,dict) and x.get('sessionId')==session and (x.get('promptId')==turn or newer(x.get('timestamp'),staged)):return True
    return False


def typed_choice(root,host):
    """The typed menu word waiting to be verified in this checkout, if any."""
    path=pending_file(root)
    try:locator=read_json(path)
    except FileNotFoundError:return None
    return locator if bare_choice(locator,host) else None


def supersede(root,host):
    """A click made after a typed menu word spends that word: the person's latest answer wins."""
    path=pending_file(root)
    with lock(path.with_suffix('.lock')):
        locator=typed_choice(root,host)
        if not locator:return
        used=used_file(root,locator['event'])
        if not used.exists():atomic_json(used,{'source':locator['event'],'refused':'Superseded by a later click on the same menu.'},immutable=True)
        path.unlink()


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

