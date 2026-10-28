"""Native interruption records and owned command cleanup; no agent runner or grants.

The host still executes and approves every tool. This module can only revoke work.
Resume authority remains in native.decision. Old attempts retain their revocation
when the same conversation receives a new owner epoch.
"""
from contextlib import contextmanager
from contextvars import ContextVar
import json
import os
from .system import Path
import shlex
import sys
from .storage import Refused, atomic_json, checkout_file, digest, identifier, lock, now, read_json, state_home

_execution = ContextVar('oh_execution', default=None)
_hook_checkout = ContextVar('oh_hook_checkout', default=None)


def _path(root):
    bound=_hook_checkout.get()
    if bound and Path(root)==bound[0]:return bound[1]
    return checkout_file(root, 'oh-native-execution.json')


@contextmanager
def _edit(root):
    with lock(_path(root).with_suffix('.lock')):
        path = _path(root)
        value = read_json(path) if path.exists() else {'owners': {}, 'attempts': {}, 'tools': {}, 'commands': {}}
        before = digest(value) if path.exists() else None
        yield value
        if digest(value) != before:
            atomic_json(path, value)


def _read(root):
    path = _path(root)
    return read_json(path) if path.exists() else None


def owner_key(state):
    human=state['human']
    return digest({'run': state['id'], **{k: human.get(k) for k in ('host', 'session', 'turn', 'prompt')},
                   **({'message_id':human['message_id']} if human.get('message_id') else {})})


def register_owner(root, state, *, active=True):
    key = owner_key(state)
    with _edit(root) as value:
        if active:
            value['current'] = key
        value['owners'].setdefault(key, {
            'run': state['id'], 'host': state['human']['host'], 'session': state['human']['session'],
            'turns': [state['human']['turn']] if state['human'].get('turn') else [],
            'transcript': state['human'].get('transcript_path'),
            'since': state['human'].get('at'), 'offset': 0,
            'marker': str(Path(state['journal']) / 'interruptions' / (key + '.json'))
            if state.get('journal') else str(_path(root).parent / 'interruptions' / (key + '.json')),
        })
    return key


def register_attempt(root, state, attempt):
    key = register_owner(root, state)
    with _edit(root) as value:
        value['attempts'].setdefault(attempt['id'], {
            'owner': key, 'directory': attempt['evidence'], 'child': None,
            'finished': False, 'launch': None, 'verified': False,
        })


def bind(root, attempt, child):
    with _edit(root) as value:
        record = value['attempts'].get(attempt['id'])
        if record is None:
            return  # Historical admissions retain their original recovery contract.
        if record['child'] not in (None, child):
            raise Refused('Native interruption binding cannot change children')
        record['child'] = child
        record['verified'] = True
        if record.get('launch') in value['tools']:
            value['tools'][record['launch']]['ended'] = now()


def marker(root, attempt=None, state=None):
    value = _read(root)
    if not value:
        return None
    key = value['attempts'].get(attempt, {}).get('owner') if attempt else owner_key(state)
    owner = value['owners'].get(key)
    return Path(owner['marker']) if owner else None


def interrupted(root, attempt=None, state=None):
    poll(root, attempt=attempt, state=state)
    path = marker(root, attempt, state)
    return read_json(path) if path and path.exists() else None


def guard(root, *, attempt=None, state=None):
    if poll(root, attempt=attempt, state=state) is False:
        raise Refused('Native interruption evidence is still being saved or read. Retry this same operation; no new approval is needed.')
    if interrupted(root, attempt, state):
        raise Refused('Native Stop ended this work. Preserve its edits and use the existing Resume question to continue.')


def _record_stop(owner, turn, record):
    path = Path(owner['marker'])
    observed = path.parent / path.stem / (digest([turn, record['event']]) + '.json')
    native_record = path.parent / path.stem / (digest([turn, 'native-interruption']) + '.json')
    if record['event'] == 'Interrupt' and native_record.exists():
        return  # A delayed callback must not replace the native occurrence time.
    if not observed.exists():
        atomic_json(observed, record, immutable=True)
        previous = read_json(path) if path.exists() else None
        from .authority import newer
        resolved_callback = (previous and previous['turn'] == turn and previous['event'] == 'Interrupt'
                             and record['event'] == 'native-interruption')
        if previous is None or resolved_callback or newer(record.get('at'), previous.get('at')):
            atomic_json(path, record)


