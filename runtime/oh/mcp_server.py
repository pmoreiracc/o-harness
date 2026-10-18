"""Focused OH records and validation tools. Native host tools own agents and questions.

The MCP bridge exists to access OH's external storage from Codex. It neither displays
menus nor executes model-selected shell commands or launches agent subprocesses.
"""
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import threading
from .storage import Refused

VERSION = '2025-06-18'
ROOT = {'type': 'string', 'description': 'Absolute path of the project checkout (the Git repository root)'}
TEXT = {'type': 'string'}


def tool(name, title, description, properties=None, required=(), read_only=False, destructive=False):
    return {'name': name, 'title': title, 'description': description,
            'inputSchema': {'type': 'object', 'required': ['root', *required], 'additionalProperties': False,
                            'properties': {'root': ROOT} | (properties or {})},
            'annotations': {'readOnlyHint': read_only, 'destructiveHint': destructive, 'idempotentHint': read_only, 'openWorldHint': False}}


# These are focused record/validation operations. Native host tools own agents and questions.
OBJECT = {'type': 'object'}
TOOLS = [
    tool('status', 'OH saved facts', 'Read saved tasks, attempts, evidence and allowances; saved lists both workflow and review without selection.', {'saved':{'type':'boolean'}}, read_only=True),
    tool('resume', 'Read unfinished work', 'Read saved continuation and verify a human resume decision when supplied; never renew allowances.', {'human':OBJECT,'run':TEXT}),
    tool('admission', 'Read review admission', 'Read the immutable subject and review request for the admitted reviewer.', {'attempt_directory':TEXT}, ['attempt_directory'], read_only=True),
    tool('config', 'OH settings', 'Read project settings and configured checks.', read_only=True),
    tool('init', 'Register project', 'Register this checkout with OH.', {'name': TEXT}),
    tool('plans', 'Project plans', 'Read plan locations, validate plans, or list designs.',
         {'action': {'type':'string','enum':['path','check','list']}}, ['action'], read_only=True),
    tool('resource', 'OH workflow', 'Read a packaged workflow or role reference.', {'path':TEXT}, ['path'], read_only=True),
    tool('scope_prepare', 'Prepare scope', 'Retain the scope to present through native host tools. Grants no implementation authority.',
         {'manifest':OBJECT,'workflow':{'type':'string','enum':['deliver','design','propose']},'doc':TEXT,'track':TEXT,'human':OBJECT}),
    tool('scope_approve', 'Record scope approval', 'Verify a native human reply for the identified scope; model claims cannot approve it.',
         {'scope':TEXT,'human':OBJECT}, ['scope','human']),
    tool('attempt_admit', 'Admit native agent', 'Bind a fresh agent attempt and its packet; review admission consumes its allowance once.',
         {'role':{'type':'string','enum':['assessment','implementation','analysis','review']}}, ['role']),
    tool('attempt_bind', 'Bind native agent identity', 'Bind the native child returned by the host to its prior admission.',
         {'attempt':TEXT,'source':OBJECT}, ['attempt','source']),
    tool('attempt_retain', 'Retain native result', 'Retain the public native agent result against its admission and subject.',
         {'attempt':TEXT,'source':OBJECT}, ['attempt','source']),
    tool('review_check', 'Check review decision', 'Check a draft decision and full receipt without admitting or finishing an attempt. Grants no authority.',
         {'report':TEXT}, ['report'], read_only=True),
    tool('candidate', 'Prepare review candidate', 'Prepare provisional completion metadata for final checks and independent review; does not complete work.'),
    tool('verify', 'Record project checks', 'Execute configured project checks and retain results against the current candidate.',
         {'base':TEXT,'mode':{'type':'string','enum':['review','pre-push','ci']}}),
    tool('evidence', 'Attach evidence', 'Retain supplementary evidence references for implementation and review; grants no authority.',
         {'attachment':OBJECT}, ['attachment']),
    tool('complete', 'Complete reviewed task', 'Validate scope, verification and independent review before committing the exact reviewed candidate.',
         {'attempt':TEXT}, ['attempt']),
    tool('decision_request', 'Bind decision effect', 'Prepare native human choices. At a completed-task boundary, continue/publish includes available Continue, PR and Stop actions; bind the selected action from the same answer. Displays no menu and grants nothing.',
         {'kind':TEXT,'attempt':TEXT,'rounds':{'type':'integer','minimum':1,
          'description':'Omit to renew the run’s configured review window. Supply only when the person explicitly requests a different number of additional rounds.'},'run':TEXT,'also':TEXT}, ['kind']),
    tool('finding_track', 'Track outside-scope findings', 'Record a saved follow-up, design note or an issue URL. Grants no implementation or issue-creation authority.',
         {'attempt':TEXT,'destination':OBJECT}, ['attempt']),
    tool('decision', 'Record human decision', 'Verify a native human decision about task/review allowance, findings or publication. Displays no menu.',
         {'kind':TEXT,'human':OBJECT,'attempt':TEXT,'destination':OBJECT}, ['kind','human']),
    tool('review', 'Prepare independent review', 'Bind changes, tree, paths, commit, range or task for fresh native read-only review. Grants no repairs.',
         {'arguments':{'type':'array','items':TEXT},'human':OBJECT}),
    tool('pr_summary', 'PR summary', 'Render retained change, verification and review evidence for publication.', {'base':TEXT}),
    tool('publication', 'Reconcile publication', 'Reconcile the approved PR destination with retained publication evidence.',
         {'pr':{'type':'integer','minimum':1}}),
    tool('ci_wait', 'Follow PR checks', 'Wait, up to timeout seconds, for CI on the published PR\'s reviewed head; returns pass, fail, pending, no_checks, skipped, head_changed, merged, closed or unavailable with its next step. Reads only.',
         {'pr':{'type':'integer','minimum':1},'timeout':{'type':'integer','minimum':1,'maximum':21600}}, read_only=True),
]
NAMES = {t['name'] for t in TOOLS}


