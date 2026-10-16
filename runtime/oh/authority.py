"""Narrow native human/child provenance. No menus or workflow dispatch."""
import json
import os
import re
from pathlib import Path
from time import sleep
from .storage import Refused, atomic_json, checkout_file, digest, read_json

COMMAND_TAG=r'<(command-message|command-name|command-args)>(.*?)</\1>'

class Expired(Refused): pass
class Saving(Refused): pass
class Unavailable(Saving): pass


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


def human(x,menu=False):
    """A native record trusted under normal host permissions. Human-marked inputs and exact native menu
    replies are accepted; SDK software can imitate both, an accepted limitation in config/invariants.json.
    Unmarked SDK text, other agents and notifications stay excluded. Only latest_answer enables menu
    records, where the unanswered question and returned answer must match the current owning menu."""
    if x.get('isSidechain') or x.get('isMeta'):return False
    origin=x.get('origin') if isinstance(x.get('origin'),dict) else {}
    if origin.get('kind') is not None:return origin['kind']=='human' and x.get('turnOrigin') in (None,'human')
    sdk=isinstance(x.get('entrypoint'),str) and x['entrypoint'].startswith('sdk-')
    return x.get('turnOrigin') is None and x.get('promptSource') not in ('sdk','system') and (menu or not sdk)


def newer(at,than):
    """Whether time `at` is later than `than`; unknown times never are."""
    from datetime import datetime
    try:return datetime.fromisoformat(str(at).replace('Z','+00:00'))>datetime.fromisoformat(str(than).replace('Z','+00:00'))
    except (ValueError,TypeError):return False


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


def attest(host,payload,root=None,*,latest=True):
    return saved(lambda: _attest(host,payload,root,latest=latest))


def _attest(host,payload,root=None,*,caller=True,latest=True):
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
        raise Unavailable('The native human transcript is not available yet; retry the same OH operation after the host saves it')
    if host=='codex':
        path=paths[0];_,_,messages,_=codex_history(path,event['session'])
        matches=[m for m in messages if (m['turn'],m['prompt'])==(event['turn'],event['prompt'])]
        if root is not None and any(not within(m['cwd'],root) for m in matches):raise Refused('Human turn belongs to another project checkout')
        if latest and matches and messages[-1] not in matches:raise Expired('The person typed something newer in this conversation')
        if not matches:
            if messages and messages[-1]['turn']==event['turn']:
                raise Refused('The requested command does not match the native human message; nothing was applied')
            raise Saving('Codex has not saved this human message yet; retry the same OH operation.')
        return event|{'at':min(m['at'] for m in matches if m['at']) if any(m['at'] for m in matches) else None,
            'record_hashes':sorted({h for m in matches for h in m['record_hashes']}),'transcript_path':str(path)}
    path=paths[0];matches=[];times=[];tagged=[];expanded={};latest_turn=None
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
            if prompted(x,event['session']):latest_turn=x['promptId']
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
        error=Saving if latest_turn!=event['turn'] or tagged and not expanded else Refused
        raise error('No matching native human turn is saved yet; no authority was granted. Retry OH after the host saves it.')
    if latest and latest_turn not in (None,event['turn']):raise Expired('The person typed something newer in this conversation')
    return event|{'at':min(times) if times else None,'record_hashes':sorted(set(matches)),'transcript_path':str(path)}


def claude_history(path,session):
    """Native human prompts used for conversational input; tool and agent text do not count."""
    messages=[]
    with path.open('rb') as stream:
        for line in stream:
            try:record=json.loads(line)
            except ValueError:
                if not line.endswith(b'\n'):raise Saving('Claude is still saving this conversation; retry the same OH operation.')
                continue
            if not isinstance(record,dict) or not prompted(record,session):continue
            content=(record.get('message') or {}).get('content')
            text=content if isinstance(content,str) else '\n'.join(c.get('text','') for c in content if isinstance(c,dict) and c.get('type')=='text')
            if tagged:=saved_command(text):text='/'+tagged[0]+(' '+tagged[1] if tagged[1] else '')
            messages.append({'turn':record['promptId'],'prompt':text.strip(),'cwd':record.get('cwd'),'at':record.get('timestamp')})
    return messages


