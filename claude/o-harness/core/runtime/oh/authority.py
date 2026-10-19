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
    """The saved transcript of the coordinating Claude conversation."""
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
    answer['question_options']=question_options(request)
    answer['question_at']=call[0].get('timestamp')
    if subject and answer.get('via')!='plan' and str(subject) not in answer['question']:
        raise Refused('This native question does not identify the reviewed artifact; ask about its actual path')
    return answer


def question_options(request):
    """Return a complete single-select native menu, never inferred prose choices."""
    questions=request.get('questions') if isinstance(request,dict) else None
    if not isinstance(questions,list) or len(questions)!=1 or not isinstance(questions[0],dict):return None
    question=questions[0]
    if question.get('multiSelect',False) is not False:return None
    options=question.get('options')
    if not isinstance(options,list) or not options:return None
    labels=[option.get('label') if isinstance(option,dict) else option for option in options]
    if any(not isinstance(label,str) or not label for label in labels) or len(set(labels))!=len(labels):return None
    return labels


def question_calls(root, host, session, question, supplied=None, *, options=None):
    """List native calls showing this prepared text or its complete checkpoint menu.
    Locating a call grants nothing; native_human still validates its saved answer."""
    path=_path(host,session,supplied);calls=[]
    def matches(arguments):
        if options is not None:
            shown=question_options(arguments)
            return shown is not None and set(shown)==set(options)
        questions=arguments.get('questions') if isinstance(arguments,dict) else None
        return isinstance(questions,list) and questions and isinstance(questions[0],dict) and (questions[0].get('question') or questions[0].get('title'))==question
    for record in _records(path):
        if host=='claude':
            if record.get('type')!='assistant' or record.get('sessionId')!=session or record.get('isSidechain') or not within(record.get('cwd'),root):continue
            content=(record.get('message') or {}).get('content')
            for part in content if isinstance(content,list) else []:
                if isinstance(part,dict) and part.get('type')=='tool_use' and part.get('name')=='AskUserQuestion':
                    if matches(part.get('input')):calls.append(part.get('id'))
        else:
            payload=record.get('payload') or {}
            if record.get('type')!='response_item' or payload.get('type')!='function_call':continue
            if payload.get('name','').split('.')[-1] not in ('request_user_input','request_user_input_async','send_user_message'):continue
            try:arguments=json.loads(payload.get('arguments','{}'))
            except ValueError:continue
            if matches(arguments):calls.append(payload.get('call_id'))
    return path,[call for call in calls if isinstance(call,str) and call]


def coordinator(root, state, locator=None):
    """Consequential helpers belong to the native parent, not an implementation/review child."""
    session=os.environ.get('CODEX_THREAD_ID') or os.environ.get('OH_NATIVE_SESSION_ID')
    if locator:
        source=native_human(root,locator)
        if session and session!=source['session']:raise Refused('The native caller cannot use another session’s human grant')
        return source
    if session and session!=state['human']['session']:
        raise Refused('This coordinator was superseded; continue from the current native parent or use a new explicit matching work command')
    session=session or state['human']['session']
    path=_path(state['host'],session,state['human'].get('transcript_path'))
    if state['host']=='codex':codex_history(path,session)
    elif '/subagents/' in str(path):raise Refused('A delegated child cannot become the owning parent')
    return state['human']


def native_child(root, state, attempt, locator):
    """Bind saved native spawn provenance and its real model/effort, without launching anything."""
    return saved(lambda: _child(root,state,attempt,locator,binding=True))


def _attempt_parent(state,attempt):
    # Historical attempts keep the host/parent in effect at admission, even after
    # another native conversation continues the durable work.
    return state|{'host':attempt.get('host',state['host']),'human':attempt.get('parent',state['human'])}


