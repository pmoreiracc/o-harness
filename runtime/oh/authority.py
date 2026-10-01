from .storage import checkout_file

from .storage import state_writer
"""A hook payload is a locator. Only a native user transcript record grants work."""
import json
import os
from pathlib import Path
import re
from time import sleep
from .storage import Refused,atomic_json,digest,git,lock,now,read_json,state_home


def pending_file(root):return checkout_file(root, 'oh-pending-human.json')


def pending_locators(locator):
    return [{k:v for k,v in locator.items() if k!='prior'},*locator.get('prior',[])]


def retain_pending(path,locators):
    if locators:atomic_json(path,locators[0]|{'prior':locators[1:]})
    else:path.unlink(missing_ok=True)


class Expired(Refused):
    """The person typed something newer in the conversation, so this command is no longer what they asked for."""


class Saving(Refused):
    """The host has not finished writing the native evidence yet; the same read may succeed shortly."""


def saved(read):
    """Retry only incomplete host evidence, for at most 1.5 seconds. Never retry a workflow mutation."""
    for delay in (0,0.1,0.2,0.4,0.8):
        if delay:sleep(delay)
        try:return read()
        except Saving:
            if delay==0.8:raise


def codex_history(path,session):
    """Stream native human messages and their context; large tool output must not hide a checkout change."""
    messages=[];turn=None
    with path.open('rb') as stream:
        try:first=stream.readline();record=json.loads(first)
        except ValueError:raise Saving('Codex is still saving this conversation; retry the same OH operation.')
        if not isinstance(record,dict):raise Refused('Invalid Codex session record')
        meta=record.get('payload',{})
        if record.get('type')!='session_meta' or meta.get('id')!=session:
            raise Refused('The saved Codex conversation does not match this invocation')
        if isinstance(meta.get('source'),dict) or meta.get('source') in ('exec','subagent'):
            raise Refused('Delegated agent prompts cannot grant authority')
        cwd=meta.get('cwd')
        for line in stream:
            try:x=json.loads(line)
            except ValueError:
                if not line.endswith(b'\n'):raise Saving('Codex is still saving this conversation; retry the same OH operation.')
                continue
            if not isinstance(x,dict):continue
            p=x.get('payload',{})
            if x.get('type')=='turn_context':cwd=p.get('cwd') or cwd
            if x.get('type')!='event_msg':continue
            if p.get('type')=='task_started':turn=p.get('turn_id')
            if p.get('thread_id',session)!=session:continue
            if p.get('type')=='user_message':
                message_turn=p.get('turn_id') or turn;text=p.get('message')
            elif p.get('type')=='item_completed' and (p.get('item') or {}).get('type')=='UserMessage':
                item=p['item'];message_turn=p.get('turn_id');content=item.get('content')
                if not isinstance(item.get('id'),str) or not item['id']:continue
                text=content if isinstance(content,str) else '\n'.join(c['text'] for c in content
                    if isinstance(c,dict) and c.get('type')=='text' and isinstance(c.get('text'),str)) if isinstance(content,list) else None
            else:continue
            if isinstance(message_turn,str) and message_turn and isinstance(text,str):
                messages.append({'turn':message_turn,'prompt':text.strip(),'cwd':cwd,'at':x.get('timestamp'),'record_hashes':[digest(x)]})
    return meta,turn,messages,cwd


def stage(root,host,payload,idea=None):
    """Keep a typed command until OH verifies it. `idea`: the command ('propose' or 'design') whose argument the
    text is, because OH asked for it (see `wait_for`)."""
    if os.environ.get('OH_CHILD_ATTEMPT'):raise Refused('Delegated agent prompts cannot grant authority')
    from .workflow import human_event
    event=human_event(payload,host)  # shape only; no grant is issued here
    if not re.fullmatch(r'[a-zA-Z0-9_-]+',event['session']):raise Refused('Invalid native session identifier')
    locator={'host':host,'payload':payload,'event':event}|({'idea':idea} if idea else {})
    path=pending_file(root)
    with lock(path.with_suffix('.lock')):
        # Hooks can arrive before the host saves the message, or out of order. Keep the locators;
        # only materialization may decide which native human request supersedes another.
        if path.exists():
            previous=pending_locators(read_json(path))
            for item in previous:
                if item['event']==event and item.get('superseded_before'):
                    locator['superseded_before']=item['superseded_before']
            locator['prior']=[item for item in previous if item['event']!=event]
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
    gate=describe(journal,state,root) if state['host']=='claude' else None
    return (gate,state,journal.records()[-1]['at']) if gate else None