def _path(host, session, supplied=None, child=False):
    from .hosts import codex_home
    home=(codex_home()/'sessions' if host=='codex' else Path.home()/'.claude/projects').resolve()
    if host not in ('codex','claude') or not re.fullmatch(r'[A-Za-z0-9_-]+',session or ''):
        raise Refused('A native host and session identity are required')
    paths=[Path(supplied).expanduser().resolve()] if supplied else list(home.rglob('*'+session+'*.jsonl'))
    paths=[p for p in paths if p.is_relative_to(home) and p.is_file()]
    if len(paths)!=1:raise Saving('The native session is not uniquely saved yet; retry this same operation')
    return paths[0]


def _records(path):
    with Path(path).open(encoding='utf-8') as stream:
        for line in stream:
            try:value=json.loads(line)
            except ValueError:
                if not line.endswith('\n'):raise Saving('The native host is still saving its evidence; retry this operation')
                continue
            if isinstance(value,dict):yield value


def native_human(root, locator, *, since=None, subject=None, latest=True):
    """Read native human provenance. latest=False identifies already-consumed sources for
    idempotent replay only; any new authority requires the default freshness check."""
    if not isinstance(locator,dict):raise Refused('Supply a native human evidence locator')
    host=locator.get('host');session=locator.get('session')
    use=locator.get('tool_use_id')
    if not use:
        if not locator.get('turn'):
            path=_path(host,session,locator.get('transcript_path'))
            messages=codex_history(path,session)[2] if host=='codex' else claude_history(path,session)
            hint=locator.get('prompt')
            matching=[m for m in messages if not hint or m['prompt']==hint.strip() or saved_command(m['prompt']) is not None and saved_command(m['prompt'])==saved_command(hint)]
            if not matching:raise Saving('The native host has not saved this human input yet; retry the same operation')
            selected=matching[-1]
            locator=locator|{'turn':selected['turn'],'prompt':selected['prompt'],'transcript_path':str(path)}
        if not isinstance(locator.get('prompt'),str):
            path=_path(host,session,locator.get('transcript_path'))
            if host=='codex':messages=codex_history(path,session)[2]
            else:messages=claude_history(path,session)
            matches=[m for m in messages if m['turn']==locator.get('turn')]
            if not matches:raise Saving('This native human turn is not saved yet')
            locator=locator|{'prompt':matches[-1]['prompt'],'transcript_path':str(path)}
        payload=dict(locator,hook_event_name='UserPromptSubmit',session_id=session,turn_id=locator.get('turn'))
        result=attest(host,payload,root,latest=latest)
        if since and not newer(result.get('at'),since):raise Refused('This human reply predates the subject it would approve')
        context='';context_at=None
        for record in _records(result['transcript_path']):
            if record.get('timestamp') and result.get('at') and not newer(result['at'],record['timestamp']):continue
            if host=='codex':
                item=record.get('payload') or {}
                if record.get('type')!='response_item' or item.get('type')!='message' or item.get('role')!='assistant':continue
                parts=item.get('content')
            else:
                if record.get('type')!='assistant' or record.get('sessionId')!=session or record.get('isSidechain'):continue
                parts=(record.get('message') or {}).get('content')
            text='\n'.join(part.get('text','') for part in parts if isinstance(part,dict) and part.get('type') in ('text','output_text')) if isinstance(parts,list) else ''
            if text:context=text;context_at=record.get('timestamp')
        if subject and str(subject) not in context:raise Refused('This typed reply has no preceding native context identifying the reviewed artifact')
        result['question']=context
        result['question_at']=context_at
        return result
    path=_path(host,session,locator.get('transcript_path'));call=None;answer=None;answered_text=None;superseded=False;inputs=[]
    for record in _records(path):
        # Supersession follows saved input order, including a human turn whose timestamp
        # is not yet saved. Tool output and notifications never supersede a human reply.
        if host=='claude' and prompted(record,session):
            inputs.append((record.get('timestamp'),None))
            if answer:superseded=True
        payload=record.get('payload') or {};text=None
        if host=='codex' and record.get('type')=='event_msg' and payload.get('thread_id',session)==session:
            if payload.get('type')=='user_message':text=payload.get('message')
            elif payload.get('type')=='item_completed':
                item=payload.get('item') or {}
                if item.get('type')=='UserMessage':
                    content=item.get('content');text=content if isinstance(content,str) else '\n'.join(c.get('text','') for c in content if isinstance(c,dict) and c.get('type')=='text') if isinstance(content,list) else None
            # Codex can save the same native reply as both user_message and UserMessage.
            if isinstance(text,str):
                inputs.append((record.get('timestamp'),text))
                if answer and text!=answered_text:superseded=True
        if since and not newer(record.get('timestamp'),since):continue
        if host=='claude':
            if record.get('sessionId')!=session or record.get('isSidechain') or record.get('isMeta'):continue
            if not within(record.get('cwd'),root):continue
            content=(record.get('message') or {}).get('content')
            if not isinstance(content,list):continue
            for part in content:
                if not isinstance(part,dict):continue
                if (record.get('type')=='assistant' and part.get('type')=='tool_use' and
                        part.get('id')==use and part.get('name') in ('AskUserQuestion','ExitPlanMode')):
                    call=(record,part)
                elif (call and not answer and record.get('type')=='user' and part.get('type')=='tool_result' and
                      part.get('tool_use_id')==use and not part.get('is_error') and human(record,menu=True)):
                    native=record.get('toolUseResult')
                    if not isinstance(native,dict):continue
                    if call[1]['name']=='ExitPlanMode':
                        if native.get('isAgent') is not False or native.get('awaitingLeaderApproval'):continue
                        text=native.get('plan');plan_path=native.get('filePath')
                        if not isinstance(text,str) or not isinstance(plan_path,str):continue
                        answer={'prompt':'approve','accepted_plan':text,'accepted_plan_path':plan_path,'via':'plan'}
                    else:
                        answers=native.get('answers')
                        if not isinstance(answers,dict) or len(answers)!=1 or not all(isinstance(v,str) for v in answers.values()):continue
                        answer={'prompt':next(iter(answers.values())),'via':'question'}
                    answer.update(host=host,session=session,turn=use,at=record.get('timestamp'),
                                  record_hashes=[digest(call[0]),digest(record)],transcript_path=str(path))
        else:
            if record.get('type')=='session_meta':
                if payload.get('id')!=session or isinstance(payload.get('source'),dict):raise Refused('A delegated session cannot grant authority')
                if not within(payload.get('cwd'),root):raise Refused('Human reply belongs to another checkout')
            if record.get('type')=='response_item' and payload.get('type')=='function_call' and payload.get('call_id')==use:
                if payload.get('name','').split('.')[-1] not in ('request_user_input','request_user_input_async','send_user_message'):continue
                call=(record,payload)
            # A function_call_output alone is model/tool text. The host's direct UserMessage is authority.
            if record.get('type')=='event_msg' and payload.get('type') in ('user_message','item_completed') and call and not answer:
                if not isinstance(text,str):continue
                wrapped=re.fullmatch(r'<send_user_message_question_reply>\s*(.*?)\s*</send_user_message_question_reply>',text,re.S)
                if not wrapped:continue
                try:replies=json.loads(wrapped[1])
                except ValueError:continue
                if len(replies)!=1 or not isinstance(replies[0],dict) or not isinstance(replies[0].get('answer'),str):continue
                try:question_tool,question_call,question_index=json.loads(replies[0].get('questionItemId',''))
                except (ValueError,TypeError):continue
                if question_call!=use or question_tool.split('.')[-1]!=call[1].get('name','').split('.')[-1] or question_index!=0:continue
                answer={'host':host,'session':session,'turn':payload.get('turn_id') or use,'prompt':replies[0]['answer'],
                        'via':'question','at':record.get('timestamp'),'record_hashes':[digest(call[0]),digest(record)],'transcript_path':str(path)}
                answered_text=text
    if not answer:raise Saving('The native human answer is not saved or was cancelled; no authority was granted')
    if latest and (superseded or any(newer(at,answer.get('at')) and (host=='claude' or text!=answered_text) for at,text in inputs)):
        raise Expired('The person supplied newer input in this conversation; the earlier native answer grants no new authority')
    request=call[1].get('input') if host=='claude' else None
    if host=='codex':
        try:request=json.loads(call[1].get('arguments','{}'))
        except ValueError:request={}
    questions=request.get('questions',[]) if isinstance(request,dict) else []
    answer['question']=(questions[0].get('question') or questions[0].get('title') or '') if questions and isinstance(questions[0],dict) else ''
    answer['question_at']=call[0].get('timestamp')
    if subject and answer.get('via')!='plan' and str(subject) not in answer['question']:
        raise Refused('This native question does not identify the reviewed artifact; ask about its actual path')
    return answer