def _turn_stopped(owner, turn):
    """Observed owner turns include recovery turns; only an actual Stop revokes a turn."""
    path = Path(owner['marker'])
    if path.exists():
        record = read_json(path)
        if record.get('event') != 'recovery' and record.get('turn') == turn:
            return True
    return any((path.parent / path.stem / (digest([turn, event]) + '.json')).exists()
               for event in ('Interrupt', 'native-interruption'))


def poll(root, *, attempt=None, state=None):
    """Recover a missing callback from native interruption records, never a status label.

    Claude has no user-interrupt Stop hook. Commands and tool boundaries inspect the
    attributed parent's newly saved records. The cursor is bounded and kept outside
    the checkout; partial lines never become evidence.
    """
    value = _read(root)
    if not value:
        return True
    key = value['attempts'].get(attempt, {}).get('owner') if attempt else owner_key(state) if state else value.get('current')
    owner = value['owners'].get(key)
    if not owner or not owner.get('transcript'):
        return True
    with _edit(root) as value:
        owner = value['owners'].get(key)
        return _scan(owner, lambda turn, record: _record_stop(owner, turn, record))


def _scan(owner, stopped):
    """Read incremental native records; the caller chooses durable or local observation."""
    if not owner or not owner.get('transcript'):
        return True
    path = Path(owner['transcript'])
    try:
        size = path.stat().st_size
    except FileNotFoundError:
        return False
    if size == owner.get('offset', 0):
        return True
    from .authority import newer, _claude_interruption
    offset = owner.get('offset', 0)
    if size < offset:
        offset = 0
        owner.pop('skipping_record', None)
    with path.open('rb') as stream:
        stream.seek(offset)
        scanned = 0
        while scanned < 1024 * 1024:
            line = stream.readline(1024 * 1024)
            if not line:
                break
            scanned += len(line)
            if not line.endswith(b'\n'):
                if len(line) == 1024 * 1024:
                    owner['offset'] = stream.tell()
                    owner['skipping_record'] = True
                break
            owner['offset'] = stream.tell()
            if owner.pop('skipping_record', False):
                continue
            try:
                record = json.loads(line)
            except (ValueError, UnicodeError):
                continue
            if not isinstance(record, dict) or not newer(record.get('timestamp'), owner.get('since')):
                continue
            payload = record.get('payload')
            payload = payload if isinstance(payload, dict) else {}
            codex = (owner['host'] == 'codex' and record.get('type') == 'event_msg'
                     and payload.get('type') == 'turn_aborted' and payload.get('reason') == 'interrupted')
            claude = (owner['host'] == 'claude' and record.get('sessionId') == owner['session']
                      and not record.get('isSidechain') and _claude_interruption(record))
            if codex or claude:
                turn = payload.get('turn_id') if codex else record.get('uuid') or digest(record)
                if turn:
                    stopped(turn, {'host': owner['host'], 'session': owner['session'],
                        'turn': turn, 'at': record['timestamp'], 'event': 'native-interruption',
                        'record_hash': digest(record)})
    return owner.get('offset', 0) >= size


def observe(context):
    """Command waiters only read durable state; their host sandbox is unchanged."""
    owner = context['owner']
    marker_path = Path(owner['marker'])
    def seen(turn, record):
        owner['observed_stop'] = record
    caught_up = _scan(owner, seen)
    return caught_up, marker_path.exists() or bool(owner.get('observed_stop'))


@contextmanager
def _read_control(root):
    # Exclusive locking an existing read handle serializes claims with Stop/Resume
    # without granting the shell write access to the durable control index.
    from .system import lock_file, unlock_file
    with checkout_file(root, 'oh-native-execution.lock').open('rb') as stream:
        lock_file(stream.fileno())
        try:
            yield _read(root)
        finally:
            unlock_file(stream.fileno())


def finished(root, attempt):
    with _edit(root) as value:
        if attempt in value['attempts']:
            value['attempts'][attempt]['finished'] = True


def _actor(value, host, payload):
    session, child = payload.get('session_id'), payload.get('agent_id')
    for attempt, record in value['attempts'].items():
        owner = value['owners'][record['owner']]
        if owner['host'] == host and record['child'] and record['child'] in (child, session):
            return attempt
    return None


def command_prefix(root, attempt):
    from .config import HOME
    return [sys.executable, '-I', *(['-X', 'utf8'] if os.name == 'nt' else []),
            str(HOME / 'oh'), '--data-home', str(state_home()),
            '--root', str(Path(root).resolve()),
            'owned-command', attempt, '--argv']