def answer(root,hint=None,after=None):
    """Apply the person's latest answer to the menu the run waits on, read from the owner's own transcript.
    Only that single latest answer counts: once it is applied or refused, no earlier answer can take its place,
    and applying it moves the menu on so every earlier answer is out of date. `hint` is a typed menu word the
    prompt hook saw: if it can't be read as that latest answer, nothing is applied. `after` is when a waiting
    command was typed: an answer given before it waits, since the command is the person's latest act."""
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
    if not found or after and not newer(found.get('at'),after):return None
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
    return noted(result,supersede(root,'claude',found,locked=True))


def noted(result,dropped):
    """Say once that a menu answer given after a typed command set that command aside."""
    if not dropped:return result
    return result|{'note':f'You answered the menu after typing {dropped}, so OH set that command aside; type it again to run it.'}


def answered(root,host,session,transcript):
    """What the typed path does after a human choice applies: count the owner conversation's usage toward this
    run when it is running again."""
    from .transcripts import register
    from .workflow import load_run
    _,run=load_run(root)
    if run['status']=='running' and transcript:
        register(root,host,{'session_id':session,'transcript_path':transcript},run['id'],run['project'])


COMMAND_TAG=r'<(command-message|command-name|command-args)>(.*?)</\1>'


def saved_command(text):
    """Claude saves a typed slash command as its tags (<command-name>/oh-propose</command-name>, its
    <command-args> and a <command-message>, in either order), not as the text typed. (name, args), or None
    when the record holds anything else."""
    tags=re.findall(COMMAND_TAG,text,re.S);names=[tag for tag,_ in tags]
    if 'command-name' not in names or len(set(names))!=len(names) or re.sub(COMMAND_TAG,'',text,flags=re.S).strip():return None
    found=dict(tags)
    return skill_name(found['command-name'].strip()),found.get('command-args','').strip()


def typed_command(prompt):
    """The (name, args) of a slash command as the prompt hook passes it, or None for other text."""
    if not prompt.startswith('/'):return None
    name,*args=prompt.split(maxsplit=1)
    return skill_name(name),(args or [''])[0].strip()


def skill_name(command):
    """/oh-propose and /o-harness:oh-propose are the same command, whichever form the person typed or Claude
    saved; another plugin's /other:oh-propose stays its own."""
    return command.removeprefix('/').removeprefix('o-harness:')


def expanded_skill(x):
    """The skill Claude expanded for a slash command, from the record it saves with the command's turn
    ("Base directory for this skill: <plugin>/skills/<name>"), or None."""
    content=(x.get('message') or {}).get('content')
    text=content if isinstance(content,str) else '\n'.join(c.get('text','') for c in content if isinstance(c,dict) and c.get('type')=='text') if isinstance(content,list) else ''
    found=re.match(r'Base directory for this skill: (.+)',text)  # the rest of the line: a folder may hold spaces
    return Path(found[1].strip()).name if found else None


def prompted(x,session):
    """Whether a Claude record is something the person typed in this conversation: a prompt or a command, not a
    tool result, a menu answer or a summary Claude wrote."""
    content=(x.get('message') or {}).get('content')
    typed=isinstance(content,str) or isinstance(content,list) and any(isinstance(c,dict) and c.get('type')!='tool_result' for c in content)
    return (x.get('type')=='user' and x.get('sessionId')==session and bool(x.get('promptId')) and typed
            and not x.get('isCompactSummary') and human(x))


def attest(host,payload,root=None):
    return saved(lambda: _attest(host,payload,root))