def coordinator(root, state, locator=None):
    """Consequential helpers belong to the native parent, not an implementation/review child."""
    session=os.environ.get('CODEX_THREAD_ID') or os.environ.get('OH_NATIVE_SESSION_ID')
    if locator:
        source=native_human(root,locator)
        if session and session!=source['session']:raise Refused('The native caller cannot use another session’s human grant')
        return source
    if session and session!=state['human']['session']:
        raise Refused('Completion and decisions belong to the native owning parent session')
    session=session or state['human']['session']
    path=_path(state['host'],session,state['human'].get('transcript_path'))
    if state['host']=='codex':codex_history(path,session)
    elif '/subagents/' in str(path):raise Refused('A delegated child cannot become the owning parent')
    return state['human']


def native_child(root, state, attempt, locator):
    """Bind saved native spawn provenance and its real model/effort, without launching anything."""
    return _child(root,state,attempt,locator,binding=True)


def _child(root,state,attempt,locator,*,binding):
    """Identification may retain a failed binding; only strict validation admits its work."""
    issues=[];requested_profile=None;context={}
    def mismatch(message):
        if binding:raise Refused(message)
        issues.append(message)
    host=state['host'];child=locator.get('child_session') or locator.get('session')
    path=_path(host,child,locator.get('transcript_path'),child=True)
    profile=None;meta=None;parent=state['human']['session'];spawn=None;spawn_use=locator.get('tool_use_id')
    parent_path=_path(host,parent,state['human'].get('transcript_path'))
    child_records=list(_records(path))
    if host=='codex':
        for r in child_records:
            p=r.get('payload') or {}
            if r.get('type')=='session_meta':
                source=(p.get('source') or {})
                data=source.get('subagent',{}).get('thread_spawn',{}) if isinstance(source,dict) else {}
                if p.get('id')!=child or data.get('parent_thread_id')!=parent or p.get('model_provider')!='openai':raise Refused('Child is not a first-party native delegate of this parent')
                if not within(p.get('cwd'),root):raise Refused('Native child belongs to another checkout')
                if not newer(p.get('timestamp'),attempt['started_at']):raise Refused('The child predates this admission; launch a fresh agent')
                meta=(r,data)
            if r.get('type')=='turn_context':profile={'model':p.get('model'),'effort':p.get('effort') or p.get('reasoning_effort')}
        if not meta:raise Saving('Native child metadata is not saved yet')
        if not profile:
            if binding:raise Saving('Native child profile is not saved yet')
            issues.append('Actual native model/effort is unknown; no profile was saved.')
        name=meta[1].get('agent_path','').rsplit('/',1)[-1]
        if name!='oh_'+attempt['id'].replace('-',''):raise Refused('Native task name does not identify this immutable admission')
        for r in _records(parent_path):
            p=r.get('payload') or {}
            if r.get('type')!='response_item' or p.get('type')!='function_call' or p.get('name','').split('.')[-1]!='spawn_agent':continue
            try:args=json.loads(p.get('arguments','{}'))
            except ValueError:continue
            if args.get('task_name')==name:
                if spawn_use and p.get('call_id')!=spawn_use:continue
                requested_profile={'model':args.get('model'),'effort':args.get('reasoning_effort')}
                context={'fork_turns':args.get('fork_turns')}
                if args.get('fork_turns')!='none':mismatch('A fresh context requires fork_turns none')
                if requested_profile!=attempt['profile']:mismatch('Native spawn did not explicitly use the admitted profile')
                spawn=r;spawn_use=p.get('call_id')
        if not spawn:raise Refused('No fresh native spawn is attributable to this child')
    else:
        actual=None
        if path.parent.name!='subagents' or path.parent.parent.name!=parent:raise Refused('Child is not in this parent’s native subagents')
        for r in child_records:
            if r.get('agentId')!=child or r.get('sessionId')!=parent:continue
            if not within(r.get('cwd'),root):raise Refused('Native child belongs to another checkout')
            if r.get('type')=='assistant' and (r.get('message') or {}).get('model'):
                actual=r['message']['model'];requested=attempt['profile']['model']
                if actual!=requested and not actual.startswith('claude-'+requested+'-'):mismatch('Native child model differs from admission')
                if not newer(r.get('timestamp'),attempt['started_at']):raise Refused('The native child predates this admission')
                meta=(r,{})
            elif not meta and newer(r.get('timestamp'),attempt['started_at']):meta=(r,{})
        for r in _records(parent_path):
            for p in ((r.get('message') or {}).get('content') or []) if isinstance((r.get('message') or {}).get('content'),list) else []:
                if p.get('type')!='tool_use' or p.get('name') not in ('Agent','Task') or p.get('id')!=locator.get('tool_use_id'):continue
                args=p.get('input') or {}
                if attempt['id'] not in args.get('prompt',''):raise Refused('The native agent request does not identify its admission')
                requested_profile={'model':args.get('model'),'effort':args.get('effort')}
                context={k:args.get(k) for k in ('subagent_type','fork_context','fork_turns')}
                if requested_profile!=attempt['profile']:mismatch('Native spawn must explicitly record the admitted model and effort')
                if args.get('subagent_type')=='fork' or args.get('fork_context') or args.get('fork_turns') not in (None,'none'):mismatch('The child must start without parent history')
                spawn=r;profile={'model':actual,'effort':args.get('effort')} if actual else None
                if actual and (actual==attempt['profile']['model'] or actual.startswith('claude-'+attempt['profile']['model']+'-')):profile['model']=attempt['profile']['model']
        if not meta or not spawn:raise Saving('Native child identity or explicit spawn settings are not saved yet')
        linked=False
        for record in _records(parent_path):
            result=record.get('toolUseResult')
            parts=(record.get('message') or {}).get('content')
            if isinstance(result,dict) and result.get('agentId')==child and isinstance(parts,list) and any(isinstance(p,dict) and p.get('type')=='tool_result' and p.get('tool_use_id')==locator.get('tool_use_id') for p in parts):linked=True
        if not linked:raise Saving('The native spawn result has not attributed this child to its call yet')
    if profile is None:
        if binding:raise Saving('Native child profile is not saved yet')
        if not issues:issues.append('Actual native model/effort is unknown; no profile was saved.')
    elif profile!=attempt['profile']:mismatch('Actual native model/effort differs from the immutable admission')
    value={'child_session':child,'parent_session':parent,'transcript_path':str(path),'profile':profile,
           'tool_use_id':spawn_use,'record_hashes':[digest(meta[0]),digest(spawn)]}
    if not binding:value.update(binding_issues=issues,requested_profile=requested_profile,requested_context=context)
    return value