def _claude_spawn_use(path,parent,child):
    """Recover only a unique native launch-result identity, never agent prose."""
    uses=set()
    for record in _records(path):
        result=record.get('toolUseResult');parts=(record.get('message') or {}).get('content')
        if (record.get('type')!='user' or record.get('sessionId')!=parent or record.get('isSidechain')
                or not isinstance(result,dict) or result.get('agentId')!=child or result.get('isAsync') is not True
                or result.get('status')!='async_launched' or not isinstance(parts,list)):continue
        uses.update(p['tool_use_id'] for p in parts if isinstance(p,dict) and p.get('type')=='tool_result'
                    and not p.get('is_error') and isinstance(p.get('tool_use_id'),str) and p['tool_use_id'])
    if len(uses)==1:return uses.pop()
    raise Saving('Provide the original native spawn-call identity; no unique launch result is saved for this child')


def _child(root,state,attempt,locator,*,binding):
    """Identification may retain a failed binding; only strict validation admits its work."""
    state=_attempt_parent(state,attempt)
    issues=[];requested_profile=None;context={}
    def mismatch(message):
        if binding:raise Refused(message+'; cancel or await this child, then retain its terminal result with the original child and spawn identities before launching the admitted profile')
        if message not in issues:issues.append(message)
    host=state['host'];child=locator.get('child_session') or locator.get('session')
    if not isinstance(child,str) or not re.fullmatch(r'[A-Za-z0-9_-]+',child):raise Refused('A native child identity is required')
    profile=None;meta=None;parent=state['human']['session'];spawn=None;spawn_use=locator.get('tool_use_id')
    parent_path=_path(host,parent,state['human'].get('transcript_path'))
    supplied=locator.get('transcript_path')
    if host=='claude':
        if parent_path.stem!=parent:raise Refused('The saved parent transcript does not match its native session identity')
        if not spawn_use:spawn_use=_claude_spawn_use(parent_path,parent,child)
        expected=(parent_path.parent/parent/'subagents'/('agent-'+str(child)+'.jsonl')).resolve()
        if supplied and Path(supplied).expanduser().resolve() not in (parent_path,expected):
            raise Refused('The supplied child transcript is neither this native child nor its known parent')
        # Native Agent results identify the child. A parent-transcript hint is a
        # routine locator mistake, not a reason to launch or charge another agent.
        supplied=str(expected)
    # Claude can stop an attributed background launch before creating its file.
    # The parent call/result can identify that failed attempt, never its profile.
    missing=host=='claude' and not binding and not expected.exists()
    path=expected if missing else _path(host,child,supplied,child=True)
    child_records=[] if missing else list(_records(path))
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
            if r.get('sessionId') not in (None,parent) or r.get('isSidechain'):continue
            for p in ((r.get('message') or {}).get('content') or []) if isinstance((r.get('message') or {}).get('content'),list) else []:
                if p.get('type')!='tool_use' or p.get('name') not in ('Agent','Task') or p.get('id')!=spawn_use:continue
                args=p.get('input')
                if not isinstance(args,dict):raise Refused('The native spawn settings are not an input object')
                if attempt['id'] not in args.get('prompt',''):raise Refused('The native agent request does not identify its admission')
                requested_profile={'model':args.get('model'),'effort':args.get('effort')}
                context={k:args.get(k) for k in ('subagent_type','fork_context','fork_turns')}
                if requested_profile!=attempt['profile']:mismatch('Native spawn must explicitly record the admitted model and effort')
                if args.get('subagent_type')=='fork' or args.get('fork_context') or args.get('fork_turns') not in (None,'none'):mismatch('The child must start without parent history')
                spawn=r;profile={'model':actual,'effort':args.get('effort')} if actual else None
                if actual and (actual==attempt['profile']['model'] or actual.startswith('claude-'+attempt['profile']['model']+'-')):profile['model']=attempt['profile']['model']
        if not spawn:raise Saving('Native child identity or explicit spawn settings are not saved yet')
        linked=False
        for record in _records(parent_path):
            if record.get('sessionId') not in (None,parent) or record.get('isSidechain'):continue
            result=record.get('toolUseResult')
            parts=(record.get('message') or {}).get('content')
            if (record.get('type')=='user' and isinstance(result,dict) and result.get('agentId')==child and isinstance(parts,list)
                    and any(isinstance(p,dict) and p.get('type')=='tool_result' and p.get('tool_use_id')==spawn_use and not p.get('is_error') for p in parts)):
                linked=True
                if not meta and not binding and newer(record.get('timestamp'),attempt['started_at']):meta=(record,{})
        if not linked:raise Saving('The native spawn result has not attributed this child to its call yet')
        if not meta:raise Saving('Native child identity is not saved yet')
    if profile is None:
        if binding:raise Saving('Native child profile is not saved yet')
        if not issues:issues.append('Actual native model/effort is unknown; no profile was saved.')
    elif profile!=attempt['profile']:mismatch('Actual native model/effort differs from the immutable admission')
    value={'child_session':child,'parent_session':parent,'transcript_path':str(path),'profile':profile,
           'tool_use_id':spawn_use,'record_hashes':[digest(meta[0]),digest(spawn)]}
    if not binding:value.update(binding_issues=issues,requested_profile=requested_profile,requested_context=context)
    return value