def shell_line(words, *, windows=False):
    """Literal helper invocation for the selected shell, independent of host OS."""
    if windows:
        import subprocess
        quote=lambda value:"'"+value.replace("'","''")+"'"
        # Windows PowerShell strips embedded quotes from direct native arguments.
        # Start-Process forwards this single, Windows-quoted argument string on
        # both PowerShell versions, without changing permissions or interpreting it.
        return ('exit (Start-Process -FilePath '+quote(words[0])+' -ArgumentList '
                +quote(subprocess.list2cmdline(words[1:]))+' -NoNewWindow -Wait -PassThru -ErrorAction Stop).ExitCode')
    return shlex.join(words)


def command_line(root, attempt, argv, *, windows=False):
    return shell_line(command_prefix(root, attempt) + [json.dumps(argv, ensure_ascii=False)], windows=windows)


def _shell_guidance(words, host, name):
    if name == 'PowerShell':return 'PowerShell: ' + shell_line(words, windows=True)
    if host == 'claude' or os.name != 'nt':return 'Bash: ' + shell_line(words)
    # Codex may call its Windows shell tool Bash even when it executes PowerShell.
    # Its callback does not reliably identify the selected shell. Label both forms.
    return 'Bash: ' + shell_line(words) + '\nPowerShell: ' + shell_line(words, windows=True)


def _literal_words(command):
    """Accept literal invocations only, never shell operators outside argv data."""
    try:
        words = shlex.split(command)
        if shlex.join(words) == command:
            return words
    except ValueError:
        pass
    # PowerShell's quoted native invocation, with its explicit exit-code propagation.
    import re
    process=re.fullmatch(r"exit \(Start-Process -FilePath '((?:[^']|'')*)' -ArgumentList '((?:[^']|'')*)' -NoNewWindow -Wait -PassThru -ErrorAction Stop\)\.ExitCode",command,re.S)
    if process:
        from .system import windows_command_words
        import subprocess
        program,arguments=(part.replace("''", "'") for part in process.groups())
        words=windows_command_words(subprocess.list2cmdline([program])+' '+arguments)
        # Accept the exact literal renderer, not additional switches or shell code.
        return words if words and shell_line(words,windows=True)==command else None
    if command.startswith('& ') and command.endswith('; exit $LASTEXITCODE'):
        body = command[2:-len('; exit $LASTEXITCODE')]
        matches = list(re.finditer(r"'((?:[^']|'')*)'(?: |$)", body))
        if matches and ''.join(m.group() for m in matches) == body:
            return [m[1].replace("''", "'") for m in matches]
    return None


def _same_words(actual, expected):
    # Both separators name the same Windows path. Keep all non-path arguments,
    # casing, executable identity and command structure exact.
    return len(actual)==len(expected) and all(a==b or os.name=='nt' and os.path.isabs(b)
        and a.replace('/', '\\')==b.replace('/', '\\') for a,b in zip(actual,expected))


def _owned_argv(root, attempt, command):
    words = _literal_words(command.strip())
    prefix = command_prefix(root, attempt)
    if not words or not _same_words(words[:-1],prefix):
        return None
    try:
        argv = json.loads(words[-1])
    except ValueError:
        return None
    if isinstance(argv, list) and argv and all(isinstance(x, str) and '\0' not in x for x in argv):
        return argv
    return None


def _focused_helper(root, attempt, record, command):
    words = _literal_words(command.strip())
    prefix = command_prefix(root, attempt)[:-3]
    if not words or not _same_words(words[:len(prefix)],prefix) or len(words) <= len(prefix):
        return False
    action, *args = words[len(prefix):]
    if action == 'admission':
        return action if _same_words(args,[record['directory']]) else False
    return action if action in ('candidate', 'verify', 'review-check', 'resource', 'command-format', 'status', 'config', 'plans') and (
        action != 'config' or not args) else False


def _shell_command(host, name, args):
    """Accept canonical shell hooks and Codex's native unified-exec payload."""
    if name in ('Bash', 'PowerShell'):
        return True, args.get('command')
    if host == 'codex' and name in ('exec_command', 'functions.exec_command'):
        return True, args.get('cmd')
    return False, None


def _deny(reason):
    return {'hookSpecificOutput': {'hookEventName': 'PreToolUse',
            'permissionDecision': 'deny', 'permissionDecisionReason': reason}}


def hook(root, host, payload):
    """A native callback can revoke or refuse work, never approve or rewrite a tool."""
    from subprocess import CalledProcessError
    from .storage import git
    try:
        root = Path(git(root, 'rev-parse', '--show-toplevel'))
    except CalledProcessError:
        return {}
    try:
        path = _path(root)
    except Refused as exc:
        if 'not registered' in str(exc):
            return {}
        raise
    if not path.exists():
        return {}
    # Resolve registration once for this synchronous callback. Repeated Git
    # identity checks in poll/read/edit can otherwise exhaust the host deadline.
    token=_hook_checkout.set((root,path))
    try:return _hook(root,host,payload)
    finally:_hook_checkout.reset(token)


