"""OH's tools for Codex. Codex runs its sandboxed shell where it can write only inside the project, but OH
keeps its runs, approvals and locks in its own folder, which the model must not be able to write. Codex runs
a plugin's MCP server outside that sandbox, so OH's everyday commands are tools of this server: each runs one
OH command through the plugin's own `oh` launcher, exactly as the shell would. `choose` shows the choice OH is
waiting for as a native menu (MCP elicitation) and records the click itself.

Commands that change what OH runs on the machine (settings and checks, setup, host trust, backups, services)
are not tools: they run in the shell, where Codex asks the person first. Codex names the conversation and
turn that called a tool in the request's metadata, which the model can't set; every tool acts only on the
checkout that conversation works in. Codex starts this server from the plugin: no `oh` command reaches it."""
import json
import os
from pathlib import Path
import queue
import re
import subprocess
import sys
import threading
from .storage import Refused, identifier, now

VERSION = '2025-06-18'
ROOT = {'type': 'string', 'description': 'Absolute path of the project checkout (the Git repository root)'}
TEXT = {'type': 'string'}


def tool(name, title, description, properties=None, required=(), read_only=False):
    return {'name': name, 'title': title, 'description': description,
            'inputSchema': {'type': 'object', 'required': ['root', *required], 'additionalProperties': False,
                            'properties': {'root': ROOT} | (properties or {})},
            'annotations': {'readOnlyHint': read_only, 'destructiveHint': False, 'idempotentHint': read_only, 'openWorldHint': False}}


TOOLS = [
    tool('status', 'OH status', 'Shows the OH run in this checkout: its status, tasks and what it is waiting for.', read_only=True),
    tool('config', 'OH settings', 'Shows every OH setting with its value, default and meaning, and this project\'s checks. '
         'Read only: changing a setting is `config set` in the shell, which Codex asks the person to approve.', read_only=True),
    tool('init', 'Register the project', 'Registers this checkout with OH: it joins the project of the same repository, or '
         'names a new one after the repository folder.', {'name': TEXT | {'description': 'Only when the person asks for another name'}}),
    tool('plans', 'OH plans', 'Where this project\'s plans live (path), whether they are consistent (check), and the designs (list).',
         {'action': {'type': 'string', 'enum': ['path', 'check', 'list']}}, ['action'], read_only=True),
    tool('resource', 'OH workflow', 'Returns one of OH\'s workflow instructions, such as workflows/deliver/SKILL.md.',
         {'path': TEXT}, ['path'], read_only=True),
    tool('deliver', 'Deliver', 'Runs `deliver` with the person\'s arguments: none lists ready work, a design number delivers '
         'it, and prose proposes a quick fix.', {'arguments': {'type': 'array', 'items': TEXT}}),
    tool('prepare', 'Prepare tasks', 'Saves a task list in OH\'s storage for the person to approve. Returns the exact '
         'trigger the person types to approve it.', {'tasks': {'type': 'array', 'items': {'type': 'object'},
         'description': 'Tasks with id, title, instructions and optional needs, ordered by dependency'}}, ['tasks']),
    tool('prepare_design', 'Prepare a design', 'Binds an approved design document for delivery.',
         {'doc': TEXT, 'track': TEXT}, ['doc']),
    tool('start', 'Start prepared work', 'Verifies the person\'s approval and runs the prepared work.', {'request': TEXT}),
    tool('run', 'Run OH', 'Verifies the person\'s latest choice and carries it out, or continues the current run. '
         'It can take a long time.'),
    tool('pause', 'Pause', 'Asks the current run to pause at a safe point.'),
    tool('resume', 'Resume', 'Resumes the paused run with the allowances it already had.'),
    tool('stop', 'Stop', 'Ends the current run, keeping its work and evidence.'),
    tool('pr_summary', 'PR summary', 'The review summary for this branch\'s pull request.', {'base': TEXT}, read_only=True),
    tool('choose', 'Ask the person to choose', 'Shows the person the choice OH is waiting for (continue, approve, stop...) '
         'as a menu and records their click in OH. Call it when OH output has a `gate`, in the conversation that '
         'started the run. The result says what was recorded and whether to call `run`.'),
]
NAMES = {t['name'] for t in TOOLS}


