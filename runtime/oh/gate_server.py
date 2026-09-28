"""OH's MCP server for Codex: the `choose` tool shows the choice OH is waiting for as a native menu
(MCP elicitation) and records the click itself. The answer travels from the host's menu to this process;
the model only learns what was recorded. Codex starts the server from the plugin; it is not an `oh`
command, so allowing `oh` commands never lets a model run it outside its sandbox."""
import json
from pathlib import Path
from .storage import Refused, identifier, now

VERSION = '2025-06-18'
TOOL = {'name': 'choose', 'title': 'Ask the person to choose',
        'description': ('Shows the person the choice OH is waiting for in this checkout (continue, approve, stop...) '
                        'as a menu, and records their click in OH. Call it when OH output has a `gate`. '
                        'The result says what was recorded; then run OH `run`.'),
        'inputSchema': {'type': 'object', 'required': ['root'], 'additionalProperties': False,
                        'properties': {'root': {'type': 'string', 'description': 'Absolute path of the project checkout'}}},
        'annotations': {'readOnlyHint': False, 'destructiveHint': False, 'idempotentHint': False, 'openWorldHint': False}}


class Server:
    def __init__(self, stdin, stdout):
        self.stdin, self.stdout, self.client, self.calls = stdin, stdout, {}, 0

    def send(self, message):
        self.stdout.write(json.dumps({'jsonrpc': '2.0'} | message) + '\n');self.stdout.flush()

    def receive(self):
        while True:
            line = self.stdin.readline()
            if not line:raise EOFError
            try:message = json.loads(line)
            except ValueError:continue
            if isinstance(message, dict):return message

    def other(self, message):
        """Answer requests that arrive while a menu is open, so the host never waits on us."""
        if message.get('method') == 'ping' and 'id' in message:self.send({'id': message['id'], 'result': {}})
        elif 'id' in message and 'method' in message:self.send({'id': message['id'], 'error': {'code': -32601, 'message': 'Not supported'}})

    def elicit(self, message, schema, call):
        self.calls += 1
        ident = f'oh-menu-{self.calls}'
        self.send({'id': ident, 'method': 'elicitation/create', 'params': {'message': message, 'requestedSchema': schema}})
        while True:
            reply = self.receive()
            if reply.get('id') == ident and 'method' not in reply:return reply
            if reply.get('method') == 'notifications/cancelled' and (reply.get('params') or {}).get('requestId') == call:return {'result': {'action': 'cancel'}}
            self.other(reply)

    def choose(self, arguments, call):
        from .gates import apply, current
        root = (arguments or {}).get('root')
        if not isinstance(root, str) or not Path(root).is_absolute() or not Path(root).is_dir():
            raise Refused('Pass the absolute path of the project checkout as root.')
        root = Path(root).resolve()
        gate = current(root)
        if not gate:return 'No OH choice is waiting in this checkout.'
        if gate['host'] != 'codex':raise Refused('This run belongs to Claude; ask there.')
        typed = ', '.join(o['choice'] for o in gate['options']) + (', or refine: <what to change>' if gate['words'] else '')
        fallback = f'No choice was made. Ask the person to type one of: {typed}.'
        if 'elicitation' not in (self.client.get('capabilities') or {}):
            return 'This Codex surface cannot show OH menus. ' + fallback
        menu = gate['options'] + ([{'choice': 'refine', 'label': 'Refine', 'description': ''}] if gate['words'] else [])
        properties = {'choice': {'type': 'string', 'title': 'Your choice', 'enum': [o['choice'] for o in menu],
                                 'enumNames': [o['label'] for o in menu]}}
        if gate['words']:
            properties['changes'] = {'type': 'string', 'title': 'What to change (only for Refine)'}
        details = '\n'.join(f'- {o["label"]}: {o["description"]}' for o in gate['options'] if o['description'] != o['label'])
        message = gate['question'].split(' [')[0] + ('\n' + details if details else '')
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
        from .workflow import load_run
        _, state = load_run(root)
        # Codex does not tell an MCP server which conversation called it: the click binds to this run's
        # own conversation, the menu it answered and the host.
        event = {'host': 'codex', 'session': state['human']['session'], 'turn': 'menu-' + identifier(),
                 'prompt': choice, 'via': 'elicitation', 'at': now()}
        after = apply(root, event, gate['id'])
        label = next((o['label'] for o in menu if o['choice'] == choice.split(':')[0]), choice)
        return f'Recorded the person\'s choice: {label}. Run OH `run` to carry it out. Status now: {after["status"]}.'

    def serve(self):
        while True:
            try:message = self.receive()
            except EOFError:return
            method, ident = message.get('method'), message.get('id')
            if method == 'initialize':
                self.client = message.get('params') or {}
                self.send({'id': ident, 'result': {'protocolVersion': self.client.get('protocolVersion', VERSION),
                    'capabilities': {'tools': {}}, 'serverInfo': {'name': 'o-harness', 'version': '1'}}})
            elif method == 'tools/list':self.send({'id': ident, 'result': {'tools': [TOOL]}})
            elif method == 'tools/call':
                params = message.get('params') or {}
                try:
                    if params.get('name') != 'choose':raise Refused('Unknown tool')
                    text, error = self.choose(params.get('arguments'), ident), False
                except EOFError:return
                except (Refused, OSError, ValueError, KeyError) as exc:text, error = f'OH: {exc}', True
                self.send({'id': ident, 'result': {'content': [{'type': 'text', 'text': text}], 'isError': error}})
            else:self.other(message)


def serve(stdin, stdout):
    Server(stdin, stdout).serve()
