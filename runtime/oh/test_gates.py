import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from . import test_workflow as fixtures
from .authority import materialize, stage_click
from .config import HOME
from .gates import ask, current, pick
from .gate_server import serve
from .runner import run
from .storage import Refused
from .workflow import choose, human_event, load_run, start


class GateTest(unittest.TestCase):
    setUp_workflow = fixtures.WorkflowTest.setUp
    git = fixtures.WorkflowTest.git
    fake = fixtures.WorkflowTest.fake

    def setUp(self):
        self.setUp_workflow()
        self.home = Path(self.temp.name).resolve() / 'home'
        patcher = patch('pathlib.Path.home', return_value=self.home);patcher.start();self.addCleanup(patcher.stop)
        self.transcript = self.home / '.claude/projects/p/s.jsonl';self.transcript.parent.mkdir(parents=True)
        self.records = []

    def begin(self, host):
        prompt = 'oh start .oh/tasks.json'
        start(self.root, {'tasks': self.tasks}, human_event({'hook_event_name': 'UserPromptSubmit', 'session_id': 's', 'turn_id': '1', 'prompt': prompt}, host))
        return run(self.root, self.fake)

    def click(self, question, answer, use='toolu_1', session='s', prefilled=None):
        request = {'questions': [question]} | ({'answers': prefilled} if prefilled is not None else {})
        self.records += [
            {'type': 'assistant', 'sessionId': session, 'cwd': str(self.root), 'message': {'role': 'assistant', 'content': [
                {'type': 'tool_use', 'id': use, 'name': 'AskUserQuestion', 'input': request}]}},
            {'type': 'user', 'sessionId': session, 'cwd': str(self.root), 'timestamp': '2026-09-28T12:00:00Z',
             'toolUseResult': {'questions': [question], 'answers': {question['question']: answer}},
             'message': {'role': 'user', 'content': [{'type': 'tool_result', 'tool_use_id': use, 'content': 'answered'}]}}]
        self.transcript.write_text(''.join(json.dumps(r) + '\n' for r in self.records))
        stage_click(self.root, 'claude', {'hook_event_name': 'PostToolUse', 'tool_name': 'AskUserQuestion', 'session_id': session,
                                          'tool_use_id': use, 'transcript_path': str(self.transcript)})
        return materialize(self.root)

    def test_checkpoint_offers_its_choices_as_a_menu_that_expires_when_the_run_moves(self):
        result = self.begin('claude')
        self.assertEqual(result['gate']['choices'], ['continue', 'pr', 'stop'])
        question = result['gate']['ask']['questions'][0]
        self.assertEqual([o['label'] for o in question['options']], ['Continue', 'Open a PR', 'Stop'])
        self.assertIn('Continue runs 1 of the 1 remaining task', question['options'][0]['description'])
        self.assertIn('AskUserQuestion', result['gate']['how'])
        choose(self.root, 'continue', human_event({'hook_event_name': 'UserPromptSubmit', 'session_id': 's', 'turn_id': '2', 'prompt': 'continue'}, 'claude'))
        self.assertIsNone(current(self.root))  # running: nothing to choose
        after = run(self.root, self.fake)
        self.assertEqual(after['gate']['choices'], ['pr', 'stop'])
        self.assertNotEqual(after['gate']['id'], result['gate']['id'])

    def test_a_click_on_claude_is_read_from_its_transcript_and_applied(self):
        question = self.begin('claude')['gate']['ask']['questions'][0]
        self.assertEqual(self.click(question, 'Continue')['status'], 'running')
        _, state = load_run(self.root)
        self.assertEqual(state['granted'][-1], '6')

    def test_model_written_or_altered_or_foreign_answers_choose_nothing(self):
        question = self.begin('claude')['gate']['ask']['questions'][0]
        cases = [('prefilled', {'prefilled': {question['question']: 'Continue'}}),
                 ('other session', {'session': 'intruder'}),
                 ('altered menu', {'question': question | {'options': question['options'][:1] + [{'label': 'Stop', 'description': 'x'}]}})]
        for index, (name, change) in enumerate(cases):
            with self.subTest(name):
                with self.assertRaises(Refused):
                    self.click(change.pop('question', question), 'Continue', use=f'toolu_{index + 2}', **change)
                self.assertEqual(load_run(self.root)[1]['status'], 'checkpoint')
        with self.assertRaises(Refused):self.click(question, 'Just keep going', use='toolu_9')  # free text is no choice here
        self.assertEqual(load_run(self.root)[1]['status'], 'checkpoint')

    def test_stop_on_a_finished_run_closes_its_menu(self):
        question = self.begin('claude')['gate']['ask']['questions'][0]
        choose(self.root, 'continue', human_event({'hook_event_name': 'UserPromptSubmit', 'session_id': 's', 'turn_id': '2', 'prompt': 'continue'}, 'claude'))
        question = run(self.root, self.fake)['gate']['ask']['questions'][0]
        after = self.click(question, 'Stop', use='toolu_stop')
        self.assertEqual((after['status'], after.get('gate')), ('stopped', None))

    def test_a_click_on_an_older_menu_is_refused(self):
        question = self.begin('claude')['gate']['ask']['questions'][0]
        choose(self.root, 'continue', human_event({'hook_event_name': 'UserPromptSubmit', 'session_id': 's', 'turn_id': '2', 'prompt': 'continue'}, 'claude'))
        run(self.root, self.fake)
        with self.assertRaises(Refused):self.click(question, 'Stop')
        self.assertEqual(load_run(self.root)[1]['status'], 'completed')

    def test_free_text_is_a_change_request_only_where_one_is_allowed(self):
        gate = {'options': [{'choice': 'approve', 'label': 'Approve'}, {'choice': 'reconsider', 'label': 'Reconsider'}], 'words': True}
        self.assertEqual(pick(gate, 'approve'), 'approve')
        self.assertEqual(pick(gate, 'Make the title shorter'), 'refine: Make the title shorter')
        with self.assertRaises(Refused):pick(gate | {'words': False}, 'Make the title shorter')

    def test_the_hook_refuses_prefilled_answers_on_oh_menus_only(self):
        script = HOME / 'plugins/o-harness/scripts/gate-hook.py'
        def pre(question, **extra):
            payload = {'hook_event_name': 'PreToolUse', 'tool_input': {'questions': [{'question': question}]} | extra}
            return subprocess.run([sys.executable, str(script), 'pre'], input=json.dumps(payload), capture_output=True, text=True).stdout
        self.assertIn('deny', pre('Continue? [OH gate abc]', answers={'Continue? [OH gate abc]': 'Continue'}))
        self.assertEqual(pre('Continue? [OH gate abc]'), '')
        self.assertEqual(pre('Pick a colour', answers={'Pick a colour': 'Red'}), '')
        payload = {'hook_event_name': 'PreToolUse', 'tool_input': {'questions': [{'question': 'Continue? [OH gate abc]'}, {'question': 'Also?'}]}}
        self.assertIn('one question on its own', subprocess.run([sys.executable, str(script), 'pre'], input=json.dumps(payload), capture_output=True, text=True).stdout)

    def server(self, root, reply, capabilities=None):
        """Play the Codex host: answer the menu the server opens with `reply`."""
        output = io.StringIO()
        class Host:
            queue = [{'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {'protocolVersion': '2025-06-18',
                      'capabilities': {'elicitation': {}} if capabilities is None else capabilities}},
                     {'jsonrpc': '2.0', 'id': 2, 'method': 'tools/call', 'params': {'name': 'choose', 'arguments': {'root': str(root)}}}]
            def readline(self):
                if not self.queue:
                    opened = [json.loads(line) for line in output.getvalue().splitlines() if 'elicitation/create' in line]
                    if not opened or getattr(self, 'answered', False):return ''
                    self.answered = True
                    self.queue.append({'jsonrpc': '2.0', 'id': opened[-1]['id'], 'result': reply})
                return json.dumps(self.queue.pop(0)) + '\n'
        serve(Host(), output)
        sent = [json.loads(line) for line in output.getvalue().splitlines()]
        return sent, next(m for m in sent if m.get('id') == 2)['result']['content'][0]['text']

    def test_codex_menu_records_the_click_itself(self):
        self.begin('codex')
        sent, text = self.server(self.root, {'action': 'accept', 'content': {'choice': 'continue'}})
        asked = next(m for m in sent if m.get('method') == 'elicitation/create')
        self.assertEqual(asked['params']['requestedSchema']['properties']['choice']['enum'], ['continue', 'pr', 'stop'])
        self.assertIn('Recorded', text)
        self.assertIn(f'Project Fixture · {self.root.resolve()} · run ', asked['params']['message'])  # the person sees the target
        self.assertIn('Continue runs 1 of the 1 remaining task', asked['params']['message'])
        _, state = load_run(self.root)
        self.assertEqual((state['status'], state['granted'][-1]), ('running', '6'))

    def test_codex_menu_falls_back_to_typing_when_it_cannot_be_shown(self):
        self.begin('codex')
        for reply, capabilities in (({'action': 'decline'}, None), ({'action': 'cancel'}, None), ({}, {})):
            sent, text = self.server(self.root, reply, capabilities)
            self.assertIn('type one of: continue, pr, stop', text)
            self.assertEqual(load_run(self.root)[1]['status'], 'checkpoint')
        self.assertFalse(any(m.get('method') == 'elicitation/create' for m in sent))  # no capability: never asked

    def test_codex_menu_refuses_a_claude_run_and_a_relative_root(self):
        self.begin('claude')
        self.assertIn('belongs to Claude', self.server(self.root, {})[1])
        self.assertIn('absolute path', self.server(Path('project'), {})[1])

    def test_no_oh_command_reaches_the_menu_server(self):
        from .cli import main
        for argv in (['gate-server'], ['--', 'gate-server'], ['--root', str(self.root), '--', 'gate-server']):
            with self.subTest(argv), patch('sys.stderr', io.StringIO()), self.assertRaises(SystemExit):main(argv)

    def test_codex_menu_is_never_shown_to_workers_or_by_a_different_runtime(self):
        self.begin('codex')
        with patch.dict(os.environ, {'OH_CHILD_ATTEMPT': '1'}):
            self.assertIn('workers cannot ask', self.server(self.root, {'action': 'accept', 'content': {'choice': 'continue'}})[1])
        with patch('oh.config.version', return_value='another-revision'):
            sent, text = self.server(self.root, {'action': 'accept', 'content': {'choice': 'continue'}})
        self.assertIn('updated after this run started', text)
        self.assertFalse(any(m.get('method') == 'elicitation/create' for m in sent))
        self.assertEqual(load_run(self.root)[1]['status'], 'checkpoint')
        from .hosts import command
        config = self.home / '.codex/config.toml';config.parent.mkdir(parents=True)
        config.write_text('[plugins."o-harness@o-harness"]\nenabled = true\n[plugins."other@x"]\nenabled = true\n')
        with patch('oh.hosts.executable', return_value='codex'):
            args = command('codex', {'model': 'm', 'effort': 'low'}, self.root, 'implementation', None, 1000)
        self.assertIn('plugins."o-harness@o-harness".enabled=false', args)
        self.assertFalse(any('other@x' in a for a in args))

    def test_a_click_that_can_never_verify_is_set_aside_and_typing_still_works(self):
        from .authority import stage
        question = self.begin('claude')['gate']['ask']['questions'][0]
        self.records.append({'type': 'assistant', 'sessionId': 's', 'cwd': str(self.root), 'message': {'role': 'assistant', 'content': [
            {'type': 'tool_use', 'id': 'toolu_two', 'name': 'AskUserQuestion', 'input': {'questions': [question, question | {'question': 'Also?'}]}}]}})
        self.records.append({'type': 'user', 'sessionId': 's', 'cwd': str(self.root), 'toolUseResult': {'answers': {question['question']: 'Continue', 'Also?': 'Stop'}},
                             'message': {'role': 'user', 'content': [{'type': 'tool_result', 'tool_use_id': 'toolu_two', 'content': 'x'}]}})
        self.transcript.write_text(''.join(json.dumps(r) + '\n' for r in self.records))
        stage_click(self.root, 'claude', {'hook_event_name': 'PostToolUse', 'tool_name': 'AskUserQuestion', 'session_id': 's',
                                          'tool_use_id': 'toolu_two', 'transcript_path': str(self.transcript)})
        with self.assertRaises(Refused):materialize(self.root)
        self.assertEqual(load_run(self.root)[1]['status'], 'checkpoint')
        stage(self.root, 'claude', {'hook_event_name': 'UserPromptSubmit', 'session_id': 's', 'prompt_id': 't2', 'prompt': 'stop'})  # not blocked

    def test_each_host_gets_its_own_menu_mechanism(self):
        from .installation import build
        with tempfile.TemporaryDirectory() as name:
            for host in ('claude', 'codex'):
                plugin = Path(name) / host / 'o-harness';plugin.parent.mkdir()
                build(plugin, host)
                hooks = json.loads((plugin / 'hooks/hooks.json').read_text())['hooks']
                self.assertFalse((plugin / 'codex-mcp.json').exists())
                self.assertEqual((plugin / '.mcp.json').exists(), host == 'codex')
                self.assertEqual('PreToolUse' in hooks and 'PostToolUse' in hooks, host == 'claude')
                manifest = json.loads((plugin / '.codex-plugin/plugin.json').read_text())
                self.assertEqual(manifest.get('mcpServers'), './.mcp.json' if host == 'codex' else None)