def native_result(root, state, attempt, locator):
    bound=attempt.get('native_child')
    if not bound:
        parent=_path(state['host'],state['human']['session'],state['human'].get('transcript_path'))
        use=locator.get('tool_use_id');launch=None;requested=None;context=None
        if not isinstance(use,str) or not use:raise Refused('A failed native launch requires its actual tool call identity')
        for record in _records(parent):
            if not newer(record.get('timestamp'),attempt['started_at']):continue
            if state['host']=='codex':
                item=record.get('payload') or {}
                if record.get('type')=='response_item' and item.get('type')=='function_call' and item.get('call_id')==use and item.get('name','').split('.')[-1]=='spawn_agent':
                    try:args=json.loads(item.get('arguments','{}'))
                    except ValueError:continue
                    if args.get('task_name')=='oh_'+attempt['id'].replace('-',''):
                        requested={'model':args.get('model'),'effort':args.get('reasoning_effort')}
                        context={'fork_turns':args.get('fork_turns')}
                        launch=record
                if launch and record.get('type')=='response_item' and item.get('type')=='function_call_output' and item.get('call_id')==use:
                    output=item.get('output','')
                    try:failure=json.loads(output) if isinstance(output,str) else output
                    except ValueError:failure=None
                    failed=(isinstance(failure,dict) and (bool(failure.get('error')) or failure.get('isError') is True or failure.get('status')=='failed') or
                            isinstance(output,str) and re.match(r'(?i)^\s*(?:error\b|failed\b|refused\b)',output))
                    if failed:
                        return {'text':output,'status':'failed','profile':None,'admitted_profile':attempt['profile'],
                                'requested_profile':requested,'requested_context':context,'record_hashes':[digest(launch),digest(record)]}
            else:
                if record.get('sessionId')!=state['human']['session'] or record.get('isSidechain'):continue
                parts=(record.get('message') or {}).get('content')
                for item in parts if isinstance(parts,list) else []:
                    if not isinstance(item,dict):continue
                    if item.get('type')=='tool_use' and item.get('id')==use and item.get('name') in ('Agent','Task') and attempt['id'] in (item.get('input') or {}).get('prompt',''):
                        args=item.get('input') or {}
                        requested={'model':args.get('model'),'effort':args.get('effort')}
                        context={k:args.get(k) for k in ('subagent_type','fork_context','fork_turns')}
                        launch=record
                    if launch and item.get('type')=='tool_result' and item.get('tool_use_id')==use and item.get('is_error'):
                        return {'text':str(item.get('content','Native launch failed')),'status':'failed','profile':None,
                                'admitted_profile':attempt['profile'],'requested_profile':requested,
                                'requested_context':context,'record_hashes':[digest(launch),digest(record)]}
        if launch and (locator.get('child_session') or locator.get('session')):
            identified=_child(root,state,attempt,locator,binding=False)
            terminal=native_result(root,state,attempt|{'native_child':identified},locator)
            return terminal|{'status':'binding_failed','terminal_status':terminal['status'],
                'tool_use_id':identified['tool_use_id'],
                'admitted_profile':attempt['profile'],'requested_profile':identified['requested_profile'],
                'requested_context':identified['requested_context'],
                'binding_issues':identified['binding_issues'] or ['Native launch was not successfully bound to its admission.'],
                'record_hashes':identified['record_hashes']+terminal['record_hashes']}
        raise Saving('No attributed native launch failure or child result is saved yet')
    if locator.get('child_session',bound['child_session'])!=bound['child_session']:raise Refused('Result belongs to a different child')
    path=_path(state['host'],bound['child_session'],bound['transcript_path'],child=True)
    final=None;terminal=None;terminal_record=None
    if state['host']=='claude':
        parent=_path('claude',bound['parent_session'],state['human'].get('transcript_path'))
        active=False
        for record in _records(parent):
            if record.get('sessionId') not in (None,bound['parent_session']) or record.get('isSidechain'):continue
            parts=(record.get('message') or {}).get('content')
            if isinstance(parts,list):
                for part in parts:
                    if not isinstance(part,dict):continue
                    if part.get('type')=='tool_use' and part.get('id')==bound.get('tool_use_id') and part.get('name') in ('Agent','Task'):
                        active=True
                    if part.get('type')=='tool_result' and part.get('tool_use_id')==bound.get('tool_use_id'):
                        result=record.get('toolUseResult') or {}
                        if not terminal and isinstance(result,dict) and result.get('agentId')==bound['child_session'] and result.get('status') in ('completed','cancelled','failed'):
                            terminal=result['status'];terminal_record=record
            if not terminal and active and record.get('type')=='system' and record.get('subtype')=='agents_killed' and record.get('sessionId')==bound['parent_session'] and newer(record.get('timestamp'),attempt['started_at']):
                terminal='cancelled';terminal_record=record
            result=record.get('toolUseResult')
            # Native child notifications can have no tool-result content. A result for another
            # call, even with a claimed child id, is not this delegate's terminal event.
            if not terminal and not isinstance(parts,list) and isinstance(result,dict) and result.get('agentId')==bound['child_session'] and result.get('status') in ('completed','cancelled','failed'):
                terminal=result['status'];terminal_record=record
    public=[];public_hashes=[]
    for r in _records(path):
        if terminal_record and r.get('timestamp') and terminal_record.get('timestamp') and newer(r['timestamp'],terminal_record['timestamp']):continue
        if state['host']=='codex':
            p=r.get('payload') or {}
            if r.get('type')=='response_item' and p.get('type')=='message' and p.get('role')=='assistant':
                text='\n'.join(part.get('text','') for part in p.get('content',[]) if isinstance(part,dict) and part.get('type') in ('text','output_text'))
                if text and text not in public:public.append(text);public_hashes.append(digest(r))
            if not final and r.get('type')=='event_msg' and p.get('type') in ('task_complete','task_completed'):
                text=p.get('last_agent_message')
                if isinstance(text,str):final={'text':text,'status':'completed','duration_ms':p.get('duration_ms'),'record_hashes':[digest(r)]}
            elif not final and r.get('type')=='event_msg' and p.get('type')=='turn_aborted':
                final={'text':'\n\n'.join(public) or p.get('reason','Native child interrupted'),'status':'interrupted','record_hashes':public_hashes+[digest(r)]}
        elif r.get('type')=='assistant' and r.get('agentId')==bound['child_session']:
            message=r.get('message') or {};parts=message.get('content')
            if isinstance(parts,list):
                text='\n'.join(p['text'] for p in parts if isinstance(p,dict) and p.get('type')=='text')
                if text and text not in public:public.append(text);public_hashes.append(digest(r))
                if text and terminal=='completed' and not any(p.get('type')=='tool_use' for p in parts if isinstance(p,dict)):
                    final={'text':text,'status':'completed','record_hashes':[digest(r),digest(terminal_record)]}
    if terminal in ('cancelled','failed'):
        error=(terminal_record.get('toolUseResult') or {})
        error=error.get('error') if isinstance(error,dict) else None
        final={'text':'\n\n'.join(public) or str(error or 'Native child '+terminal),
               'status':'interrupted' if terminal=='cancelled' else 'failed',
               'record_hashes':public_hashes+[digest(terminal_record)]}
    if not final:raise Saving('The native child has not saved a terminal public result yet')
    return final|{'profile':bound['profile'],'native_id':bound['child_session']}