def _attest(host,payload,root=None,*,caller=True):
    from .workflow import human_event
    event=human_event(payload,host)
    if caller and os.environ.get('CODEX_THREAD_ID') and (host!='codex' or event['session']!=os.environ['CODEX_THREAD_ID']):
        raise Refused('This command belongs to another conversation; continue it there.')
    from .hosts import codex_home
    allowed=(codex_home()/'sessions' if host=='codex' else Path.home()/'.claude/projects').resolve()
    if payload.get('transcript_path'):
        paths=[Path(payload['transcript_path']).expanduser().resolve()]
    else:paths=list(allowed.rglob('*'+event['session']+'*.jsonl'))
    if len(paths)!=1 or not paths[0].is_relative_to(allowed) or not paths[0].is_file():
        raise Saving('The native human transcript is not available yet; retry the same OH operation after the host saves it')
    if host=='codex':
        path=paths[0];_,_,messages,_=codex_history(path,event['session'])
        matches=[m for m in messages if (m['turn'],m['prompt'])==(event['turn'],event['prompt'])]
        if root is not None and any(not within(m['cwd'],root) for m in matches):raise Refused('Human turn belongs to another project checkout')
        if matches and messages[-1] not in matches:raise Expired('The person typed something newer in this conversation')
        if not matches:
            if messages and messages[-1]['turn']==event['turn']:
                raise Refused('The requested command does not match the native human message; nothing was applied')
            raise Saving('Codex has not saved this human message yet; retry the same OH operation.')
        return event|{'at':min(m['at'] for m in matches if m['at']) if any(m['at'] for m in matches) else None,
            'record_hashes':sorted({h for m in matches for h in m['record_hashes']}),'transcript_path':str(path)}
    path=paths[0];matches=[];times=[];tagged=[];expanded={};latest=None
    with path.open('rb') as stream:
        first=stream.readline()
        stream.seek(max(len(first),path.stat().st_size-8*1024*1024))
        import itertools
        for line in itertools.chain([first],stream):
            try:x=json.loads(line)
            except ValueError:
                if not line.endswith(b'\n'):raise Saving('Claude is still saving this conversation; retry the same OH operation.')
                continue
            if not isinstance(x,dict):continue
            if prompted(x,event['session']):latest=x['promptId']
            if x.get('type')!='user' or x.get('sessionId')!=event['session'] or x.get('promptId')!=event['turn']:continue
            if x.get('isMeta') and not x.get('isSidechain'):
                # The model's own Skill tool call saves the same text; only a typed command's expansion
                # follows the command's record directly and names no tool call.
                if not x.get('sourceToolUseID') and x.get('parentUuid'):expanded.setdefault(x['parentUuid'],set()).add(expanded_skill(x))
                continue
            if not human(x):continue
            if root is not None and not within(x.get('cwd'),root):raise Refused('Human turn belongs to another project checkout')
            message=x.get('message',{})
            if message.get('role')!='user':continue
            text=message.get('content')
            if isinstance(text,list):text='\n'.join(c.get('text','') for c in text if c.get('type')=='text')
            if isinstance(text,str) and text.strip()==event['prompt']:
                matches.append(digest(x))
                if x.get('timestamp'):times.append(x['timestamp'])
            elif host=='claude' and isinstance(text,str) and typed_command(event['prompt']) is not None and saved_command(text)==typed_command(event['prompt']):
                tagged.append(x)
    # Command tags alone could be text the person pasted: Claude ran the command only if it also saved the
    # skill it expanded from that very record.
    for x in tagged:
        if typed_command(event['prompt'])[0] in expanded.get(x.get('uuid'),()):
            matches.append(digest(x))
            if x.get('timestamp'):times.append(x['timestamp'])
            # One turn, one grant: every spelling of the command (with or without o-harness:, any spacing) is
            # recorded as the same prompt, so a respelled replay finds the turn already spent.
            name,args=typed_command(event['prompt'])
            event=event|{'prompt':'/o-harness:'+name+(' '+args if args else '')}
    if not matches:
        error=Saving if latest!=event['turn'] or tagged and not expanded else Refused
        raise error('No matching native human turn is saved yet; no authority was granted. Retry OH after the host saves it.')
    if latest not in (None,event['turn']):raise Expired('The person typed something newer in this conversation')
    return event|{'at':min(times) if times else None,'record_hashes':sorted(set(matches)),'transcript_path':str(path)}