def payload(root, value):
    """Store tool arguments outside the consumer; these inputs are not approval evidence."""
    from .storage import atomic_json, digest, read_json, state_home
    if not isinstance(value,dict):raise Refused('The helper payload must be an object')
    if len(json.dumps(value).encode())>1048576:raise Refused('Reference large artifacts instead of embedding them in tool arguments')
    path=state_home()/'requests'/digest(str(root))/('native-'+digest(value)+'.json')
    try:atomic_json(path,value,immutable=True)
    except FileExistsError:
        if read_json(path)!=value:raise Refused('Retained request differs from its content identity')
    return str(path)


def command(name, arguments, root):
    """Map a focused tool to the same CLI operation used by Claude."""
    def text(key, required=False):
        value=arguments.get(key)
        if value is None and not required:return None
        if not isinstance(value,str) or not value.strip():raise Refused(f'`{key}` must be text')
        return value
    if name not in NAMES:raise Refused('Unknown tool')
    if name=='status':
        if 'saved' in arguments and not isinstance(arguments['saved'],bool):raise Refused('saved must be boolean')
        return ['status']+(['--saved'] if arguments.get('saved') else [])
    if name in ('config','candidate'):return [name]
    if name=='resume':return ['resume']+(['--run',text('run')] if text('run') else [])+(['--human',payload(root,arguments['human'])] if arguments.get('human') is not None else [])
    if name=='admission':return ['admission','--',text('attempt_directory',True)]
    if name=='init':return ['init']+([f'--name={text("name")}'] if text('name') else [])
    if name=='plans':
        if arguments.get('action') not in ('path','check','list'):raise Refused('Invalid plans action')
        return ['plans',arguments['action']]
    if name=='resource':return ['resource','--',text('path',True)]
    if name=='scope_prepare':
        workflow=arguments.get('workflow','deliver')
        if workflow not in ('deliver','design','propose'):raise Refused('Invalid workflow')
        args=['scope','prepare','--workflow',workflow]
        for key in ('doc','track'):
            if text(key):args+=[f'--{key}',text(key)]
        if arguments.get('human') is not None:args+=['--human',payload(root,arguments['human'])]
        if text('doc') and 'manifest' not in arguments:return args
        return args+['--',payload(root,arguments.get('manifest',{}))]
    if name=='scope_approve':return ['scope','approve','--',text('scope',True),payload(root,arguments.get('human'))]
    if name=='attempt_admit':
        role=arguments.get('role')
        if role not in ('assessment','implementation','analysis','review'):raise Refused('Invalid agent role')
        return ['attempt','admit',role]
    if name in ('attempt_bind','attempt_retain'):
        return ['attempt',name.split('_',1)[1],'--',text('attempt',True),payload(root,arguments.get('source'))]
    if name=='review_check':return ['review-check','--',payload(root,{'report':text('report',True)})]
    if name=='evidence':return ['evidence','--',payload(root,arguments.get('attachment'))]
    if name=='complete':return ['complete','--',text('attempt',True)]
    if name=='decision_request':
        args=['decision-request']
        for key in ('attempt','run','also'):
            if text(key):args+=['--'+key,text(key)]
        if 'rounds' in arguments:
            if type(arguments['rounds']) is not int or arguments['rounds']<1:raise Refused('rounds must be a positive whole number')
            args+=['--rounds',str(arguments['rounds'])]
        return args+['--',text('kind',True)]
    if name=='finding_track':
        return ['finding-track']+(['--destination',payload(root,arguments['destination'])] if arguments.get('destination') is not None else [])+['--',text('attempt',True)]
    if name=='decision':
        args=['decision']
        if text('attempt'):args+=['--attempt',text('attempt')]
        if arguments.get('destination') is not None:args+=['--destination',payload(root,arguments['destination'])]
        return args+['--',text('kind',True),payload(root,arguments.get('human'))]
    if name=='review':
        values=arguments.get('arguments') or []
        if not isinstance(values,list) or not all(isinstance(v,str) for v in values):raise Refused('arguments must be a list of text')
        return ['review']+(['--human',payload(root,arguments['human'])] if arguments.get('human') is not None else [])+['--',*values]
    if name=='verify':
        mode=arguments.get('mode','review')
        if mode not in ('review','pre-push','ci'):raise Refused('Invalid verification mode')
        if not text('base'):
            if mode!='review':raise Refused('Pass the comparison base when selecting a non-default verification mode')
            return ['verify']
        return ['verify','--',text('base'),mode]
    if name=='pr_summary':return ['pr-summary']+(['--',text('base')] if text('base') else [])
    if name=='ci_wait':
        argv=['ci-wait']
        for key in ('pr','timeout'):
            value=arguments.get(key)
            if value is None:continue
            if type(value) is not int or value<=0:raise Refused(f'`{key}` must be a positive whole number')
            argv+=['--'+key,str(value)]
        return argv
    if name=='publication':
        number=arguments.get('pr')
        if number is not None and (type(number) is not int or number<=0):raise Refused('The PR number must be positive')
        return ['publication']+(['--pr',str(number)] if number is not None else [])
    raise Refused('Unknown tool')


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
    from .authority import saved, Saving
    from .hosts import codex_home
    def read():
        files = list((codex_home() / 'sessions').rglob('*' + thread + '.jsonl'))
        if len(files) != 1:raise Saving('OH could not find this Codex conversation\'s saved session; retry the same OH operation.')
        # Native children may record checks, but their prompts cannot grant authority.
        # Resolve only checkout identity here; consequential helpers attest human input.
        with files[0].open('rb') as stream:
            try:record=json.loads(stream.readline())
            except ValueError:raise Saving('Codex is still saving this conversation.')
            meta=record.get('payload',{})
            if record.get('type')!='session_meta' or meta.get('id')!=thread:
                raise Refused('The native conversation identity does not match this call.')
            cwd=meta.get('cwd')
            for line in stream:
                try:record=json.loads(line)
                except ValueError:continue
                if record.get('type')=='turn_context':cwd=record.get('payload',{}).get('cwd') or cwd
        return cwd
    cwd = saved(read)
    if not isinstance(cwd, str) or not cwd:raise Refused('OH could not tell which folder this Codex conversation works in.')
    return Path(cwd).resolve()