def _hook(root,host,payload):
    event = payload.get('hook_event_name')
    caught_up = poll(root) if event == 'PreToolUse' else True
    use = payload.get('tool_use_id')
    session, turn = payload.get('session_id'), payload.get('turn_id')
    with _edit(root) as value:
        active = value['owners'].get(value.get('current'))
        actor = _actor(value, host, payload)
        if actor is None and payload.get('agent_id'):
            pending = [(a, r) for a, r in value['attempts'].items()
                       if r['launch'] and not r['child'] and not r['finished']
                       and value['owners'][r['owner']]['host'] == host
                       and value['owners'][r['owner']]['session'] == session]
            if len(pending) == 1:
                actor, pending_record = pending[0]
                pending_record['child'] = payload['agent_id']
        if event == 'Interrupt':
            matches = [o for o in value['owners'].values()
                       if o['host'] == host and o['session'] == session and turn in o['turns']]
            for owner in matches:
                _record_stop(owner, turn, {'host': host, 'session': session, 'turn': turn,
                                          'at': now(), 'event': 'Interrupt'})
            return {}
        if event in ('PostToolUse', 'PostToolUseFailure'):
            if use in value['tools']:
                value['tools'][use]['ended'] = now()
            return {}
        if event == 'SubagentStart':
            pending = [(a, r) for a, r in value['attempts'].items()
                       if r['launch'] and not r['child'] and not r['finished']
                       and value['owners'][r['owner']]['host'] == host
                       and value['owners'][r['owner']]['session'] == session]
            if len(pending) == 1 and payload.get('agent_id'):
                pending[0][1]['child'] = payload['agent_id']
            return {}
        if event != 'PreToolUse':
            return {}
        name = payload.get('tool_name', '')
        args = payload.get('tool_input') or {}
        shell, command = _shell_command(host, name, args)
        if not actor and turn and any(o['host'] == host and o['session'] == session
                                     and _turn_stopped(o, turn)
                                     for o in value['owners'].values()):
            return _deny('This native turn was stopped. Do not continue its tools; a new human turn can resume the saved work.')
        if actor:
            record = value['attempts'][actor]
            record['guard_observed'] = True
            owner = value['owners'][record['owner']]
            if record['finished'] or Path(owner['marker']).exists():
                return _deny('This OH attempt has ended. Stop this worker; do not retry through another tool. '
                             'The coordinator can resume with a fresh attempt in either conversation.')
            if not caught_up:
                return _deny('OH is waiting for native interruption evidence to finish saving. Retry this same tool call; no new approval is needed.')
            if not use:
                return _deny('The native host omitted this tool’s identity. Retry the same call after its records are saved; OH cannot track an unidentified operation.')
            admission_call = (name.endswith('admission') and args.get('attempt_directory') == record['directory'])
            admission_shell = (shell and isinstance(command, str)
                               and _focused_helper(root, actor, record, command)
                               and 'admission' in (_literal_words(command.strip()) or []))
            if not record.get('verified') and not (admission_call or admission_shell):
                words = command_prefix(root, actor)[:-3] + ['admission', record['directory']]
                invocation = _shell_guidance(words, host, name)
                return _deny('This worker has not validated its admission. Run the exact admission command below, '
                             'then retry this operation. Do not launch a replacement or ask for approval again. '
                             'Native shell invocation: ' + invocation)
            if shell:
                if not isinstance(command, str):
                    return _deny('The native host did not provide this command as text.')
                helper = _focused_helper(root, actor, record, command)
                if helper:
                    if helper == 'verify':
                        words = _literal_words(command.strip())
                        args = words[len(command_prefix(root, actor)[:-3]) + 1:]
                        if args[:2] != ['--attempt', actor] or len(args) > 4 or any(v.startswith('-') for v in args[2:]):
                            prefix = command_prefix(root, actor)[:-3] + ['verify', '--attempt', actor]
                            invocation = _shell_guidance(prefix, host, name)
                            return _deny('Bind this check to its admitted attempt, then retry the same native shell call: ' + invocation)
                    if use:
                        value['tools'][use] = {'attempt': actor, 'kind': 'tool', 'name': 'OH helper',
                                               'helper': helper, 'started': now()}
                    return {}
                argv = _owned_argv(root, actor, command)
                if argv is None:
                    example = _shell_guidance(command_prefix(root, actor) + [json.dumps(['executable', 'argument'])], host, name)
                    return _deny('For OH helpers, use the exact native_commands.helper_prefix from the packet directly. '
                                 'In Codex, use command_format with this attempt ID and the executable/argument array, then run its returned command unchanged. '
                                 'For ordinary project commands, use OH’s owned-command helper with the same native shell tool '
                                 'and its normal permissions. Pass the executable and arguments as a JSON array; '
                                 'for shell syntax, include the explicit original shell and its command argument. '
                                 'Invocation format: ' + example)
                if not use:
                    return _deny('The native host omitted the command identity; retry this same call after its records are saved.')
                from .system import make_temp_directory
                receipt = make_temp_directory(prefix='oh-command-')
                value['tools'][use] = {'attempt': actor, 'kind': 'command',
                                       'argv': digest(argv), 'started': now(), 'receipt': receipt}
                return {}
            if use:
                value['tools'][use] = {'attempt': actor, 'kind': 'tool', 'name': name, 'started': now()}
            return {}
        # Only native OH launches are associated with an admission. Unrelated host work is untouched.
        target = args.get('task_name')
        text = args.get('prompt', args.get('message', ''))
        launches = [(a, r) for a, r in value['attempts'].items()
                    if target == 'oh_' + a.replace('-', '') or
                    isinstance(text, str) and str(Path(r['directory']) / 'request.json') in text]
        if launches:
            if len(launches) != 1:
                return _deny('This launch names more than one OH admission; use the current immutable request.')
            attempt, record = launches[0]
            owner = value['owners'][record['owner']]
            if owner['host'] != host or owner['session'] != session or record['finished'] or Path(owner['marker']).exists():
                return _deny('This OH admission was stopped or superseded. Use Resume and obtain a fresh admission.')
            record['launch'] = use
            if use:
                value['tools'][use] = {'attempt': attempt, 'kind': 'launch', 'started': now()}
        if active and active['host'] == host and active['session'] == session and turn:
            # A late callback from a revoked turn must never become part of a new owner epoch.
            old = any(o['host'] == host and o['session'] == session and _turn_stopped(o, turn)
                      for o in value['owners'].values())
            if not old and turn not in active['turns']:
                active['turns'].append(turn)
        return {}


