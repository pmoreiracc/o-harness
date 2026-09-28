import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
from . import test_workflow as fixtures
from .authority import materialize
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
        # A menu needs only one finished task and one left: every task a batch runs costs seconds of Git work.
        fixtures.configure(self.root, tasks_per_batch=1);self.tasks = self.tasks[:2]

    def begin(self, host):
        prompt = 'oh start .oh/tasks.json'
        start(self.root, {'tasks': self.tasks}, human_event({'hook_event_name': 'UserPromptSubmit', 'session_id': 's', 'turn_id': '1', 'prompt': prompt}, host))
        return run(self.root, self.fake)

    def click(self, question, answer, use='toolu_1', session='s', prefilled=None, questions=None, extra=None, raw=None, cwd=None, apply=True):
        """Save a question-tool call and the host's answer in the owner's transcript, as Claude does, then run OH."""
        from .storage import now
        time.sleep(0.01)  # a person answers later than OH's own records, never within the same millisecond
        request = {'questions': questions or [question]} | ({'answers': prefilled} if prefilled is not None else {}) | (extra or {})
        where = str(cwd or self.root)
        self.records += [
            {'type': 'assistant', 'sessionId': session, 'cwd': where, **({'wireToolInputs': {use: raw}} if raw else {}),
             'message': {'role': 'assistant', 'content': [{'type': 'tool_use', 'id': use, 'name': 'AskUserQuestion', 'input': request}]}},
            {'type': 'user', 'sessionId': session, 'cwd': where, 'timestamp': now(),
             'toolUseResult': {'questions': request['questions'], 'answers': {question['question']: answer}},
             'message': {'role': 'user', 'content': [{'type': 'tool_result', 'tool_use_id': use, 'content': 'answered'}]}}]
        self.transcript.write_text(''.join(json.dumps(r) + '\n' for r in self.records), newline='\n')
        return materialize(self.root) if apply else None

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
        self.assertEqual(state['granted'][-1], '2')

    def test_model_written_or_altered_or_foreign_answers_choose_nothing(self):
        question = self.begin('claude')['gate']['ask']['questions'][0]
        cases = [('prefilled', {'prefilled': {question['question']: 'Continue'}}),
                 ('another conversation', {'session': 'other'}),
                 ('altered menu', {'questions': [question | {'options': question['options'][:1] + [{'label': 'Stop', 'description': 'x'}]}]}),
                 ('mixed with another question', {'questions': [question, {'question': 'Also?'}]}),
                 ('extra input', {'extra': {'metadata': {'source': 'model'}}}),
                 ('raw input differs', {'raw': {'questions': [question], 'answers': {question['question']: 'Continue'}}})]
        for index, (name, change) in enumerate(cases):
            with self.subTest(name):
                self.assertIsNone(self.click(question, 'Continue', use=f'toolu_{index + 2}', **change))
                self.assertEqual(load_run(self.root)[1]['status'], 'checkpoint')
        with self.assertRaises(Refused):self.click(question, 'Just keep going', use='toolu_9')  # free text is no choice here
        self.assertIsNone(materialize(self.root))  # said once, then set aside
        self.assertEqual(self.click(question, 'Continue', use='toolu_10')['status'], 'running')

    def test_stop_on_a_finished_run_closes_its_menu(self):
        question = self.begin('claude')['gate']['ask']['questions'][0]
        choose(self.root, 'continue', human_event({'hook_event_name': 'UserPromptSubmit', 'session_id': 's', 'turn_id': '2', 'prompt': 'continue'}, 'claude'))
        question = run(self.root, self.fake)['gate']['ask']['questions'][0]
        after = self.click(question, 'Stop', use='toolu_stop')
        self.assertEqual((after['status'], after.get('gate')), ('stopped', None))

    def test_only_the_latest_click_on_the_current_menu_counts(self):
        question = self.begin('claude')['gate']['ask']['questions'][0]
        self.records += [
            {'type': 'assistant', 'sessionId': 's', 'cwd': str(self.root), 'message': {'role': 'assistant', 'content': [
                {'type': 'tool_use', 'id': 'toolu_first', 'name': 'AskUserQuestion', 'input': {'questions': [question]}}]}},
            {'type': 'user', 'sessionId': 's', 'cwd': str(self.root), 'toolUseResult': {'answers': {question['question']: 'Stop'}},
             'message': {'role': 'user', 'content': [{'type': 'tool_result', 'tool_use_id': 'toolu_first', 'content': 'x'}]}}]
        self.assertEqual(self.click(question, 'Continue', use='toolu_latest')['status'], 'running')  # the person changed their mind
        self.assertIsNone(materialize(self.root))  # the earlier Stop is on an older menu now: nothing re-applies it
        run(self.root, self.fake)
        self.assertEqual(load_run(self.root)[1]['status'], 'completed')

    def test_a_click_counts_from_a_subfolder_of_the_checkout(self):
        question = self.begin('claude')['gate']['ask']['questions'][0]
        (self.root / 'docs').mkdir()
        self.assertEqual(self.click(question, 'Continue', cwd=self.root / 'docs')['status'], 'running')

    def test_an_older_click_never_displaces_a_newer_typed_choice(self):
        from .authority import pending_file, stage
        question = self.begin('claude')['gate']['ask']['questions'][0]
        self.click(question, 'Continue', apply=False)  # clicked, but OH didn't run yet
        stage(self.root, 'claude', {'hook_event_name': 'UserPromptSubmit', 'session_id': 's', 'prompt_id': 'later', 'prompt': 'stop'})
        with self.assertRaises(Refused):materialize(self.root)  # the typed stop isn't saved yet: nothing happens
        self.assertTrue(pending_file(self.root).exists())
        self.assertEqual(load_run(self.root)[1]['status'], 'checkpoint')

    def typed(self, prompt, turn, cwd=None, save=True, extra=None):
        """The person types a choice: the prompt hook stages it, and Claude saves the turn."""
        from .authority import stage
        from .storage import now
        time.sleep(0.01)
        stage(self.root, 'claude', {'hook_event_name': 'UserPromptSubmit', 'session_id': 's', 'prompt_id': turn, 'prompt': prompt,
                                    'transcript_path': str(self.transcript)})
        if save:
            self.records.append({'type': 'user', 'sessionId': 's', 'promptId': turn, 'cwd': str(cwd or self.root), 'timestamp': now(),
                                 'message': {'role': 'user', 'content': prompt}} | (extra or {}))
            self.transcript.write_text(''.join(json.dumps(r) + '\n' for r in self.records), newline='\n')

    def activity(self):
        """Claude saves something later in the conversation, such as the agent's next tool call."""
        from .storage import now
        self.records.append({'type': 'assistant', 'sessionId': 's', 'cwd': str(self.root), 'timestamp': now(), 'message': {'role': 'assistant', 'content': []}})
        self.transcript.write_text(''.join(json.dumps(r) + '\n' for r in self.records), newline='\n')

    def test_the_latest_answer_wins_typed_or_clicked(self):
        question = self.begin('claude')['gate']['ask']['questions'][0]
        self.typed('continue', 'typed-1')
        self.assertEqual(self.click(question, 'Stop', use='toolu_later')['status'], 'stopped')  # the click came after the typing
        self.assertIsNone(materialize(self.root))  # the typed continue is spent, never replayed

    def test_a_typed_choice_after_a_click_wins(self):
        question = self.begin('claude')['gate']['ask']['questions'][0]
        self.click(question, 'Stop', apply=False)
        self.typed('continue', 'typed-2')
        self.assertEqual(materialize(self.root)['status'], 'running')

    def test_a_typed_choice_that_cannot_be_read_applies_nothing_older(self):
        from .authority import pending_file
        question = self.begin('claude')['gate']['ask']['questions'][0]
        self.click(question, 'Stop', apply=False)
        self.typed('continue', 'unread', save=False)  # typed after the click, but not saved where OH reads
        with self.assertRaises(Refused):materialize(self.root)  # Claude might still be saving it
        self.activity()  # the conversation moved on without it
        with self.assertRaisesRegex(Refused, 'could not read your typed choice'):materialize(self.root)
        self.assertFalse(pending_file(self.root).exists())
        self.assertIsNone(materialize(self.root))  # the older Stop click is set aside, never applied
        self.assertEqual(load_run(self.root)[1]['status'], 'checkpoint')
        self.assertEqual(self.click(question, 'Stop', use='toolu_again')['status'], 'stopped')  # choosing again works

    def test_typed_choices_count_as_saved_by_the_desktop_app_but_not_from_other_senders(self):
        desktop = {'origin': {'kind': 'human'}, 'turnOrigin': 'human', 'promptSource': 'sdk', 'entrypoint': 'claude-desktop'}
        self.begin('claude')
        for name, extra in (('another agent', {'origin': {'kind': 'peer'}}), ('a notification', {'promptSource': 'system'}),
                            ('an automated caller', {'entrypoint': 'sdk-cli'})):
            with self.subTest(name):
                self.typed('continue', 'from-' + name.split()[-1], extra=extra)
                with self.assertRaisesRegex(Refused, 'could not read'):materialize(self.root)
                self.assertEqual(load_run(self.root)[1]['status'], 'checkpoint')
        self.typed('continue', 'desktop', extra=desktop)
        self.assertEqual(materialize(self.root)['status'], 'running')

    def test_a_refused_latest_answer_never_lets_an_older_one_apply(self):
        question = self.begin('claude')['gate']['ask']['questions'][0]
        self.click(question, 'Continue', apply=False)
        self.typed('retry', 'typed-4')  # the person's latest answer, which this checkpoint refuses
        with self.assertRaises(Refused):materialize(self.root)
        self.assertIsNone(materialize(self.root))  # the older Continue click never takes its place
        self.assertEqual(load_run(self.root)[1]['status'], 'checkpoint')

    def test_answers_from_a_checkout_nested_inside_do_not_count(self):
        from .authority import within
        self.begin('claude')
        nested = self.root / '.claude/worktrees/other';nested.mkdir(parents=True);(nested / '.git').write_text('gitdir: elsewhere')
        self.assertFalse(within(nested, self.root));self.assertTrue(within(self.root / 'docs', self.root))
        self.typed('continue', 'typed-5', cwd=nested)
        with self.assertRaisesRegex(Refused, 'could not read'):materialize(self.root)  # said, never applied
        self.assertEqual(load_run(self.root)[1]['status'], 'checkpoint')

    def test_a_typed_choice_from_a_subfolder_verifies(self):
        self.begin('claude')
        (self.root / 'docs').mkdir()
        self.typed('continue', 'typed-3', cwd=self.root / 'docs')
        self.assertEqual(materialize(self.root)['status'], 'running')

    def test_a_forged_typed_choice_grants_nothing(self):
        from .authority import stage
        question = self.begin('claude')['gate']['ask']['questions'][0]
        stage(self.root, 'claude', {'hook_event_name': 'UserPromptSubmit', 'session_id': 's', 'prompt_id': 'forged', 'prompt': 'continue'})
        with self.assertRaises(Refused):self.click(question, 'Stop')  # the forged turn never verifies, so nothing applies
        self.assertEqual(load_run(self.root)[1]['status'], 'checkpoint')
        self.assertEqual(self.click(question, 'Stop', use='toolu_again')['status'], 'stopped')

    def test_an_applied_answer_clears_an_old_refusal_and_counts_the_owner_conversation(self):
        from .authority import refusal_file
        from .storage import atomic_json, digest, read_json, state_home
        question = self.begin('claude')['gate']['ask']['questions'][0]
        atomic_json(refusal_file(self.root), {'refused': 'an older command'})
        self.assertEqual(self.click(question, 'Continue')['status'], 'running')
        self.assertFalse(refusal_file(self.root).exists())
        source = read_json(state_home() / 'sources' / (digest({'host': 'claude', 'session': 's'}) + '.json'))
        self.assertEqual((source['run'], source['path']), (load_run(self.root)[1]['id'], str(self.transcript)))

    def test_free_text_is_a_change_request_only_where_one_is_allowed(self):
        gate = {'options': [{'choice': 'approve', 'label': 'Approve'}, {'choice': 'reconsider', 'label': 'Reconsider'}], 'words': True}
        self.assertEqual(pick(gate, 'approve'), 'approve')
        self.assertEqual(pick(gate, 'Make the title shorter'), 'refine: Make the title shorter')
        self.assertEqual(pick(gate, 'refine: shorter title'), 'refine: shorter title')
        for command in ('stop', 'Stop', 'pause', 'continue', '/oh-stop', '$oh-deliver 0001'):
            with self.subTest(command), self.assertRaises(Refused):pick(gate, command)  # a command, never a change request
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

    def server(self, root, reply, capabilities=None, while_open=None):
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
                    if while_open:while_open()
                    self.queue.append({'jsonrpc': '2.0', 'id': opened[-1]['id'], 'result': reply})
                return json.dumps(self.queue.pop(0)) + '\n'
        serve(Host(), output)
        sent = [json.loads(line) for line in output.getvalue().splitlines()]
        return sent, next(m for m in sent if m.get('id') == 2)['result']['content'][0]['text']

    def test_codex_menu_records_the_click_itself(self):
        from .authority import refusal_file
        from .storage import atomic_json
        self.begin('codex')
        atomic_json(refusal_file(self.root), {'refused': 'an older command'})
        sent, text = self.server(self.root, {'action': 'accept', 'content': {'choice': 'continue'}})
        asked = next(m for m in sent if m.get('method') == 'elicitation/create')
        self.assertEqual(asked['params']['requestedSchema']['properties']['choice']['enum'], ['continue', 'pr', 'stop'])
        self.assertIn('Recorded', text)
        self.assertFalse(refusal_file(self.root).exists())
        self.assertIn(f'Project Fixture · {self.root.resolve()} · run ', asked['params']['message'])  # the person sees the target
        self.assertIn('Continue runs 1 of the 1 remaining task', asked['params']['message'])
        _, state = load_run(self.root)
        self.assertEqual((state['status'], state['granted'][-1]), ('running', '2'))

    def test_codex_latest_answer_wins_between_typing_and_the_menu(self):
        from .authority import pending_file, stage
        self.begin('codex')
        typed = {'hook_event_name': 'UserPromptSubmit', 'session_id': 's', 'turn_id': 't1', 'prompt': 'stop'}
        stage(self.root, 'codex', typed)
        self.assertIn('already typed a choice', self.server(self.root, {'action': 'accept', 'content': {'choice': 'continue'}})[1])
        pending_file(self.root).unlink()
        sent, text = self.server(self.root, {'action': 'accept', 'content': {'choice': 'continue'}},
                                 while_open=lambda: stage(self.root, 'codex', typed | {'turn_id': 't2'}))
        self.assertIn('Recorded', text)  # typed while the menu was open, so older than the click
        self.assertFalse(pending_file(self.root).exists())
        self.assertEqual(load_run(self.root)[1]['status'], 'running')

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
        config = self.home / 'codex-home/config.toml';config.parent.mkdir(parents=True)
        config.write_text('[plugins."o-harness@o-harness"]\nenabled = true\n[plugins."other@x"]\nenabled = true\n', newline='\n')
        with patch('oh.hosts.executable', return_value='codex'), patch.dict(os.environ, {'CODEX_HOME': str(config.parent)}):
            args = command('codex', {'model': 'm', 'effort': 'low'}, self.root, 'implementation', None, 1000)
        self.assertIn('plugins."o-harness@o-harness".enabled=false', args)
        self.assertFalse(any('other@x' in a for a in args))

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
                if host == 'codex':  # Codex clears a server's environment: OH's worker marker and data home are passed on
                    server = json.loads((plugin / '.mcp.json').read_text())['mcpServers']['o-harness']
                    self.assertEqual(server['env_vars'], ['OH_CHILD_ATTEMPT', 'OH_DATA_HOME'])