def _claude_handback(root,attempt,bound,records,forwarded,completion=None):
    """Return the acknowledged handback and whether all owned tools have settled."""
    pending={};background=set();unknown=False;final=None
    for record in records:
        if (record.get('agentId'),record.get('sessionId'))!=(bound['child_session'],bound['parent_session']):continue
        # A background command is quiescent once the child's own record carries its native
        # terminal notification; a bare start acknowledgement is not that.
        attached=record.get('attachment') if record.get('type')=='attachment' else None
        if isinstance(attached,dict) and attached.get('type')=='queued_command' and isinstance(attached.get('prompt'),str):
            done=re.search(r'<tool-use-id>([^<\s]+)</tool-use-id>\s*<output-file>[^<]*</output-file>\s*<status>(completed|failed|killed)</status>',attached['prompt'])
            if done:background.discard(done[1])
        done=_claude_notification(record,delivered=True)
        if done:background.discard(done['use'])
        parts=(record.get('message') or {}).get('content')
        if record.get('type') not in ('assistant','user'):continue
        # Further child activity invalidates an earlier handback as quiescence.
        final=None
        if not isinstance(parts,list):continue
        for part in parts:
            if not isinstance(part,dict):continue
            if record['type']=='assistant' and part.get('type')=='tool_use':
                use=part.get('id')
                if not isinstance(use,str) or not use or use in pending:unknown=True;continue
                pending[use]=(record,part)
                payload=part.get('input')
                if not isinstance(payload,dict):unknown=True;continue
                if payload.get('run_in_background'):background.add(use)
            elif record['type']=='user' and part.get('type')=='tool_result':
                call=pending.pop(part.get('tool_use_id'),None)
                if not call:continue
                # A native failed/rejected invocation did not acknowledge a
                # background start. It cannot owe a later completion notice.
                if part.get('is_error') is True:background.discard(part['tool_use_id'])
                request,tool=call;payload=tool.get('input');caller=tool.get('caller')
                if not isinstance(payload,dict) or not isinstance(caller,dict):continue
                text=payload.get('message')
                if tool.get('name')!='SubagentHandback' or caller.get('type')!='direct' or not isinstance(text,str) or not text:continue
                if pending or background or unknown or record.get('toolEndsTurn') is not True or part.get('is_error'):continue
                if not request.get('uuid') or record.get('parentUuid')!=request['uuid'] or record.get('sourceToolAssistantUUID')!=request['uuid']:continue
                if not within(request.get('cwd'),root) or not within(record.get('cwd'),root):continue
                if not newer(request.get('timestamp'),attempt['started_at']) or not newer(record.get('timestamp'),attempt['started_at']) or newer(request.get('timestamp'),record.get('timestamp')):continue
                permission=record.get('permissionDecision')
                if permission is not None and (not isinstance(permission,dict) or permission.get('decision') not in (None,'accept')):continue
                content=part.get('content')
                if not isinstance(content,list) or any(not isinstance(p,dict) or p.get('type')!='text' or not isinstance(p.get('text'),str) for p in content):continue
                try:ack=json.loads(''.join(p['text'] for p in content))
                except ValueError:continue
                if not isinstance(ack,dict) or ack.get('success') is not True:continue
                # Claude may prefix a native warning and indent every report line.
                # Match only that lossless envelope; never parse its warning prose.
                indented='\n'+'\n'.join('  '+line for line in text.split('\n'))
                notice=next((r for r in forwarded if isinstance(r['origin'].get('body'),str)
                             and (r['origin']['body']==text or r['origin']['body'].endswith(indented))
                             and newer(r.get('timestamp'),attempt['started_at']) and not newer(request.get('timestamp'),r.get('timestamp'))),None)
                # Synchronous Agent results retain the report even when Claude absorbs
                # its peer notification into the parent's current turn. Use that exact
                # native call's payload, matched to the acknowledged child handback.
                if not notice and completion:
                    result=completion.get('toolUseResult') or {}
                    report=result.get('handbackReport') if isinstance(result,dict) else None
                    parts=(completion.get('message') or {}).get('content')
                    if (completion.get('type')=='user' and completion.get('sessionId')==bound['parent_session']
                            and not completion.get('isSidechain') and isinstance(result,dict) and result.get('status')=='completed'
                            and result.get('agentId')==bound['child_session'] and isinstance(report,dict)
                            and report.get('text')==text and isinstance(parts,list)
                            and any(isinstance(p,dict) and p.get('type')=='tool_result'
                                    and p.get('tool_use_id')==bound['tool_use_id'] and not p.get('is_error') for p in parts)
                            and newer(completion.get('timestamp'),attempt['started_at'])
                            and not newer(record.get('timestamp'),completion.get('timestamp'))):notice=completion
                    # Background completion may be absorbed into a native task
                    # notification instead of forwarding the report to the parent.
                    notification=_claude_notification(completion)
                    if (notification and notification['status']=='completed'
                            and not newer(record.get('timestamp'),notification['at'])):notice=completion
                if notice:final={'text':text,'status':'completed','record_hashes':[digest(request),digest(record),digest(notice)]}
    settled=not pending and not background and not unknown
    return (final if settled else None),settled