@contextmanager
def execution(root, state, attempt, *, receipt=None, owner=None):
    if receipt is None:
        guard(root, attempt=attempt)
    context = {'root': Path(root), 'attempt': attempt, 'receipt': receipt, 'owner': owner}
    token = _execution.set(context)
    try:
        yield
    finally:
        _execution.reset(token)


def command_context():
    return _execution.get()


def started_command(context, argv):
    root, attempt = context['root'], context['attempt']
    if context['receipt'] is not None:
        caught_up, stopped = observe(context)
        if stopped or not caught_up:
            raise Refused('This command was stopped or its interruption evidence is still saving')
        atomic_json(context['receipt'] / 'started.json', {'attempt': attempt, 'argv': digest(argv), 'at': now(), 'gated': True}, immutable=True)
        return attempt, Path(context['owner']['marker'])
    with _edit(root) as value:
        record = value['attempts'].get(attempt)
        if not record or record['finished'] or Path(value['owners'][record['owner']]['marker']).exists():
            raise Refused('This command belongs to a stopped or completed OH attempt')
        key = identifier()
        value['commands'][key] = {'attempt': attempt, 'argv': digest(argv), 'started': now(), 'gated': True}
        return key, Path(value['owners'][record['owner']]['marker'])


def ended_command(context, key, returncode):
    if context['receipt'] is not None:
        atomic_json(context['receipt'] / 'result.json', {'at': now(), 'returncode': returncode}, immutable=True)
        return
    with _edit(context['root']) as value:
        record = value['commands'][key]
        record.update(ended=now(), returncode=returncode)


def spawned_command(context, key, child):
    """Keep the OS identity needed if the native host kills the helper itself."""
    from .system import process_identity
    record = {'pid': child.pid, 'identity': process_identity(child.pid)}
    if getattr(child, 'oh_job_name', None):
        record['job'] = child.oh_job_name
    if context['receipt'] is not None:
        atomic_json(context['receipt'] / 'process.json', record, immutable=True)
    else:
        with _edit(context['root']) as value:
            value['commands'][key]['process'] = record