def checkout(arguments, thread):
    """The checkout a tool acts on: the Git repository root, and the one the conversation works in, never a
    repository around it (a nested worktree, submodule or vendored repository has its own)."""
    from .authority import within
    from .storage import git
    root = arguments.get('root')
    if not isinstance(root, str) or not Path(root).is_absolute() or not Path(root).is_dir():
        raise Refused('Pass the absolute path of the project checkout as root.')
    root = Path(root).resolve()
    try:top = Path(git(root, 'rev-parse', '--show-toplevel')).resolve()
    except (Refused, OSError, subprocess.SubprocessError):top = None
    if top != root:raise Refused(f'{root} is not the root of a Git checkout.')
    if not within(folder(thread), root):
        raise Refused(f'This conversation does not work in {root}; OH acts only on the checkout the conversation is in.')
    return root


# OH's and the hosts' own settings: taken from what Codex passes this server, never from the person's shell.
FORWARDED = {'OH_DATA_HOME', 'XDG_CONFIG_HOME', 'CODEX_HOME', 'CLAUDE_CONFIG_DIR'}
MARK = '__OH_SHELL_ENVIRONMENT__'


def shell_environment():
    """The environment the person's login shell sets up, read once as terminals and editors do. Empty on Windows
    (Codex passes its environment through there) or when the shell can't be read in time."""
    if os.name == 'nt':return {}
    shell = os.environ.get('SHELL')
    if not shell:
        import pwd  # windows-ok: POSIX only, after the Windows return above
        shell = pwd.getpwuid(os.getuid()).pw_shell  # windows-ok: POSIX only
    if not shell or not Path(shell).is_absolute():return {}
    try:done = subprocess.run([shell, '-ilc', f'printf {MARK}; env -0'], stdin=subprocess.DEVNULL, capture_output=True, timeout=20)
    except (OSError, subprocess.SubprocessError):return {}
    if done.returncode or MARK.encode() not in done.stdout:return {}
    pairs = done.stdout.split(MARK.encode(), 1)[1].split(b'\0')
    return dict(p.decode('utf-8', 'replace').split('=', 1) for p in pairs if b'=' in p)