def _claude_notification(record,*,delivered=False):
    """Read only native task envelopes, never task-looking model or user prose."""
    text=None;at=record.get('timestamp')
    if record.get('type')=='queue-operation' and record.get('operation')=='enqueue':
        text=record.get('content')
    elif record.get('type')=='attachment':
        attachment=record.get('attachment')
        if (isinstance(attachment,dict) and attachment.get('type')=='queued_command'
                and attachment.get('commandMode')=='task-notification'
                and attachment.get('origin')=={'kind':'task-notification','producer':'session-task'}):
            text=attachment.get('prompt');at=attachment.get('timestamp')
    elif (delivered and record.get('type')=='user' and record.get('isMeta') is True
          and record.get('origin')=={'kind':'task-notification','producer':'session-task'}):
        text=(record.get('message') or {}).get('content')
        # Only child-tool settlement uses delivered notices: parent delivery can
        # lag the enqueue timestamp across a subsequent agent resume.
        # Native delivery prefixes its envelope with a human-authority warning.
        # Only the first envelope's leading fields are read, never report tags.
        if isinstance(text,str):
            _,marker,body=text.partition('<task-notification>')
            text=marker+body
    if not isinstance(text,str):return None
    # Only the leading native fields are identities. Reports/summaries may contain tags.
    match=re.match(r'\A<task-notification>\s*<task-id>([^<>]+)</task-id>\s*'
                   r'(?:<tool-use-id>([^<>]+)</tool-use-id>\s*)?'
                   r'(?:<output-file>[^<>]*</output-file>\s*)?'
                   r'<status>(completed|killed|cancelled|failed)</status>',text)
    if not match:return None
    return {'child':match[1],'use':match[2],'status':'cancelled' if match[3]=='killed' else match[3],'at':at}