def _quiescent(value, attempt):
    if not value or attempt not in value['attempts']:
        return True  # Historical attempts still require their actual native terminal result.
    if any(c['attempt'] == attempt and not c.get('ended') for c in value['commands'].values()):
        return False
    for tool in value['tools'].values():
        if tool['attempt'] != attempt:
            continue
        # Cancelled parallel code-mode calls can lose their completion callback.
        # These focused reads cannot edit the consumer or grant execution.
        # Their missing replies must not prevent retention of a terminal worker.
        if tool['kind']=='tool' and tool.get('name') in ('mcp__o_harness__resource','mcp__o_harness__command_format'):
            continue
        if tool.get('receipt'):
            if tool.get('cleanup', {}).get('source') == 'kernel-reboot':
                continue
            receipt = Path(tool['receipt'])
            if not receipt.is_dir():
                return False  # Missing evidence is not proof of a command that never started.
            if (receipt / 'claimed.json').exists() and not (receipt / 'result.json').exists():
                return False
            continue
        if not tool.get('ended') and not (tool['kind'] == 'command' and not tool.get('claimed')):
            return False
    return True


def quiescent(root, attempt):
    return _quiescent(_read(root), attempt)


def guarded(root, attempt):
    value = _read(root)
    return bool(value and value['attempts'].get(attempt, {}).get('guard_observed'))


@contextmanager
def settlement(root, attempt):
    """Close the tool gate and journal the result under the same tool-admission lock."""
    with _edit(root) as value:
        if not _quiescent(value, attempt):
            from .authority import Saving
            raise Saving('Owned command or tool cleanup is still pending. Retry retention with the same answer.')
        yield
        if attempt in value['attempts']:
            value['attempts'][attempt]['finished'] = True