def command(name, arguments, root):
    """The `oh` arguments a tool runs. Values follow `--`, so none can be read as an option."""
    def text(key, required=False):
        value = arguments.get(key)
        if value is None and not required:return None
        if not isinstance(value, str) or not value.strip():raise Refused(f'`{key}` must be text')
        return value
    if name in ('status', 'config', 'run', 'pause', 'resume', 'stop'):return [name]
    if name == 'init':return ['init'] + ([f'--name={text("name")}'] if text('name') else [])
    if name == 'plans':
        if arguments.get('action') not in ('path', 'check', 'list'):raise Refused('`action` is path, check or list')
        return ['plans', arguments['action']]
    if name == 'resource':return ['resource', '--', text('path', True)]
    if name == 'deliver':
        values = arguments.get('arguments') or []
        if not isinstance(values, list) or not all(isinstance(v, str) for v in values):raise Refused('`arguments` is a list of text')
        return ['deliver', '--', *values]
    if name == 'prepare':return ['prepare', '--', str(manifest(root, arguments.get('tasks')))]
    if name == 'prepare_design':return ['prepare-design', '--', text('doc', True)] + ([text('track')] if text('track') else [])
    if name == 'start':return ['start'] + (['--', text('request')] if text('request') else [])
    if name == 'pr_summary':return ['pr-summary'] + (['--', text('base')] if text('base') else [])
    raise Refused('Unknown tool')


def manifest(root, tasks):
    """Save a task list where `prepare` reads it: OH's storage for this project, which the model can't write."""
    from .prepared import directory
    from .storage import atomic_json, digest
    if not isinstance(tasks, list) or not tasks:raise Refused('`tasks` is a nonempty list')
    path = directory(root).parent / 'manifests' / (digest(tasks)[:16] + '.json')
    atomic_json(path, {'tasks': tasks})
    return path


def conversation(meta):
    """The Codex conversation that called: set by Codex in the request, never by the model."""
    turn = meta.get('x-codex-turn-metadata') if isinstance(meta.get('x-codex-turn-metadata'), dict) else {}
    thread = turn.get('thread_id') or meta.get('threadId')
    if not isinstance(thread, str) or not re.fullmatch(r'[a-zA-Z0-9_-]+', thread):
        raise Refused('This Codex version does not say which conversation is calling OH. Update Codex, or run OH '
                      'from the shell with the plugin\'s scripts/oh.')
    return thread


def folder(thread):
    """The folder the conversation works in, from Codex's own saved session."""
    home = Path(os.environ.get('CODEX_HOME') or Path.home() / '.codex').expanduser()
    files = list((home / 'sessions').rglob('*' + thread + '.jsonl'))
    if len(files) != 1:raise Refused('OH could not find this Codex conversation\'s saved session.')
    cwd = None
    with files[0].open('rb') as stream:
        first = json.loads(stream.readline() or b'{}')
        if first.get('type') != 'session_meta' or (first.get('payload') or {}).get('id') != thread:
            raise Refused('OH could not read this Codex conversation\'s saved session.')
        cwd = first['payload'].get('cwd')
        stream.seek(max(0, files[0].stat().st_size - 4 * 1024 * 1024))
        for line in stream:
            try:item = json.loads(line)
            except ValueError:continue
            if isinstance(item, dict) and item.get('type') == 'turn_context':cwd = (item.get('payload') or {}).get('cwd') or cwd
    if not isinstance(cwd, str) or not cwd:raise Refused('OH could not tell which folder this Codex conversation works in.')
    return Path(cwd).resolve()