def _claude_terminal(attempt,bound,records):
    """Follow the attributed child's latest lifecycle, including native stop and resume."""
    terminal=None;status=None;forwarded=[];calls={};resumes={};active_use=bound['tool_use_id'];active_at=attempt['started_at']
    for record in records:
        if record.get('sessionId') not in (None,bound['parent_session']) or record.get('isSidechain'):continue
        parts=(record.get('message') or {}).get('content');result=record.get('toolUseResult')
        origin=record.get('origin')
        if (record.get('type')=='user' and record.get('sessionId')==bound['parent_session'] and record.get('isMeta') is True
                and record.get('promptSource')=='system' and record.get('turnOrigin')=='peer' and isinstance(origin,dict)
                and origin.get('kind')=='peer' and origin.get('from')==bound['child_session']
                and origin.get('senderTaskId')==bound['child_session'] and origin.get('handback') is True):forwarded.append(record)
        for part in parts if isinstance(parts,list) else []:
            if not isinstance(part,dict):continue
            args=part.get('input')
            if record.get('type')=='assistant' and part.get('type')=='tool_use' and isinstance(args,dict):
                calls[part.get('id')]=(record,part)
                resume=(part.get('name') in ('Agent','Task') and args.get('resume')==bound['child_session'] or
                        part.get('name')=='SendMessage' and (args.get('to') or args.get('recipient'))==bound['child_session'])
                if resume:
                    resumes[part.get('id')]=(status,terminal,forwarded,active_at,active_use)
                    terminal=None;status=None;forwarded=[];active_at=record.get('timestamp');active_use=part.get('id')
            if (record.get('type')!='user' or record.get('sessionId')!=bound['parent_session']
                    or part.get('type')!='tool_result'):continue
            use=part.get('tool_use_id');call=calls.get(use)
            if part.get('is_error') or isinstance(result,dict) and (result.get('success') is False or result.get('error')):
                if use==active_use and use in resumes:status,terminal,forwarded,active_at,active_use=resumes[use]
                continue
            if not isinstance(result,dict):continue
            if call:
                request,tool=call;args=tool['input']
                if (tool.get('name')=='TaskStop' and args.get('task_id')==bound['child_session']
                        and result.get('task_id')==bound['child_session'] and result.get('task_type')=='local_agent'
                        and not result.get('error') and result.get('success') is not False
                        and newer(request.get('timestamp'),attempt['started_at'])
                        and newer(record.get('timestamp'),attempt['started_at'])
                        and not newer(active_at,request.get('timestamp'))
                        and not newer(request.get('timestamp'),record.get('timestamp'))):
                    status='cancelled';terminal=record
            if (use==active_use and result.get('agentId')==bound['child_session'] and result.get('status') in ('completed','cancelled','failed')
                    and newer(record.get('timestamp'),attempt['started_at']) and not newer(active_at,record.get('timestamp'))):
                if status!=result['status']:status=result['status'];terminal=record
        if (not terminal and record.get('type')=='system' and record.get('subtype')=='agents_killed'
                and record.get('sessionId')==bound['parent_session'] and newer(record.get('timestamp'),active_at)):
            status='cancelled';terminal=record
        if not isinstance(parts,list) and isinstance(result,dict) and result.get('agentId')==bound['child_session'] and result.get('status') in ('completed','cancelled','failed'):
            if newer(record.get('timestamp'),active_at) and status!=result['status']:status=result['status'];terminal=record
        notification=_claude_notification(record)
        if (record.get('sessionId')==bound['parent_session'] and notification and notification['child']==bound['child_session']
                # Later native stops may omit the call ID. The immutable spawn
                # already binds this parent/child; an explicit foreign ID still fails.
                and notification['use'] in (None,active_use) and newer(notification['at'],active_at)
                and (not terminal or not newer(terminal.get('timestamp'),notification['at']))):
            if status!=notification['status'] or newer(notification['at'],terminal.get('timestamp')):
                status=notification['status'];terminal=record
    return status,terminal,forwarded,active_at