def reconcile_tools(root, attempt, terminal=None):
    """Reconcile under the control lock; report edits needing native completion."""
    value = _read(root)
    control = value['attempts'].get(attempt['id']) if value else None
    launches = {key for key, tool in value['tools'].items()
                if tool['attempt'] == attempt['id'] and tool['kind'] == 'launch'
                and not tool.get('ended')} if control else set()
    if launches:
        from .authority import _records
        owner = value['owners'][control['owner']]
        ended = set()
        # Launch calls belong to the original parent, including rejected calls
        # with no child and earlier calls superseded by a corrected retry.
        # Settling a launch does not establish child or owned-command completion.
        for record in _records(owner['transcript']):
            if owner['host'] == 'codex' and record.get('type') == 'response_item':
                item = record.get('payload') or {}
                if item.get('type') in ('function_call_output', 'custom_tool_call_output') and item.get('call_id') in launches:
                    ended.add(item['call_id'])
            if (owner['host'] == 'claude' and record.get('type') == 'user'
                    and record.get('sessionId') == owner['session'] and not record.get('isSidechain')):
                content = (record.get('message') or {}).get('content')
                for item in content if isinstance(content, list) else []:
                    if isinstance(item, dict) and item.get('type') == 'tool_result' and item.get('tool_use_id') in launches:
                        ended.add(item['tool_use_id'])
        if ended:
            with _edit(root) as updated:
                for key in ended:
                    updated['tools'][key].update(ended=now(), completion_source='native-parent-record')
    bound = attempt.get('native_child')
    if not bound:
        return
    value = _read(root)
    control = value['attempts'].get(attempt['id']) if value else None
    if control and Path(value['owners'][control['owner']]['marker']).exists():
        from .controls import busy
        from .system import recover_process
        if not busy(root):
            for key, command in value['commands'].items():
                if command['attempt'] != attempt['id'] or command.get('ended'):
                    continue
                proof = recover_process(command)
                if proof:
                    with _edit(root) as updated:
                        updated['commands'][key].update(ended=now(), returncode=130, cleanup=proof)
                elif not command.get('process') and not command.get('gated'):
                    raise Refused('Native Stop cleanup is still pending. This older OH command has neither a cleanup receipt '
                                  'nor a saved process identity, so its descendants cannot be identified safely. '
                                  'Preserve the checkout and OH evidence in persistent storage before considering a reboot. '
                                  'A verified reboot proves process cleanup only; Resume still requires the original checkout identity. '
                                  'If identity validation fails, preserve the original registration and resolve that blocker; '
                                  'do not use init --replace to recover this active run.')
            # Temporary command receipts may be removed by the reboot itself.
            # An ended native shell call alone does not establish descendant
            # cleanup; a later kernel boot does, without recreating lost receipts.
            for key, tool in value['tools'].items():
                if tool['attempt'] != attempt['id'] or not tool.get('receipt') or tool.get('cleanup'):
                    continue
                if (Path(tool['receipt']) / 'result.json').exists():
                    continue
                proof = recover_process({'started': tool['started']})
                if proof:
                    with _edit(root) as updated:
                        updated['tools'][key].update(ended=now(), cleanup=proof)
            value = _read(root)
    pending = {key for key, tool in value['tools'].items()
               if tool['attempt'] == attempt['id'] and not tool.get('ended')} if value else set()
    if not pending:
        return
    from .authority import _records
    ended = {}
    for record in _records(bound['transcript_path']):
        if record.get('type') == 'response_item':
            item = record.get('payload') or {}
            if item.get('type') in ('function_call_output', 'custom_tool_call_output') and item.get('call_id') in pending:
                ended[item['call_id']] = 'native-record'
        if record.get('type') == 'event_msg':
            event = record.get('payload') or {}
            item = event.get('item') or {}
            # Code-mode nested tools use exec-* IDs in item_completed, not the
            # enclosing custom_tool_call_output's call_* ID. A returned MCP
            # error is completion. Discovery can also fail before a server is
            # reached, leaving only an error. That ends the read-only discovery
            # call, but an arbitrary MCP transport error cannot prove cleanup.
            tool = value['tools'].get(item.get('id'), {})
            discovery_failed = (tool.get('kind') == 'tool'
                and tool.get('name') in ('list_mcp_resources', 'list_mcp_resource_templates')
                and item.get('tool') == tool['name']
                and item.get('status') == 'failed' and isinstance(item.get('error'), dict))
            item_terminal = (
                item.get('type') == 'McpToolCall' and (isinstance(item.get('result'), dict) or discovery_failed)
                or item.get('type') == 'CommandExecution' and type(item.get('exit_code')) is int
                or item.get('type') == 'FileChange')
            if (event.get('type') == 'item_completed'
                    and event.get('thread_id') == bound['child_session']
                    and item.get('id') in pending
                    and item.get('status') in ('completed', 'failed') and item_terminal):
                ended[item['id']] = 'native-record'
        if record.get('type') == 'user':
            content = (record.get('message') or {}).get('content')
            for item in content if isinstance(content, list) else []:
                if isinstance(item, dict) and item.get('type') == 'tool_result' and item.get('tool_use_id') in pending:
                    ended[item['tool_use_id']] = 'native-record'
    owner = value['owners'][value['attempts'][attempt['id']]['owner']]
    # Codex may omit the inner FileChange/post-hook when apply_patch fails before
    # execution. Its native completed child is the lifecycle boundary for this
    # built-in edit, not for commands, helpers or arbitrary external tools.
    from .authority import newer
    if (owner['host']=='codex' and terminal and terminal.get('status')=='completed'
            and terminal.get('native_id')==bound['child_session']):
        for key in pending-ended.keys():
            tool=value['tools'][key]
            if (tool['kind']=='tool' and tool.get('name')=='apply_patch'
                    and newer(terminal.get('completed_at'),tool.get('started'))):
                ended[key]='native-child-completed'
    if Path(owner['marker']).exists():
        from .controls import busy
        # verify holds oh-runner.lock across every check and its final journal
        # write. The caller holds oh-control.lock, so no queued old verify can
        # pass _author's Stop check while this proof/retention is committed.
        # Command receipts remain independently required by _quiescent, even
        # if a killed helper released its lock before its descendants ended.
        if not busy(root):
            for key in pending - ended.keys():
                tool = value['tools'][key]
                if tool.get('name') == 'mcp__o_harness__verify' or tool.get('helper') == 'verify':
                    ended[key] = 'stopped-verification'
    if ended:
        with _edit(root) as value:
            for key, source in ended.items():
                value['tools'][key]['ended'] = now()
                value['tools'][key]['completion_source'] = source
    return owner['host']=='codex' and any(value['tools'][key]['kind']=='tool'
        and value['tools'][key].get('name')=='apply_patch' for key in pending-ended.keys())