def pending_choice(root,locator):
    """Resolve staged locators from native evidence; arrival order cannot withdraw a human request."""
    candidates=pending_locators(locator)
    def read():
        verified=[];deferred=[];revoked=[]
        for candidate in candidates:
            try:
                # Inspect other conversations only to order their requests. The winner must still pass
                # caller-bound attestation before anything is applied or marked spent.
                event=_attest(candidate['host'],candidate['payload'],root,caller=False)
                if newer(candidate.get('superseded_before'),event.get('at')):revoked.append((candidate,event))
                else:verified.append((candidate,event))
            except Saving:
                if candidate.get('superseded_before'):deferred.append(candidate)
                else:raise
            except Refused:continue
        if verified and deferred:raise Saving('A pending command is still being saved; retry the same OH operation.')
        return verified,deferred,revoked
    verified,deferred,revoked=saved(read)  # one bounded wait; no request is lost while evidence is incomplete
    for candidate,event in revoked:
        if starts_work(candidate):remember_request(root,event)
        spent(root,event|{'prompt':candidate['event']['prompt']},'Superseded by a later answer on the menu.')
    if not verified:
        if deferred or revoked:
            retain_pending(pending_file(root),deferred)
            return None  # no new authority; an already approved run may continue
        return locator  # the ordinary path reports/clears an expired command once
    selected,event=verified[0]
    for candidate,proof in verified[1:]:
        if newer(proof.get('at'),event.get('at')):selected,event=candidate,proof
    attest(selected['host'],selected['payload'],root)
    for candidate,proof in verified:
        if used_file(root,proof)!=used_file(root,event) and newer(event.get('at'),proof.get('at')):
            spent(root,proof|{'prompt':candidate['event']['prompt']},'Superseded by a newer command in this checkout.')
    return selected


def remember_request(root,event):
    """Keep verified request/menu chronology after the pending slot is consumed, under its same lock."""
    if not event.get('at'):return event  # older hosts cannot establish cross-chat order
    path=checkout_file(root,'oh-latest-request.json')
    latest=read_json(path) if path.exists() else {}
    if newer(latest.get('at'),event['at']):return latest
    if not latest or newer(event['at'],latest.get('at')):atomic_json(path,event)
    return event


@state_writer
def materialize(root):
    from .workflow import active_file
    # A fresh native invocation may replace a pending request, including one from another conversation.
    discovered=desktop_pending(root)
    path=pending_file(root)
    with lock(path.with_suffix('.lock')):
        if path.exists() and ((locator:=read_json(path)).get('prior') or locator.get('superseded_before')):
            selected=pending_choice(root,locator)
            if selected is None:return discovered if discovered is not None else answer(root)
            atomic_json(path,selected)
        if path.exists() and bare_choice(read_json(path)) and menu_waiting(root):
            # A menu answer typed in Claude is read from the transcript like a click, so the person's latest
            # answer wins whichever way they gave it; the hook's locator only said that one was typed. Wait
            # while Claude may still be saving that turn, so an older click never wins over it.
            locator=read_json(path)
            def ready():
                if not settled(root,locator,path):
                    raise Saving('Your typed choice is not saved in the conversation yet; retry the same OH operation.')
            saved(ready)
            path.unlink();return answer(root,hint=locator['event']['turn'])
        if not path.exists():return discovered if discovered is not None else answer(root)
        locator=read_json(path)
        try:event=attest(locator['host'],locator['payload'],root)
        except Expired:
            # Said once: the person moved on, so this command is spent and never carried out behind their back.
            message=f"You typed something after {locator['event']['prompt']}, so OH set it aside; type it again to run it."
            spent(root,locator['event'],message);path.unlink()
            raise Refused(message)
        except Refused:
            # A command that can't be verified never holds up the open menu.
            if menu_waiting(root) and (result:=answer(root)) is not None:return result
            raise
        # The person answered the open menu after typing this command: that answer is their latest act.
        if menu_waiting(root) and (result:=answer(root,after=event.get('at'))) is not None:return result
        used=used_file(root,event)
        if used.exists():
            path.unlink();record=read_json(used)
            if 'refused' in record:raise Refused(record['refused'])
            return record['result']
        from .cli import host_hook
        try:
            if starts_work(locator) and newer(remember_request(root,event).get('at'),event.get('at')):
                from .storage import Final
                raise Final('Superseded by a later command or menu answer in this checkout.')
            result=host_hook(root,locator['host'],locator['payload'],verified=event,idea=locator.get('idea'))
            if result is None:raise Refused('This input is not a supported native OH transition')
        except Exception as exc:
            # A refused command that starts work stays pending and is spent only once carried out, so `oh run`
            # carries it out when the reason is fixed, without the person typing it again. A newer command or a
            # later menu answer replaces it; a newer prompt sets it aside. A choice (a menu word, /oh-resume)
            # answers the moment it was typed at, and a failure OH did not foresee would only repeat: those are
            # said once and spent, as is a refusal that is the command's last word.
            refused=exc if isinstance(exc,Refused) else Refused(f'OH could not carry out this command ({type(exc).__name__}: {exc})')
            from .storage import Final
            if not starts_work(locator) or not isinstance(exc,Refused) or isinstance(exc,Final):
                atomic_json(used,{'source':event,'refused':str(refused)},immutable=True);path.unlink()
            raise refused from exc
        atomic_json(used,{'source':event,'result':result},immutable=True)
        from .transcripts import register
        from .workflow import load_run
        if active_file(root).exists():
            _,run=load_run(root)
            if run['status']=='running':register(root,locator['host'],locator['payload']|{'transcript_path':event['transcript_path']},run['id'],run['project'])
        path.unlink()
        return result