def checkout(arguments, thread):
    root = arguments.get('root')
    if not isinstance(root, str) or not Path(root).is_absolute() or not Path(root).is_dir():
        raise Refused('Pass the absolute path of the project checkout as root.')
    root = Path(root).resolve()
    if not folder(thread).is_relative_to(root):
        raise Refused(f'This conversation works outside {root}; OH acts only on the checkout the conversation is in.')
    return root


class Server:
    def __init__(self, stdin, stdout, launcher=None):
        self.stdin, self.stdout, self.launcher, self.client = stdin, stdout, launcher, {}
        self.lock, self.replies, self.cancelled = threading.Lock(), {}, {}

    def send(self, message):
        with self.lock:
            self.stdout.write(json.dumps({'jsonrpc': '2.0'} | message) + '\n');self.stdout.flush()

    def serve(self):
        """Read the host's messages. Tool calls run on their own threads, so the server keeps answering (a ping,
        a menu's reply, a cancel) while a long OH run is working."""
        for line in iter(self.stdin.readline, ''):
            try:message = json.loads(line)
            except ValueError:continue
            if not isinstance(message, dict):continue
            method, ident = message.get('method'), message.get('id')
            if method is None and ident in self.replies:self.replies[ident].put(message)
            elif method == 'notifications/cancelled':
                cancelled = self.cancelled.get((message.get('params') or {}).get('requestId'))
                if cancelled:cancelled.set()
            elif method == 'initialize':
                self.client = message.get('params') or {}
                self.send({'id': ident, 'result': {'protocolVersion': self.client.get('protocolVersion', VERSION),
                    'capabilities': {'tools': {}}, 'serverInfo': {'name': 'o-harness', 'version': '1'}}})
            elif method == 'tools/list':self.send({'id': ident, 'result': {'tools': TOOLS}})
            elif method == 'tools/call':
                self.cancelled[ident] = threading.Event()
                threading.Thread(target=self.call, args=(message,), daemon=True).start()
            elif method == 'ping' and ident is not None:self.send({'id': ident, 'result': {}})
            elif method and ident is not None:self.send({'id': ident, 'error': {'code': -32601, 'message': 'Not supported'}})

    def call(self, message):
        ident, params = message['id'], message.get('params') or {}
        try:text, error = self.tool(params.get('name'), params.get('arguments') or {}, params.get('_meta') or {}, ident), False
        except (Refused, OSError, ValueError, KeyError) as exc:text, error = f'OH: {exc}', True
        finally:self.cancelled.pop(ident, None)
        self.send({'id': ident, 'result': {'content': [{'type': 'text', 'text': text}], 'isError': error}})

    def tool(self, name, arguments, meta, ident):
        if os.environ.get('OH_CHILD_ATTEMPT'):raise Refused('OH workers cannot use OH\'s tools.')
        if name not in NAMES:raise Refused('Unknown tool')
        if not isinstance(arguments, dict):raise Refused('Arguments must be an object')
        thread = conversation(meta)
        root = checkout(arguments, thread)
        if name == 'choose':return self.choose(root, thread, ident)
        return self.oh(root, command(name, arguments, root), thread, meta.get('progressToken'))

    def oh(self, root, argv, thread, token):
        """Run one OH command through the plugin's launcher, as the shell would, in the calling conversation.
        OH's progress lines become progress notifications when the host asked for them."""
        environment = dict(os.environ, CODEX_THREAD_ID=thread)
        output, lines = [], []
        with subprocess.Popen([sys.executable, '-I', str(self.launcher), '--root', str(root), *argv], stdin=subprocess.DEVNULL,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=environment, text=True, encoding='utf-8', errors='replace') as process:
            reader = threading.Thread(target=lambda: output.append(process.stdout.read()), daemon=True);reader.start()
            for count, line in enumerate(process.stderr, 1):
                lines.append(line.rstrip())
                if token is not None:self.send({'method': 'notifications/progress', 'params': {'progressToken': token, 'progress': count, 'message': line.strip()}})
            reader.join()
        code = process.returncode
        if code:
            said = [line[4:] for line in lines if line.startswith('OH: ')]
            raise Refused(said[-1] if said else '\n'.join(lines[-5:]) or f'OH exited with {code}')
        return ''.join(output).strip() or 'Done.'

    def elicit(self, message, schema, call):
        ident = 'oh-menu-' + identifier()  # unguessable, so only the host can answer this menu
        replies = self.replies[ident] = queue.Queue()
        try:
            self.send({'id': ident, 'method': 'elicitation/create', 'params': {'message': message, 'requestedSchema': schema}})
            while True:
                try:return replies.get(timeout=0.2)
                except queue.Empty:
                    if call not in self.cancelled or self.cancelled[call].is_set():return {'result': {'action': 'cancel'}}
        finally:self.replies.pop(ident, None)

    def choose(self, root, thread, call):
        from .config import project_name, version
        from .gates import apply, current
        from .workflow import load_run
        gate = current(root)
        if not gate:return 'No OH choice is waiting in this checkout.'
        if gate['host'] != 'codex':raise Refused('This run belongs to Claude; ask there.')
        _, state = load_run(root)
        if thread != state['human']['session']:raise Refused('Ask in the Codex conversation that started this run.')
        typed = ', '.join(o['choice'] for o in gate['options']) + (', or refine: <what to change>' if gate['words'] else '')
        fallback = f'No choice was made. Ask the person to type one of: {typed}.'
        from .authority import answered, supersede, typed_choice
        if typed_choice(root, 'codex'):
            return 'The person already typed a choice; call `run` to apply it instead of asking again.'
        if state['harness_version'] != version():
            return 'OH was updated after this run started, so its menu is not shown. ' + fallback
        if 'elicitation' not in (self.client.get('capabilities') or {}):
            return 'This Codex surface cannot show OH menus. ' + fallback
        menu = gate['options'] + ([{'choice': 'refine', 'label': 'Refine', 'description': ''}] if gate['words'] else [])
        properties = {'choice': {'type': 'string', 'title': 'Your choice', 'enum': [o['choice'] for o in menu],
                                 'enumNames': [o['label'] for o in menu]}}
        if gate['words']:
            properties['changes'] = {'type': 'string', 'title': 'What to change (only for Refine)'}
        details = '\n'.join(f'- {o["label"]}: {o["description"]}' for o in gate['options'] if o['description'] != o['label'])
        message = (f"{gate['question'].split(' [')[0]}\nProject {project_name(root)} · {root} · run {state['id'][:8]}"
                   + ('\n' + details if details else ''))
        reply = self.elicit(message, {'type': 'object', 'required': ['choice'], 'properties': properties}, call)
        result = reply.get('result') or {}
        if result.get('action') != 'accept':
            return 'The menu was closed or could not be shown here. ' + fallback
        content = result.get('content') or {}
        choice = content.get('choice')
        if choice not in [o['choice'] for o in menu]:return 'The menu came back without a valid choice. ' + fallback
        if choice == 'refine':
            words = content.get('changes')
            if not isinstance(words, str) or not words.strip():
                return 'Refine needs what to change; nothing was recorded. Ask the person to type: refine: <what to change>.'
            choice = 'refine: ' + ' '.join(words.split())
        event = {'host': 'codex', 'session': thread, 'turn': 'menu-' + identifier(), 'prompt': choice, 'via': 'elicitation', 'at': now()}
        supersede(root, 'codex')  # anything typed while the menu was open is older than this click
        after = apply(root, event, gate['id'])
        answered(root, 'codex', thread, state['human'].get('transcript_path'))
        label = next((o['label'] for o in menu if o['choice'] == choice.split(':')[0]), choice)
        if after['status'] in ('stopped', 'completed') and not after.get('gate'):
            return f'Recorded the person\'s choice: {label}. The run is {after["status"]}; there is nothing left to run.'
        return f'Recorded the person\'s choice: {label}. Call `run` to carry it out. Status now: {after["status"]}.'


def serve(stdin, stdout, launcher=None):
    Server(stdin, stdout, launcher).serve()