def unlaunched_stop(root, attempt, stopped):
    """Prove the admission had no launch before the parent's saved native Stop."""
    value = _read(root)
    record = value['attempts'].get(attempt['id']) if value else None
    if not record or record['child'] or record['launch']:
        return None
    owner = value['owners'][record['owner']]
    from .authority import _records, _claude_interruption, newer
    stop_record = None
    for event in _records(owner['transcript']):
        if not newer(event.get('timestamp'), attempt['started_at']):
            continue
        if owner['host'] == 'codex':
            item = event.get('payload') or {}
            if not isinstance(item, dict):
                continue
            if event.get('type') == 'response_item' and item.get('type') == 'function_call':
                if item.get('name', '').split('.')[-1] == 'spawn_agent':
                    try:
                        args = json.loads(item.get('arguments', '{}'))
                    except (ValueError, TypeError):
                        return None
                    if args.get('task_name') == 'oh_' + attempt['id'].replace('-', ''):
                        return None
            if (event.get('type') == 'event_msg' and item.get('type') == 'turn_aborted'
                    and item.get('turn_id') == stopped['turn'] and item.get('reason') == 'interrupted'):
                stop_record = event
        elif event.get('sessionId') == owner['session'] and not event.get('isSidechain'):
            content = (event.get('message') or {}).get('content')
            for item in content if isinstance(content, list) else []:
                if isinstance(item, dict) and item.get('type') == 'tool_use' and item.get('name') in ('Agent', 'Task'):
                    if attempt['id'] in (item.get('input') or {}).get('prompt', ''):
                        return None
            if _claude_interruption(event):
                stop_record = event
    return digest(stop_record) if stop_record else None


@contextmanager
def continuation(root, state, source, *, replacing=False):
    """Serialize the final ownership transfer with a native Stop during cleanup."""
    from .authority import newer
    proposed = state | {'human': source}
    key = register_owner(root, proposed, active=False)
    for owner_state in ((proposed,) if replacing else (state, proposed)):
        if not poll(root, state=owner_state):
            raise Refused('Native interruption evidence is still being saved or read. Retry the same Resume answer.')
    from .authority import child_user_interruption
    control = _read(root)
    for attempt in (() if replacing else state.get('attempts', [])):
        owner = (control or {}).get('attempts', {}).get(attempt['id'], {}).get('owner')
        if owner and owner != owner_key(state):
            continue  # A previous owner epoch cannot revoke this continuation.
        stopped = child_user_interruption(root, state, attempt)
        if stopped and not newer(source.get('at'), stopped['at']):
            raise Refused('Work was stopped after this Resume answer. Invoke the work again to resume; the old answer cannot restart it.')
    with _edit(root) as value:
        for owner_id in ({key} if replacing else {owner_key(state), key}):
            owner = value['owners'].get(owner_id)
            if not owner or not Path(owner['marker']).exists():
                continue
            stopped = read_json(owner['marker'])
            if stopped['event'] == 'Interrupt':
                from .authority import Saving
                raise Saving('Native Stop was observed but its occurrence record is still saving. Retry the same Resume answer.')
            if not newer(source.get('at'), stopped['at']):
                raise Refused('Work was stopped after this Resume answer. Invoke the work again to resume; the old answer cannot restart it.')
        yield
        value['current'] = key


def owned_command(root, attempt, argv):
    """Run only a native-hook-reserved command, inside the host's existing sandbox."""
    if not isinstance(argv, list) or not argv or not all(isinstance(v, str) for v in argv):
        raise Refused('An owned command needs an explicit executable and argument array')
    with _read_control(root) as value:
        record = value['attempts'].get(attempt)
        if not record or record['finished']:
            raise Refused('This command belongs to a completed OH attempt')
        owner = dict(value['owners'][record['owner']])
        context = {'owner': owner}
        caught_up, stopped = observe(context)
        if stopped or not caught_up:
            raise Refused('Native Stop ended this command or its interruption evidence is still saving')
        candidates = [v for v in value['tools'].values()
                      if v['attempt'] == attempt and v['kind'] == 'command'
                      and v.get('argv') == digest(argv) and not v.get('ended') and v.get('receipt')
                      and Path(v['receipt']).is_dir() and not (Path(v['receipt']) / 'claimed.json').exists()]
        if not candidates:
            raise Refused('OH has no native hook reservation for this command. The callback may not have run or matched this invocation. '
                          'Check the host hook execution error and the packet command prefix; repair the cause before retrying the same native call. '
                          'This does not establish that hook trust is missing.')
        receipt = Path(candidates[0]['receipt'])
        atomic_json(receipt / 'claimed.json', {'attempt': attempt, 'argv': digest(argv), 'at': now()}, immutable=True)
    from .processes import interruptible, launch
    try:
        with interruptible(), execution(root, None, attempt, receipt=receipt, owner=owner):
            with launch(root, argv, cwd=Path.cwd()) as (child, cancelled, reason):
                from .system import wait_for_exit
                wait_for_exit(child)
        return 130 if reason or observe({'owner': owner})[1] else child.returncode
    except KeyboardInterrupt:
        return 130
    finally:
        if not (receipt / 'started.json').exists():
            atomic_json(receipt / 'result.json', {'at': now(), 'not_started': True}, immutable=True)