def starts_work(locator):
    """A typed command that starts work (propose, design, deliver, a prepared request), which OH keeps until done."""
    from .entry import command
    parsed=command((locator.get('event') or {}).get('prompt'))
    return bool(locator.get('idea')) or bool(parsed) and parsed[0] in ('propose','design','deliver','oh-start')


def waiting_file(session):
    """Where OH notes that it waits for this conversation's next message; the prompt hook looks for it by name."""
    if not isinstance(session,str) or not re.fullmatch(r'[a-zA-Z0-9_-]+',session):raise Refused('Invalid native session identifier')
    return state_home()/'waiting'/(session+'.json')


def wait_for(root,human,command,ask):
    """Make the person's next message in this conversation and checkout the argument of `command` (they typed it
    bare, or chose Reconsider). Nothing runs until they answer; their answer is verified like a typed command."""
    from .storage import checkout_id
    atomic_json(waiting_file(human['session']),{'host':human['host'],'session':human['session'],'checkout':checkout_id(root),
        'command':command,'ask':ask,'at':now()})


def waiting_for(root,host,session):
    """What OH waits for from this conversation in this checkout: the command and the question asked, or None."""
    from .storage import checkout_id
    try:
        found=read_json(waiting_file(session))
        if found.get('host')!=host or found.get('checkout')!=checkout_id(root):return None
    except (OSError,ValueError,Refused):return None
    return {'command':found['command'],'ask':found['ask'],'at':found.get('at')}


def drop_waiting(session):
    try:waiting_file(session).unlink(missing_ok=True)
    except Refused:pass


def waits(root):
    """What OH waits for in this checkout, from any conversation: {session: record}."""
    from .storage import checkout_id
    found={}
    for path in sorted((state_home()/'waiting').glob('*.json')):
        try:record=read_json(path)
        except (OSError,ValueError):continue
        if record.get('checkout')==checkout_id(root):found[path.stem]=record
    return found


def drop_waits(root):
    """Stop and cancel take away what OH waits for in this checkout, whichever way they were given."""
    for session in waits(root):drop_waiting(session)


def waiting_work(root):
    """Whether a typed command that starts work waits in this checkout."""
    try:return starts_work(read_json(pending_file(root)))
    except FileNotFoundError:return False


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


def supersede(root,host,event,locked=False):
    """A menu answer applied after something was typed wins over it: the person's latest act counts. A typed
    menu word is spent; a typed command waits only when the answer ended the run, which makes room for it.
    Returns the command it set aside, if any. `locked` when the caller already holds the pending lock (the lock
    is per open file, so never take it twice)."""
    path=pending_file(root)
    if not locked:
        with lock(path.with_suffix('.lock')):return supersede(root,host,event,locked=True)
    from .workflow import active_file,load_run
    ended=not active_file(root).exists() or load_run(root)[1]['status'] in ('stopped','pr','completed')
    # A hook may arrive after cleanup, even when nothing was queued at the time of the click.
    if not ended:remember_request(root,event)
    try:locator=read_json(path)
    except FileNotFoundError:return
    retained=[];dropped=None
    for candidate in pending_locators(locator):
        words=bare_choice(candidate,host)
        if ended and not words:
            retained.append(candidate);continue
        try:proof=_attest(candidate['host'],candidate['payload'],root,caller=False)
        except Saving:
            cutoff=candidate.get('superseded_before')
            if not cutoff or newer(event.get('at'),cutoff):candidate=candidate|{'superseded_before':event.get('at')}
            retained.append(candidate);continue
        except Refused:continue  # invalid/expired locators grant nothing; do not spend an unattested source
        if newer(event.get('at'),proof.get('at')):
            if starts_work(candidate):remember_request(root,proof)
            spent(root,proof|{'prompt':candidate['event']['prompt']},'Superseded by a later answer on the menu.')
            if not words:dropped=dropped or candidate['event']['prompt']
        else:retained.append(candidate)
    retain_pending(path,retained)
    return dropped