class Server:
    tools=TOOLS
    def __init__(self, stdin, stdout, launcher=None):
        self.stdin, self.stdout, self.launcher, self.client = stdin, stdout, launcher, {}
        self.lock, self.reading, self.cancelled, self.shell = threading.Lock(), threading.Lock(), {}, None

    def send(self, message):
        with self.lock:
            self.stdout.write(json.dumps({'jsonrpc': '2.0'} | message) + '\n');self.stdout.flush()

    def serve(self):
        """Read the host's messages. Tool calls run on their own threads, so the server keeps answering (a ping,
        a cancel) while a configured check is working."""
        for line in iter(self.stdin.readline, ''):
            try:message = json.loads(line)
            except ValueError:continue
            if not isinstance(message, dict):continue
            method, ident = message.get('method'), message.get('id')
            if method == 'notifications/cancelled':
                cancelled = self.cancelled.get((message.get('params') or {}).get('requestId'))
                if cancelled:cancelled.set()
            elif method == 'initialize':
                self.client = message.get('params') or {}
                self.send({'id': ident, 'result': {'protocolVersion': self.client.get('protocolVersion', VERSION),
                    'capabilities': {'tools': {}}, 'serverInfo': {'name': 'o-harness', 'version': '1'}}})
            elif method == 'tools/list':self.send({'id': ident, 'result': {'tools': self.tools}})
            elif method == 'tools/call':
                self.cancelled[ident] = threading.Event()
                threading.Thread(target=self.call, args=(message,), daemon=True).start()
            elif method == 'ping' and ident is not None:self.send({'id': ident, 'result': {}})
            elif method and ident is not None:self.send({'id': ident, 'error': {'code': -32601, 'message': 'Not supported'}})

    def call(self, message):
        ident, params = message['id'], message.get('params') or {}
        try:text, error = self.tool(params.get('name'), params.get('arguments') or {}, params.get('_meta') or {}, ident), False
        except (Refused, OSError, ValueError, KeyError) as exc:text, error = f'OH: {exc}', True
        except Exception as exc:text, error = f'OH failed unexpectedly: {exc!r}', True  # never leave a call unanswered
        cancelled = self.cancelled.pop(ident)
        # The host gave up on this call (the person interrupted it, or it timed out): it expects no reply.
        # Transport cancellation alone grants no workflow authority. Native Stop rollout is gated.
        if not cancelled.is_set():self.send({'id': ident, 'result': {'content': [{'type': 'text', 'text': text}], 'isError': error}})

    def tool(self, name, arguments, meta, ident):
        if name not in NAMES:raise Refused('Unknown tool')
        if not isinstance(arguments, dict):raise Refused('Arguments must be an object')
        thread = conversation(meta)
        root = checkout(arguments, thread)
        native=meta.get('x-codex-turn-metadata')
        turn=native.get('turn_id') if isinstance(native,dict) else None
        return self.oh(root, command(name, arguments, root), thread, meta.get('progressToken'), turn)

    def environment(self, thread, turn=None):
        """What an OH command gets in Codex's shell: the person's own shell setup (PATH additions, JAVA_HOME, proxies...),
        which Codex does not give this server, with Codex's forwarded values on top."""
        with self.reading:  # its own lock: replies to the host never wait for the shell
            if self.shell is None:self.shell = shell_environment()
        # OH's and the hosts' own settings come only from Codex, exactly as this server sees them, so a command
        # and the server always use the same OH state and Codex folder.
        environment=dict(os.environ) | {k: v for k, v in self.shell.items() if k not in FORWARDED} | {'CODEX_THREAD_ID': thread}
        environment.pop('OH_CODEX_TURN_ID',None)
        if isinstance(turn,str) and re.fullmatch(r'[a-zA-Z0-9_-]+',turn):environment['OH_CODEX_TURN_ID']=turn
        return environment

    def oh(self, root, argv, thread, token, turn=None):
        """Run a focused helper with the calling native conversation identity."""
        environment = self.environment(thread,turn)
        utf8 = ['-X', 'utf8'] if os.name == 'nt' else []
        process=subprocess.run([sys.executable,'-I',*utf8,str(self.launcher),'--root',str(root),*argv],
                               stdin=subprocess.DEVNULL,capture_output=True,env=environment,
                               text=True,encoding='utf-8',errors='replace')
        output=[process.stdout];lines=process.stderr.splitlines()
        code = process.returncode
        if code:
            said = [line[4:] for line in lines if line.startswith('OH: ')]
            raise Refused(said[-1] if said else '\n'.join(lines[-5:]) or f'OH exited with {code}')
        return ''.join(output).strip() or 'Done.'


def serve(stdin, stdout, launcher=None):
    Server(stdin, stdout, launcher).serve()