def native_result(root, state, attempt, locator):
    return saved(lambda: _native_result(root,state,attempt,locator))


def _native_result(root, state, attempt, locator):
    state=_attempt_parent(state,attempt)
    bound=attempt.get('native_child')
    if not bound:
        parent=_path(state['host'],state['human']['session'],state['human'].get('transcript_path'))
        use=locator.get('tool_use_id');launch=None;requested=None;context=None
        if not use and state['host']=='claude' and locator.get('child_session'):
            use=_claude_spawn_use(parent,state['human']['session'],locator['child_session'])
            locator=locator|{'tool_use_id':use}
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
            terminal=_native_result(root,state,attempt|{'native_child':identified},locator)
            return terminal|{'status':'binding_failed','terminal_status':terminal['status'],
                'tool_use_id':identified['tool_use_id'],
                'admitted_profile':attempt['profile'],'requested_profile':identified['requested_profile'],
                'requested_context':identified['requested_context'],
                'binding_issues':identified['binding_issues'] or ['Native launch was not successfully bound to its admission.'],
                'record_hashes':identified['record_hashes']+terminal['record_hashes']}
        raise Saving('No attributed native launch failure or child result is saved yet')
    if locator.get('child_session',bound['child_session'])!=bound['child_session']:raise Refused('Result belongs to a different child')
    missing=state['host']=='claude' and bound['profile'] is None and not Path(bound['transcript_path']).exists()
    path=Path(bound['transcript_path']) if missing else _path(state['host'],bound['child_session'],bound['transcript_path'],child=True)
    final=None;terminal=None;terminal_record=None;forwarded=[];active_at=attempt['started_at']
    if state['host']=='claude':
        parent=_path('claude',bound['parent_session'],state['human'].get('transcript_path'))
        terminal,terminal_record,forwarded,active_at=_claude_terminal(attempt,bound,_records(parent))
    public=[];public_hashes=[];child_records=[] if missing else list(_records(path))
    if state['host']=='claude':
        # Desktop Stop can save only a child interruption and its native sidecar,
        # with no TaskStop or completion event in the old parent conversation.
        meta_path=path.with_suffix('.meta.json')
        try:stop_meta=read_json(meta_path)
        except (OSError,ValueError):stop_meta=None
        if (isinstance(stop_meta,dict) and stop_meta.get('stoppedByUser') is True
                and stop_meta.get('toolUseId')==bound['tool_use_id']):
            for record in child_records:
                if (record.get('type')=='user' and record.get('isSidechain') is True
                        and (record.get('agentId'),record.get('sessionId'))==(bound['child_session'],bound['parent_session'])
                        and within(record.get('cwd'),root)
                        and (record.get('message') or {}).get('content')==[{'type':'text','text':'[Request interrupted by user]'}]
                        and newer(record.get('timestamp'),active_at)
                        and (not terminal_record or newer(record.get('timestamp'),terminal_record.get('timestamp')))):
                    terminal='cancelled';terminal_record=record
            if terminal_record in child_records:public_hashes.append(digest(stop_meta))
    for r in child_records:
        if state['host']=='claude' and (r.get('agentId'),r.get('sessionId'))!=(bound['child_session'],bound['parent_session']):continue
        if terminal_record and newer(r.get('timestamp'),terminal_record.get('timestamp')) and r.get('type') in ('assistant','user'):
            # TaskStop can save its acknowledgement just before the child's
            # interruption marker. Any actual later work invalidates that stop.
            parts=(r.get('message') or {}).get('content')
            if r.get('type')=='user' and parts==[{'type':'text','text':'[Request interrupted by user]'}]:continue
            raise Saving('The native child has later activity; await or cancel it, then retry retention with its original locator')
        if state['host']=='codex':
            p=r.get('payload') or {}
            if (r.get('type')=='turn_context' or r.get('type')=='event_msg' and p.get('type') in ('task_started','user_message')
                    or r.get('type')=='response_item' and p.get('type') in ('message','function_call','custom_tool_call')):final=None
            if r.get('type')=='response_item' and p.get('type')=='message' and p.get('role')=='assistant':
                text='\n'.join(part.get('text','') for part in p.get('content',[]) if isinstance(part,dict) and part.get('type') in ('text','output_text'))
                if text and text not in public:public.append(text);public_hashes.append(digest(r))
            if r.get('type')=='event_msg' and p.get('type') in ('task_complete','task_completed'):
                text=p.get('last_agent_message')
                final={'text':text if isinstance(text,str) and text.strip() else '\n\n'.join(public),
                       'status':'completed' if isinstance(text,str) and text.strip() else 'unfinished',
                       'duration_ms':p.get('duration_ms'),'record_hashes':public_hashes+[digest(r)]}
            elif r.get('type')=='event_msg' and p.get('type')=='turn_aborted':
                final={'text':'\n\n'.join(public) or p.get('reason','Native child interrupted'),'status':'interrupted','record_hashes':public_hashes+[digest(r)]}
        elif r.get('type')=='assistant' and r.get('agentId')==bound['child_session']:
            # Earlier progress text is not the final report after another child action.
            final=None
            message=r.get('message') or {};parts=message.get('content')
            if isinstance(parts,list):
                text='\n'.join(p['text'] for p in parts if isinstance(p,dict) and p.get('type')=='text')
                if text and text not in public:public.append(text);public_hashes.append(digest(r))
                if (text and terminal=='completed' and not newer(active_at,r.get('timestamp'))
                        and not any(p.get('type')=='tool_use' for p in parts if isinstance(p,dict))):
                    final={'text':text,'status':'completed','record_hashes':[digest(r),digest(terminal_record)]}
    if terminal in ('cancelled','failed'):
        error=(terminal_record.get('toolUseResult') or {})
        error=error.get('error') if isinstance(error,dict) else None
        final={'text':'\n\n'.join(public) or str(error or 'Native child '+terminal),
               'status':'interrupted' if terminal=='cancelled' else 'failed',
               'record_hashes':public_hashes+[digest(terminal_record)]}
    if state['host']=='claude' and terminal not in ('cancelled','failed'):
        report,settled=_claude_handback(root,attempt|{'started_at':active_at},bound,child_records,forwarded,terminal_record if terminal=='completed' else None)
        # A native completed notice can be interim while the child awaits its
        # own background tools. Neither plain text nor an empty report settles it.
        if terminal=='completed' and not settled:
            raise Saving('The native child still has unsettled tool work; await its final completion, then retry retention with the original locator')
        if not final:final=report
        handback=any(p.get('name')=='SubagentHandback' for r in child_records
                     for p in ((r.get('message') or {}).get('content') or []) if isinstance(p,dict))
        result=(terminal_record or {}).get('toolUseResult')
        if not final and terminal=='completed' and not handback and not (isinstance(result,dict) and result.get('handbackReport')):
            final={'text':'\n\n'.join(public),'status':'unfinished','record_hashes':public_hashes+[digest(terminal_record)]}
    if not final:raise Saving("OH could not yet verify the native child's terminal result; await or cancel the child through its host, then retry retention with the original child and spawn identities")
    return final|{'profile':bound['profile'],'native_id':bound['child_session']}