def spent(root,event,refused):
    """Record a waiting command or choice as used without carrying it out, so a replay of it is refused. A Claude
    command is recorded under its typed spelling and under the one `attest` verifies from its command tags."""
    events=[event]
    if event.get('host')=='claude' and (typed:=typed_command(event.get('prompt'))) is not None:
        name,args=typed;events.append(event|{'prompt':'/o-harness:'+name+(' '+args if args else '')})
    for each in events:
        used=used_file(root,each)
        if not used.exists():atomic_json(used,{'source':each,'refused':refused},immutable=True)


def cancel(root):
    """The person chose not to run the command waiting in this checkout. Like stop, it only takes authority away,
    but a worker never decides for the person."""
    if os.environ.get('OH_CHILD_ATTEMPT'):raise Refused('Delegated agents cannot cancel the person\'s command')
    path=pending_file(root)
    drop_waits(root)
    with lock(path.with_suffix('.lock')):
        try:locator=read_json(path)
        except FileNotFoundError:return {'cancelled':None,'message':'No typed command is waiting in this checkout.'}
        for candidate in pending_locators(locator):spent(root,candidate['event'],'Cancelled by the person.')
        path.unlink()
    return {'cancelled':locator['event']['prompt'],'message':'The waiting command was cancelled; nothing of it ran.'}


def desktop_pending(root):
    return saved(lambda: _desktop_pending(root))


def _desktop_pending(root):
    """No-argument fallback: recover the latest human command from this Codex conversation."""
    if os.environ.get('OH_CHILD_ATTEMPT'):return
    session=os.environ.get('CODEX_THREAD_ID') or os.environ.get('CODEX_SESSION_ID')
    if not session or not re.fullmatch(r'[a-zA-Z0-9_-]+',session):return
    from .hosts import codex_home
    files=list((codex_home()/'sessions').rglob('*'+session+'*.jsonl'))
    expected=os.environ.get('OH_CODEX_TURN_ID')  # supplied by MCP, never a tool argument
    if len(files)!=1:
        if expected:raise Saving('Codex has not saved this conversation yet; retry the same OH operation.')
        return
    path=files[0]
    try:meta,turn,messages,_=codex_history(path,session)
    except Saving:raise
    except Refused:
        if expected:raise
        return  # a shell without this checkout's host context is not a Desktop invocation
    if meta.get('source')!='cli' and (meta.get('source')!='vscode' or meta.get('originator') not in ('Codex Desktop','codex_work_desktop')):return
    if not messages or messages[-1]['turn']!=(expected or turn):
        if expected:raise Saving('Codex has not saved the calling human turn yet; retry the same OH operation.')
        return
    message=messages[-1];text=message['prompt']
    if not within(message['cwd'],root):
        if expected:raise Refused('Human turn belongs to another project checkout')
        return
    from .entry import command
    asked=None if command(text) else waiting_for(root,'codex',session)
    if not command(text) and not asked:return
    payload={'hook_event_name':'UserPromptSubmit','session_id':session,'turn_id':message['turn'],'prompt':text,'transcript_path':str(path)}
    event=_attest('codex',payload,root)
    if asked and not newer(event.get('at'),asked['at']):return
    # Re-reading a consumed command returns its result; it never grants work again. This also lets a retry
    # report its own completed run instead of mistaking the absence of new authority for a failure.
    from .registry import lookup
    try:lookup(root)
    except Refused:pass  # receive registers a fresh checkout after a verified explicit invocation
    else:
        used=used_file(root,event)
        if used.exists():
            record=read_json(used)
            if 'refused' in record:
                # A later native menu click can authorize this conversation's current run without
                # adding another UserMessage. Do not make an older, withdrawn typed choice block it.
                from .workflow import active_file,load_run
                if active_file(root).exists():
                    journal,state=load_run(root)
                    if state['host']=='codex' and state['human']['session']==session:
                        sources=[state['human'],*[r['data']['source'] for r in journal.records() if r['kind']=='transition']]
                        if any(s.get('session')==session and newer(s.get('at'),event.get('at')) for s in sources):
                            return {'run':state['id'],'status':state['status']}
                raise Refused(record['refused'])
            return record['result']
    from .entry import receive
    result=receive(root,'codex',payload)
    return None if result and result.get('pending') else result
