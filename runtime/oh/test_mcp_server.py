import io
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
from . import test_workflow as fixtures
from .config import HOME
from .mcp_server import TOOLS, serve


def play(messages, respond=None, launcher=None):
    """Play the Codex host: send `messages`, answer each menu the server opens with `respond`, and hang up once
    every request has its response. Returns everything the server sent, in order."""
    output, pending, answered = io.StringIO(), list(messages), set()
    wanted = {m['id'] for m in messages if 'method' in m and 'id' in m}
    def sent():
        return [json.loads(line) for line in output.getvalue().split('\n')[:-1]]  # whole lines only
    class Host:
        def readline(self):
            deadline = time.monotonic() + 60
            while time.monotonic() < deadline:
                if pending:return json.dumps({'jsonrpc': '2.0'} | pending.pop(0)) + '\n'
                messages = sent()
                for m in messages:
                    if m.get('method') == 'elicitation/create' and m['id'] not in answered:
                        answered.add(m['id'])
                        return json.dumps({'jsonrpc': '2.0', 'id': m['id'], 'result': respond(m)}) + '\n'
                if wanted <= {m.get('id') for m in messages if 'method' not in m}:return ''
                time.sleep(0.01)
            return ''
    serve(Host(), output, launcher)
    return sent()


def codex_session(home, thread, cwd):
    """The session Codex saves for a conversation, which names the folder it works in."""
    path = home / '.codex/sessions/2026/09/28' / f'rollout-2026-09-28T00-00-00-{thread}.jsonl'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({'type': 'session_meta', 'payload': {'id': thread, 'cwd': str(cwd), 'source': 'cli'}}) + '\n', newline='\n')


def calling(thread, **extra):
    return {'_meta': {'x-codex-turn-metadata': {'thread_id': thread, 'turn_id': 'turn-1'}} | extra}


class CodexToolsTest(unittest.TestCase):
    setUp_workflow = fixtures.WorkflowTest.setUp
    git = fixtures.WorkflowTest.git

    def setUp(self):
        self.setUp_workflow()
        self.home = Path(self.temp.name).resolve() / 'home'
        patcher = patch('pathlib.Path.home', return_value=self.home);patcher.start();self.addCleanup(patcher.stop)
        environment = patch.dict(os.environ, {'CODEX_HOME': str(self.home / '.codex')});environment.start();self.addCleanup(environment.stop)
        codex_session(self.home, 't1', self.root)
        # A stand-in launcher that reports what it was asked to run, from which conversation.
        self.launcher = Path(self.temp.name) / 'oh-launcher'
        self.launcher.write_text(
            'import json,os,sys,time\n'
            'print("OH task 1: implementation", file=sys.stderr, flush=True)\n'
            'time.sleep(float(os.environ.get("FAKE_WAIT", "0")))\n'
            'if "fail" in sys.argv:print("OH: nothing to run", file=sys.stderr);sys.exit(2)\n'
            'print(json.dumps({"argv": sys.argv[1:], "thread": os.environ.get("CODEX_THREAD_ID")}))\n', newline='\n')

    def call(self, name, arguments, meta=None, launcher=None, ident=2):
        sent = play([{'id': 1, 'method': 'initialize', 'params': {'protocolVersion': '2025-06-18', 'capabilities': {}}},
                     {'id': ident, 'method': 'tools/call', 'params': {'name': name, 'arguments': arguments} | (calling('t1') if meta is None else meta)}],
                    launcher=launcher or self.launcher)
        result = next(m for m in sent if m.get('id') == ident)['result']
        return result['content'][0]['text'], result['isError']

    def test_tools_cover_everyday_commands_and_nothing_that_changes_what_oh_runs(self):
        names = {t['name'] for t in TOOLS}
        self.assertEqual(names, {'status', 'config', 'init', 'plans', 'resource', 'deliver', 'prepare', 'prepare_design',
                                 'start', 'run', 'pause', 'resume', 'stop', 'pr_summary', 'choose'})
        config = next(t for t in TOOLS if t['name'] == 'config')
        self.assertEqual(set(config['inputSchema']['properties']), {'root'})  # reading only: `config set` stays in the shell
        init = next(t for t in TOOLS if t['name'] == 'init')
        self.assertEqual(set(init['inputSchema']['properties']), {'root', 'name'})  # never --replace, --attach or --reattach

    def test_a_tool_runs_its_command_in_the_calling_conversation_and_values_stay_values(self):
        text, error = self.call('deliver', {'root': str(self.root), 'arguments': ['0005', '--root', '/elsewhere']})
        self.assertFalse(error)
        self.assertEqual(json.loads(text), {'argv': ['--root', str(self.root.resolve()), 'deliver', '--', '0005', '--root', '/elsewhere'], 'thread': 't1'})
        self.assertEqual(json.loads(self.call('init', {'root': str(self.root), 'name': '--replace'})[0])['argv'][-1], '--name=--replace')

    def test_a_real_command_runs_through_the_launcher(self):
        text, error = self.call('config', {'root': str(self.root)}, launcher=HOME / 'oh')
        self.assertFalse(error, text)
        self.assertEqual(json.loads(text)['checks'][0]['name'], 'fixture')

    def test_tools_act_only_on_the_checkout_of_the_conversation_that_calls(self):
        other = Path(self.temp.name) / 'other';other.mkdir()
        self.assertIn('works outside', self.call('status', {'root': str(other)})[0])
        self.assertIn('does not say which conversation', self.call('status', {'root': str(self.root)}, meta={})[0])
        self.assertIn('saved session', self.call('status', {'root': str(self.root)}, meta=calling('unknown'))[0])
        self.assertIn('absolute path', self.call('status', {'root': 'project'})[0])
        with patch.dict(os.environ, {'OH_CHILD_ATTEMPT': '1'}):
            self.assertIn('workers cannot', self.call('status', {'root': str(self.root)})[0])

    def test_prepare_saves_the_task_list_where_the_model_cannot_write(self):
        from .storage import project, read_json, state_home
        tasks = [{'id': '1', 'title': 'Fix', 'instructions': 'Fix it'}]
        argv = json.loads(self.call('prepare', {'root': str(self.root), 'tasks': tasks})[0])['argv']
        path = Path(argv[-1])
        self.assertTrue(path.is_relative_to(state_home() / 'projects' / project(self.root)['id']))
        self.assertEqual(read_json(path), {'tasks': tasks})

    def test_a_long_command_reports_progress_and_the_server_keeps_answering(self):
        with patch.dict(os.environ, {'FAKE_WAIT': '1'}):
            sent = play([{'id': 1, 'method': 'initialize', 'params': {'protocolVersion': '2025-06-18', 'capabilities': {}}},
                         {'id': 2, 'method': 'tools/call', 'params': {'name': 'run', 'arguments': {'root': str(self.root)}} | calling('t1', progressToken='p')},
                         {'id': 3, 'method': 'ping'}], launcher=self.launcher)
        order = [m.get('id') for m in sent if 'result' in m]
        self.assertLess(order.index(3), order.index(2))  # the ping was answered while the run worked
        progress = next(m for m in sent if m.get('method') == 'notifications/progress')
        self.assertEqual(progress['params'], {'progressToken': 'p', 'progress': 1, 'message': 'OH task 1: implementation'})

    def test_an_oh_refusal_is_the_tool_s_error(self):
        self.assertEqual(self.call('deliver', {'root': str(self.root), 'arguments': ['fail']}), ('OH: nothing to run', True))
