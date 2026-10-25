import json
from datetime import datetime, timedelta
import os
from pathlib import Path
import shutil
import shlex
import subprocess
import sys
import threading
import time
import unittest
from unittest.mock import patch

from . import authority, cancellation, native
from .authority import coordinator as native_coordinator
from .storage import Refused, identifier, now
from .test_workflow import NativeFixture, configure
from .workflow import load_run


class CancellationTest(NativeFixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        def cleanup():
            value = cancellation._read(self.root)
            for tool in (value or {}).get('tools', {}).values():
                if tool.get('receipt'):
                    shutil.rmtree(tool['receipt'], ignore_errors=True)
        self.addCleanup(cleanup)

    def launch(self, role='assessment', turn='running-turn'):
        admitted = native.admit(self.root, role)
        native.bind(self.root, admitted['id'], {'child_session': 'worker-' + admitted['id']})
        self.attempt = admitted['id']
        self.worker = 'worker-' + self.attempt
        self.tool('admission', {'attempt_directory': str(Path(admitted['request']).parent)}, use='admission')
        cancellation.hook(self.root, 'codex', {
            'hook_event_name': 'PostToolUse', 'session_id': 's', 'agent_id': self.worker,
            'tool_use_id': 'admission', 'tool_name': 'admission'})
        cancellation.hook(self.root, 'codex', {
            'hook_event_name': 'PreToolUse', 'session_id': 's',
            'turn_id': turn, 'tool_name': 'collaborationwait_agent',
            'tool_input': {}, 'tool_use_id': 'wait'})
        return admitted

    def stop(self, turn='running-turn', session='s', path=None):
        identity = (session, turn)
        if identity not in getattr(self, 'stops', set()):
            self.stops = getattr(self, 'stops', set()) | {identity}
            with (path or self.parent_path).open('a', newline='\n') as stream:
                stream.write(json.dumps({'type': 'event_msg', 'timestamp': now(), 'payload': {
                    'type': 'turn_aborted', 'turn_id': turn, 'reason': 'interrupted'}}) + '\n')
        return cancellation.hook(self.root, 'codex', {
            'hook_event_name': 'Interrupt', 'session_id': session, 'turn_id': turn})

    def tool(self, name, args=None, use='tool', worker=None):
        return cancellation.hook(self.root, 'codex', {
            'hook_event_name': 'PreToolUse', 'session_id': 's',
            'turn_id': 'worker-turn', 'agent_id': worker or self.worker,
            'tool_name': name, 'tool_input': args or {}, 'tool_use_id': use})

    @unittest.skipUnless(os.name == 'nt', 'Windows hook shell contract')
    def test_packaged_windows_hooks_reserve_commands_and_revoke_workers(self):
        from .installation import build
        plugin = Path(self.temp.name) / 'plugin with spaces & %OH_HOOK_PATH_TEST% !' / 'o-harness'
        environment = patch.dict(os.environ, {'OH_HOOK_PATH_TEST': 'must-not-expand'})
        environment.start(); self.addCleanup(environment.stop)
        build(plugin, 'codex')
        installed = subprocess.run([sys.executable, '-I', str(plugin / 'core/oh'),
                                    'setup', '--development'], capture_output=True, text=True)
        self.assertEqual(installed.returncode, 0, installed.stderr)
        hooks = json.loads((plugin / 'hooks/hooks.json').read_text())['hooks']
        self.approve();self.launch()
        data = Path(os.environ['OH_DATA_HOME'])
        revision = json.loads((data / 'runtime/active.json').read_text())['revision']
        home = patch('oh.config.HOME', data / 'versions' / revision);home.start();self.addCleanup(home.stop)
        shells = [[str(Path(os.environ['SystemRoot']) / 'System32/WindowsPowerShell/v1.0/powershell.exe'),
                   '-NoProfile', '-Command']]
        if shutil.which('pwsh'):
            shells.append([shutil.which('pwsh'), '-NoProfile', '-Command'])
        shells.append(None)  # Codex's default cmd runner uses a raw outer quote pair.
        def invoke(shell, event, payload, group=-1):
            hook = hooks[event][group]['hooks'][0]
            command = hook['commandWindows']
            args = [*shell, command] if shell else f'"{os.environ["COMSPEC"]}" /d /s /c "{command}"'
            called = subprocess.run(args, input=json.dumps(payload | {'hook_event_name': event,
                'cwd': str(self.root)}), env=os.environ | {'PLUGIN_ROOT': str(plugin)},
                capture_output=True, text=True, encoding='utf-8', timeout=hook['timeout'])
            self.assertEqual(called.returncode, 0, called.stderr)
            self.assertEqual(called.stderr, '')
            return json.loads(called.stdout) if called.stdout.strip() else {}
        for index, shell in enumerate(shells):
            with self.subTest(shell=shell):
                argv = [sys.executable, '-c', f'print("reserved-{index}")']
                payload = {'session_id': 's', 'agent_id': self.worker, 'turn_id': 'worker-turn',
                           'tool_use_id': f'windows-command-{index}', 'tool_name': 'Bash',
                           'tool_input': {'command': cancellation.command_line(self.root, self.attempt, argv, windows=True)}}
                result = invoke(shell, 'PreToolUse', payload)
                self.assertEqual(result, {}, result)
                # Execute the exact suggested worker command too, not just its
                # decoded Python argv; PowerShell 5 used to strip the JSON quotes.
                worker_shell = shell or shells[0]
                executed = subprocess.run([*worker_shell, payload['tool_input']['command']],
                                          capture_output=True, text=True)
                self.assertEqual(executed.returncode, 0, executed.stderr)
                self.assertEqual(executed.stdout.strip(), f'reserved-{index}')
                invoke(shell, 'PostToolUse', payload)
        # Exercise the other generated entry points without creating human authority.
        invoke(shells[0], 'UserPromptSubmit', {})
        invoke(shells[0], 'PreToolUse', {}, group=0)
        invoke(shells[0], 'SubagentStart', {'session_id': 's', 'agent_id': self.worker})
        for shell in shells:
            invoke(shell, 'Interrupt', {'session_id': 's', 'turn_id': 'running-turn'})
        denied = invoke(shells[0], 'PreToolUse', payload)
        self.assertEqual(denied['hookSpecificOutput']['permissionDecision'], 'deny')
        self.assertIsNotNone(cancellation.interrupted(self.root, attempt=self.attempt))

    def test_stop_and_resume_keep_old_worker_revoked_in_same_and_other_conversations(self):
        # Drive the native tool boundary and the real human-answer parser, rather
        # than jumping directly from a stopped attempt into native.resume().
        host_home = Path(self.temp.name) / 'host'
        sessions = host_home / 'sessions'
        sessions.mkdir(parents=True)
        self.parent_path = sessions / 's.jsonl'
        self.parent_path.write_text(json.dumps({'type': 'session_meta', 'payload': {
            'id': 's', 'source': 'vscode', 'cwd': str(self.root)}}) + '\n', newline='\n')
        from .installation import build
        plugin = Path(self.temp.name) / 'plugin' / 'o-harness'
        build(plugin, 'codex')
        installed = subprocess.run([sys.executable, '-I', str(plugin / 'core' / 'oh'),
                                    'setup', '--development'], capture_output=True, text=True)
        self.assertEqual(installed.returncode, 0, installed.stderr)
        def parent_tool(session, turn, name, args=None):
            payload = {'hook_event_name': 'PreToolUse', 'cwd': str(self.root),
                       'session_id': session, 'turn_id': turn, 'tool_name': name,
                       'tool_input': args or {}, 'tool_use_id': identifier()}
            called = subprocess.run([sys.executable, '-I', str(plugin / 'scripts' / 'native-control.py'), 'codex'],
                                    input=json.dumps(payload), capture_output=True, text=True, timeout=5)
            self.assertEqual(called.returncode, 0, called.stderr)
            self.assertEqual(called.stderr, '')
            result = json.loads(called.stdout)
            self.assertEqual(result, {}, (session, turn, name, result))
        def recover(session):
            from .decisions import prepare
            path = sessions / (session + '.jsonl')
            turn, use = identifier(), identifier()
            def append(record):
                with path.open('a', newline='\n') as stream:
                    stream.write(json.dumps(record) + '\n')
            if not path.exists():
                append({'type': 'session_meta', 'payload': {
                    'id': session, 'source': 'vscode', 'cwd': str(self.root)}})
            append({'type': 'event_msg', 'timestamp': now(), 'payload': {
                'type': 'user_message', 'turn_id': turn, 'message': '/oh-deliver same-work'}})
            for name in ('mcp__o_harness__status', 'collaborationlist_agents',
                         'mcp__o_harness__resource', 'mcp__o_harness__resume',
                         'mcp__o_harness__decision_request'):
                parent_tool(session, turn, name)
            prepared = prepare(self.root, 'resume')
            args = {'questions': [{'title': prepared['question'], 'options': prepared['options']}]}
            parent_tool(session, turn, 'request_user_input_async', args)
            # Preparing and displaying a question cannot launch replacement work.
            before_answer = len(load_run(self.root)[1]['attempts'])
            with self.assertRaises(Refused):
                native.admit(self.root, 'assessment')
            append({'type': 'response_item', 'timestamp': now(), 'payload': {
                'type': 'function_call', 'name': 'request_user_input_async',
                'call_id': use, 'arguments': json.dumps(args)}})
            answer = '<send_user_message_question_reply>\n' + json.dumps([{
                'questionItemId': json.dumps(['request_user_input_async', use, 0]),
                'question': prepared['question'], 'answer': 'Resume saved work'
            }]) + '\n</send_user_message_question_reply>\n'
            append({'type': 'event_msg', 'timestamp': now(), 'payload': {
                'type': 'item_completed', 'thread_id': session, 'turn_id': turn,
                'item': {'type': 'UserMessage', 'id': identifier(),
                         'content': [{'type': 'text', 'text': answer}]}}})
            locator = {'host': 'codex', 'session': session, 'decision': prepared['decision']}
            parent_tool(session, turn, 'mcp__o_harness__resume', {'human': locator})
            with patch.dict(os.environ, {'CODEX_HOME': str(host_home), 'CODEX_THREAD_ID': session}), \
                    patch('oh.authority.native_human', side_effect=self.native_human_original), \
                    patch('oh.authority.coordinator', side_effect=native_coordinator):
                native.resume(self.root, locator)
                # Replaying the same accepted answer has no extra charge or transfer.
                records = load_run(self.root)[0].records()
                native.resume(self.root, locator)
                self.assertEqual(load_run(self.root)[0].records(), records)
            self.assertEqual(len(load_run(self.root)[1]['attempts']), before_answer)
            for name in ('mcp__o_harness__status', 'mcp__o_harness__resource',
                         'mcp__o_harness__attempt_admit'):
                parent_tool(session, turn, name)
            return turn
        self.approve()
        self.launch()
        old = self.attempt
        partial = self.root / 'partial.txt'
        partial.write_text('keep this')
        self.stop()
        self.native_results[old] = {'text': 'Old worker claims success', 'status': 'completed'}
        self.assertEqual(native.select(self.root)['status'], 'stopped')
        self.assertEqual(self.tool('apply_patch')['hookSpecificOutput']['permissionDecision'], 'deny')
        before = load_run(self.root)[1]['granted']
        fresh_turn = recover('s')
        state = load_run(self.root)[1]
        self.assertEqual(state['human']['session'], 's')
        self.assertEqual(state['attempts'][0]['outcome'], 'cancelled')
        self.assertEqual(state['granted'], before)
        self.assertEqual(partial.read_text(), 'keep this')
        fresh = native.admit(self.root, 'assessment')
        native.bind(self.root, fresh['id'], {'child_session': 'fresh-worker'})
        cancellation.hook(self.root, 'codex', {
            'hook_event_name': 'PreToolUse', 'session_id': 's', 'turn_id': fresh_turn,
            'tool_name': 'collaborationwait_agent', 'tool_input': {}, 'tool_use_id': 'fresh-wait'})
        self.stop()  # Duplicate old interruption must not revoke the fresh attempt.
        self.assertIsNone(cancellation.interrupted(self.root, attempt=fresh['id']))
        self.assertEqual(self.tool('apply_patch')['hookSpecificOutput']['permissionDecision'], 'deny')
        self.stop(fresh_turn)
        self.native_results[fresh['id']] = {'text': '', 'status': 'cancelled'}
        other_turn = recover('new-parent')
        state = load_run(self.root)[1]
        self.assertEqual(state['human']['session'], 'new-parent')
        self.assertEqual(state['granted'], before)
        self.assertEqual([a['outcome'] for a in state['attempts']], ['cancelled', 'cancelled'])
        denied = cancellation.hook(self.root, 'codex', {
            'hook_event_name': 'PreToolUse', 'session_id': 's', 'turn_id': 'running-turn',
            'tool_name': 'apply_patch', 'tool_input': {}, 'tool_use_id': 'old-parent-edit'})
        self.assertEqual(denied['hookSpecificOutput']['permissionDecision'], 'deny')
        # Continue the recovered run through its real checks, review receipt and
        # completion. Native model results are fixtures; workflow gates are not.
        parent_tool('new-parent', other_turn, 'mcp__o_harness__attempt_admit')
        self.assess()
        self.implement()
        parent_tool('new-parent', other_turn, 'mcp__o_harness__verify')
        reviewed = self.reviewed('Review complete.\nOH-REVIEW-DECISION: {"verdict":"clean","findings":[]}\n'
                                 'Checked the exact recovered candidate and its retained partial work.')
        parent_tool('new-parent', other_turn, 'mcp__o_harness__complete')
        native.complete(self.root, reviewed['id'])
        final = load_run(self.root)[1]
        self.assertEqual(len(final['done']), 1)
        self.assertEqual(sum(a['role'] == 'review' for a in final['attempts']), 1)
        self.assertEqual(partial.read_text(), 'keep this')
        self.assertFalse(final.get('published'))

    def test_command_stop_kills_owned_descendants_and_returns_cancellation(self):
        self.approve()
        self.launch()
        heartbeat = self.root / 'heartbeat'
        descendant = 'import sys,time\nwhile True:\n open(sys.argv[1],"a").write(".");time.sleep(.03)'
        leader = ('import subprocess,sys,time;'
                  'subprocess.Popen([sys.executable,"-c",sys.argv[1],sys.argv[2]]);time.sleep(30)')
        argv = [sys.executable, '-c', leader, descendant, str(heartbeat)]
        line = cancellation.command_line(self.root, self.attempt, argv)
        self.assertEqual(self.tool('Bash', {'command': line}, use='command'), {})
        invocation = cancellation.command_prefix(self.root, self.attempt) + [json.dumps(argv)]
        if sys.platform == 'darwin':
            # The native shell must not need permission to write OH's private state.
            policy = '(version 1)(allow default)(deny file-write* (subpath ' + json.dumps(os.environ['OH_DATA_HOME']) + '))'
            invocation = ['/usr/bin/sandbox-exec', '-p', policy, *invocation]
        child = subprocess.Popen(invocation, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            end = time.monotonic() + 5
            while not heartbeat.exists() and child.poll() is None and time.monotonic() < end:
                time.sleep(.02)
            if child.poll() is not None:
                stdout, stderr = child.communicate()
                self.fail('Owned command exited before starting: ' + stdout + stderr)
            self.assertTrue(heartbeat.exists())
            self.stop()
        finally:
            self.stop()
            stdout, stderr = child.communicate(timeout=10)
        self.assertEqual(child.returncode, 130, stdout + stderr)
        size = heartbeat.stat().st_size
        time.sleep(.15)
        self.assertEqual(heartbeat.stat().st_size, size)
        self.assertTrue(cancellation.quiescent(self.root, self.attempt))
        self.assertEqual(self.tool('Bash', {'command': line})['hookSpecificOutput']['permissionDecision'], 'deny')
        self.assertEqual(self.tool('exec_command', {'cmd': line})['hookSpecificOutput']['permissionDecision'], 'deny')
        # A reboot may remove the private temp receipt. An ended shell call or
        # missing directory is insufficient; only a verified later boot settles it.
        receipt = Path(cancellation._read(self.root)['tools']['command']['receipt'])
        shutil.rmtree(receipt)  # windows-ok: private temp JSON receipts, no Git objects or read-only files
        self.assertFalse(cancellation.quiescent(self.root, self.attempt))
        self.native_results[self.attempt] = {'status': 'cancelled', 'text': ''}
        answer = self.resume_choice()
        with patch('oh.system.boot_time', return_value=0):
            with self.assertRaisesRegex(Refused, 'cleanup is still pending'):
                native.resume(self.root, answer)
        with patch('oh.system.boot_time', return_value=time.time()+1):
            native.resume(self.root, answer)
        self.assertTrue(cancellation.quiescent(self.root, self.attempt))
        self.assertFalse(receipt.exists())

    def test_native_permissions_are_not_granted_and_literal_command_boundaries_are_checked(self):
        self.approve()
        self.launch()
        argv = [sys.executable, '-c', "print('a; b')"]
        for name, key in (('Bash', 'command'), ('PowerShell', 'command'),
                          ('exec_command', 'cmd'), ('functions.exec_command', 'cmd')):
            for windows in ((False, True) if os.name == 'nt' else (False,)):
                with self.subTest(name=name, windows=windows):
                    line = cancellation.command_line(self.root, self.attempt, argv, windows=windows)
                    use = name + str(windows)
                    self.assertEqual(self.tool(name, {key: line}, use=use), {})
                    self.assertEqual(cancellation._read(self.root)['tools'][use]['kind'], 'command')
                    for suffix in ('; echo unowned', ' && echo unowned', '\\necho unowned'):
                        self.assertEqual(self.tool(name, {key: line + suffix})['hookSpecificOutput']['permissionDecision'], 'deny')
            self.assertEqual(self.tool(name, {key: 'echo unowned'})['hookSpecificOutput']['permissionDecision'], 'deny')
            self.assertEqual(self.tool(name, {})['hookSpecificOutput']['permissionDecision'], 'deny')
        # A native exec_command reservation must be consumable by the actual wrapper.
        from .worker_checks import command_format
        literals=['C:\\a path\\quoted "value"',"single'quote",'', 'line\nnext','a; $(not executed)']
        native_argv = [sys.executable, '-X', 'utf8', '-c', 'import sys,json; print(json.dumps(sys.argv[1:]))',*literals]
        before=cancellation._read(self.root)
        from .config import HOME
        rendered=subprocess.run([sys.executable,'-I',str(HOME/'oh'),'--root',str(self.root),
                                 'command-format','--argv',json.dumps(native_argv),'--',self.attempt],
                                capture_output=True,text=True)
        self.assertEqual(rendered.returncode,0,rendered.stderr)
        formatted=json.loads(rendered.stdout)
        self.assertEqual(cancellation._read(self.root),before)  # formatting reserves and executes nothing
        native_line=formatted['powershell' if os.name=='nt' else 'bash']
        self.assertEqual(self.tool('exec_command', {'cmd': native_line}, use='native-command'), {})
        invocation = ['powershell.exe','-NoProfile','-Command',native_line] if os.name=='nt' else ['bash','-c',native_line]
        executed = subprocess.run(invocation, capture_output=True, text=True)
        self.assertEqual(executed.returncode, 0, executed.stderr)
        self.assertEqual(json.loads(executed.stdout),literals)
        with self.assertRaisesRegex(Refused, 'no native hook reservation'):
            cancellation.owned_command(self.root, self.attempt, ['unreserved-command'])
        # A read-only reviewer needs a direct helper call: no outer pipe and no
        # scratch-file edit merely to validate its final report.
        report = 'Review complete.\nOH-REVIEW-DECISION: {"verdict":"clean","findings":[]}\nChecked the candidate.'
        command = cancellation.command_prefix(self.root, self.attempt)[:-3] + ['review-check', '--text', report]
        self.assertEqual(self.tool('Bash', {'command': shlex.join(command)}, use='review-format'), {})
        checked = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(checked.returncode, 0, checked.stderr)
        self.assertTrue(json.loads(checked.stdout)['valid'])
        # A recovery instruction must execute in Claude's Bash on Windows too.
        # OS-based PowerShell guidance previously made the retry fail in Bash.
        from .system import executable
        guidance = cancellation._shell_guidance(command, 'claude', 'Bash')
        checked = subprocess.run([executable('bash'), '-c', guidance.removeprefix('Bash: ')],
                                 capture_output=True, text=True)
        self.assertEqual(checked.returncode, 0, checked.stderr)
        self.assertTrue(json.loads(checked.stdout)['valid'])
        if os.name == 'nt':
            # Native Bash agents also spell Windows helper paths with forward slashes.
            forward=[word.replace('\\','/') if os.path.isabs(word) else word for word in command]
            self.assertEqual(self.tool('Bash', {'command':shlex.join(forward)},use='forward-helper'),{})
            record=cancellation._read(self.root)['attempts'][self.attempt]
            admission=cancellation.command_prefix(self.root,self.attempt)[:-3]+['admission',record['directory']]
            admission=[word.replace('\\','/') if os.path.isabs(word) else word for word in admission]
            self.assertEqual(self.tool('Bash',{'command':shlex.join(admission)},use='forward-admission'),{})
            foreign=admission.copy();foreign[0]+='.other'
            self.assertEqual(self.tool('Bash',{'command':shlex.join(foreign)})['hookSpecificOutput']['permissionDecision'],'deny')
            owned=cancellation.command_prefix(self.root,self.attempt)
            owned=[word.replace('\\','/') if os.path.isabs(word) else word for word in owned]
            self.assertEqual(cancellation._owned_argv(self.root,self.attempt,shlex.join(owned+[json.dumps(argv)])),argv)
            guidance = cancellation._shell_guidance(command, 'codex', 'Bash')
            _, powershell = guidance.split('\nPowerShell: ', 1)
            checked = subprocess.run(['powershell.exe', '-NoProfile', '-Command', powershell],
                                     capture_output=True, text=True)
            self.assertEqual(checked.returncode, 0, checked.stderr)
            self.assertTrue(json.loads(checked.stdout)['valid'])
            invalid = cancellation.shell_line(command[:-1]+['No decision header.'],windows=True)
            checked = subprocess.run(['powershell.exe', '-NoProfile', '-Command', invalid],
                                     capture_output=True, text=True)
            self.assertNotEqual(checked.returncode,0,checked.stdout)
            missing = cancellation.shell_line([str(self.root/'absent-python.exe'), '--version'],windows=True)
            checked = subprocess.run(['powershell.exe', '-NoProfile', '-Command', missing],
                                     capture_output=True, text=True)
            self.assertNotEqual(checked.returncode,0,checked.stdout)
        self.stop()
        with self.assertRaises(Refused):command_format(self.root,self.attempt,native_argv)

    def test_native_stop_cancels_configured_checks_without_recording_a_pass(self):
        heartbeat = Path(self.temp.name) / 'checking'
        command = [sys.executable, '-c',
                   'import pathlib,sys,time;pathlib.Path(sys.argv[1]).write_text("running");time.sleep(30)',
                   str(heartbeat)]
        configure(self.root, checks=[{'name': 'long-check', 'command': command}])
        self.approve()
        self.assess()
        self.launch('implementation')
        grant = load_run(self.root)[1]['granted']
        partial = self.root / 'partial.txt'
        partial.write_text('preserved implementation')
        # Desktop's nested MCP failures have their own item ID, distinct from
        # the enclosing functions.exec call. Failed calls have no PostToolUse.
        self.tool('mcp__o_harness__verify', use='failed-check')
        with self.parent_path.open('a', newline='\n') as stream:
            stream.write(json.dumps({'type': 'event_msg', 'payload': {
                'type': 'item_completed', 'thread_id': self.worker, 'turn_id': 'worker-turn',
                'item': {'type': 'McpToolCall', 'id': 'failed-check', 'status': 'failed',
                         'result': {'content': [{'type': 'text', 'text': 'OH exited with 1'}],
                                    'isError': True}}}}) + '\n')
        self.tool('mcp__o_harness__verify', use='interrupted-check')
        # The shell helper on either host must use the same cleanup proof.
        prefix = cancellation.command_prefix(self.root, self.attempt)[:-3]
        unbound = shlex.join(prefix + ['verify'])
        self.assertEqual(self.tool('Bash', {'command': unbound})['hookSpecificOutput']['permissionDecision'], 'deny')
        helper = shlex.join(prefix + ['verify', '--attempt', self.attempt])
        self.assertEqual(self.tool('Bash', {'command': helper}, use='queued-shell-check'), {})
        outcomes = []
        cleaning, release = threading.Event(), threading.Event()
        original_end = cancellation.ended_command
        def end(*args):
            original_end(*args)
            cleaning.set()
            if not release.wait(10):
                raise AssertionError('Verification cleanup did not release')
        def verify():
            try:
                outcomes.append(native.verify(self.root, attempt_id=self.attempt))
            except Refused as exc:
                outcomes.append(str(exc))
        with patch('oh.cancellation.ended_command', side_effect=end):
            thread = threading.Thread(target=verify)
            thread.start()
            try:
                until = time.monotonic() + 5
                while not heartbeat.exists() and time.monotonic() < until:
                    time.sleep(.02)
                self.assertTrue(heartbeat.exists())
                self.stop()
                answer = self.resume_choice(session='new-parent')
                self.native_results[self.attempt] = {'status': 'cancelled', 'text': ''}
                self.assertTrue(cleaning.wait(5))
                # Even with no process left, the helper must finish its locked
                # work before Resume can transfer ownership.
                with self.assertRaisesRegex(Refused, 'still executing'):
                    native.resume(self.root, answer)
                self.assertNotEqual(load_run(self.root)[1]['human']['session'], 'new-parent')
            finally:
                release.set()
                self.stop()
                thread.join(timeout=10)
        self.assertFalse(thread.is_alive())
        self.assertEqual(len(outcomes), 1)
        self.assertIn('Native Stop ended', outcomes[0])
        # The interrupted MCP call has no completion callback or output record.
        with cancellation._edit(self.root) as value:
            value['commands']['uncertain-cleanup'] = {'attempt': self.attempt, 'started': now()}
        with self.assertRaisesRegex(Refused, 'cleanup is still pending'):
            native.resume(self.root, answer)
        with cancellation._edit(self.root) as value:
            value['commands']['uncertain-cleanup']['ended'] = now()
        native.resume(self.root, answer)
        self.assertTrue(cancellation.quiescent(self.root, self.attempt))
        self.assertFalse(load_run(self.root)[1].get('verification'))
        recovered = load_run(self.root)[1]
        self.assertEqual(recovered['human']['session'], 'new-parent')
        self.assertEqual(recovered['granted'], grant)
        self.assertEqual(recovered['attempts'][-1]['outcome'], 'cancelled')
        self.assertEqual(partial.read_text(), 'preserved implementation')
        tools = cancellation._read(self.root)['tools']
        self.assertEqual(tools['failed-check']['completion_source'], 'native-record')
        self.assertEqual(tools['interrupted-check']['completion_source'], 'stopped-verification')
        self.assertEqual(tools['queued-shell-check']['completion_source'], 'stopped-verification')
        replacement = native.admit(self.root, 'implementation')
        native.bind(self.root, replacement['id'], {'child_session': 'replacement-worker'})
        # A delayed shell helper must refuse even on hosts without a caller
        # environment variable. It cannot select the newly admitted author.
        with patch.dict(os.environ, {'CODEX_THREAD_ID': '', 'OH_NATIVE_SESSION_ID': ''}):
            with self.assertRaisesRegex(Refused, 'ended attempt'):
                native.verify(self.root, attempt_id=self.attempt)
            delayed = subprocess.run(prefix + ['verify', '--attempt', self.attempt],
                                     capture_output=True, text=True, timeout=5)
            self.assertNotEqual(delayed.returncode, 0)
            self.assertIn('ended attempt', delayed.stderr)
        self.assertEqual(self.tool('apply_patch')['hookSpecificOutput']['permissionDecision'], 'deny')

    def test_resume_waits_for_existing_tool_then_accepts_the_same_answer(self):
        self.approve()
        self.launch()
        self.assertEqual(self.tool('apply_patch', use='edit'), {})
        self.stop()
        answer = self.resume_choice()
        self.native_results[self.attempt] = {'status': 'completed', 'text': ''}
        with self.assertRaisesRegex(Refused, 'cleanup is still pending'):
            native.resume(self.root, answer)
        cancellation.hook(self.root, 'codex', {
            'hook_event_name': 'PostToolUse', 'session_id': 's', 'agent_id': self.worker,
            'tool_use_id': 'edit', 'tool_name': 'apply_patch'})
        native.resume(self.root, answer)
        self.assertEqual(load_run(self.root)[1]['human']['turn'], answer['turn'])

    @unittest.skipIf(os.name == 'nt', 'POSIX native shell SIGTERM; Windows host kills use native job cleanup')
    def test_native_shell_termination_cleans_configured_check_before_exit(self):
        import signal
        heartbeat = Path(self.temp.name) / 'signal-check'
        child_code = 'import pathlib,sys,time;pathlib.Path(sys.argv[1]).write_text("started");time.sleep(30)'
        command = [sys.executable, '-c', child_code, str(heartbeat)]
        configure(self.root, checks=[{'name': 'signal-check', 'command': command}])
        self.approve(); self.assess()
        for number in (signal.SIGTERM, signal.SIGKILL):  # windows-ok: this POSIX signal test is skipped on Windows
            with self.subTest(signal=number):
                heartbeat.unlink(missing_ok=True)
                self.launch('implementation', turn='signal-' + str(number))
                argv = cancellation.command_prefix(self.root, self.attempt)[:-3] + ['verify', '--attempt', self.attempt]
                process = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                try:
                    until = time.monotonic() + 10
                    while not heartbeat.exists() and process.poll() is None and time.monotonic() < until:
                        time.sleep(.02)
                    self.assertTrue(heartbeat.exists())
                    process.send_signal(number)
                    out, err = process.communicate(timeout=10)
                    self.assertEqual(process.returncode, 130 if number == signal.SIGTERM else -number, out + err)
                    records = [c for c in cancellation._read(self.root)['commands'].values() if c['attempt'] == self.attempt]
                    self.assertEqual(len(records), 1)
                    self.assertEqual(bool(records[0].get('ended')), number == signal.SIGTERM)
                    self.assertFalse(load_run(self.root)[1].get('verification'))
                    self.stop('signal-' + str(number), session=load_run(self.root)[1]['human']['session'])
                    self.native_results[self.attempt] = {'status': 'cancelled', 'text': ''}
                    native.resume(self.root, self.resume_choice(session='new-parent'))
                    self.assertEqual(load_run(self.root)[1]['attempts'][-1]['outcome'], 'cancelled')
                    self.assertTrue(cancellation.quiescent(self.root, self.attempt))
                finally:
                    if process.poll() is None:
                        process.terminate(); process.communicate(timeout=10)

    def test_saved_native_interruption_recovers_missed_callback_on_both_hosts(self):
        self.approve()
        state = load_run(self.root)[1]
        for host in ('codex', 'claude'):
            with self.subTest(host=host):
                transcript = self.root / (host + '.jsonl')
                transcript.write_text('', newline='\n')
                source = state['human'] | {'host': host, 'session': host, 'turn': host,
                                          'at': now(), 'transcript_path': str(transcript)}
                owned = state | {'human': source, 'host': host}
                attempt = {'id': identifier(), 'evidence': str(self.root / host)}
                cancellation.register_attempt(self.root, owned, attempt)
                cancellation.bind(self.root, attempt, 'child-' + host)
                if host == 'codex':
                    event = {'type': 'event_msg', 'timestamp': now(),
                             'payload': {'type': 'turn_aborted', 'turn_id': host, 'reason': 'interrupted'}}
                else:
                    event = {'type': 'user', 'timestamp': now(), 'sessionId': host, 'uuid': host,
                             'message': {'content': [{'type': 'text', 'text': '[Request interrupted by user]'}]}}
                # A partial save cannot be parsed or allow fresh work.
                text = json.dumps(event)
                transcript.write_text(text[:30], newline='\n')
                self.assertFalse(cancellation.poll(self.root, attempt=attempt['id']))
                self.assertIsNone(cancellation.interrupted(self.root, attempt=attempt['id']))
                with self.assertRaisesRegex(Refused, 'still being saved'):
                    cancellation.guard(self.root, attempt=attempt['id'])
                with transcript.open('a', newline='\n') as stream:
                    stream.write(text[30:] + '\n')
                if host == 'codex':
                    delayed = (datetime.fromisoformat(event['timestamp']) + timedelta(seconds=2)).isoformat()
                    with patch('oh.cancellation.now', return_value=delayed):
                        cancellation.hook(self.root, host, {
                            'hook_event_name': 'Interrupt', 'session_id': host, 'turn_id': host})
                self.assertTrue(cancellation.poll(self.root, attempt=attempt['id']))
                self.assertEqual(cancellation.interrupted(self.root, attempt=attempt['id'])['at'], event['timestamp'])
                with self.assertRaisesRegex(Refused, 'Native Stop ended'):
                    cancellation.guard(self.root, attempt=attempt['id'])
                # A new owner starts after that Stop; old saved records do not stop it again.
                resumed_at = (datetime.fromisoformat(event['timestamp']) + timedelta(seconds=1)).isoformat()
                fresh = owned | {'human': source | {'turn': 'fresh', 'at': resumed_at}}
                with cancellation.continuation(self.root, owned, fresh['human']):
                    pass
                fresh_attempt = {'id': identifier(), 'evidence': str(self.root / ('fresh-' + host))}
                cancellation.register_attempt(self.root, fresh, fresh_attempt)
                self.assertIsNone(cancellation.interrupted(self.root, attempt=fresh_attempt['id']))
                cancellation.guard(self.root, attempt=fresh_attempt['id'])

    def test_stop_during_resume_does_not_restart_work_and_late_report_stays_cancelled(self):
        self.approve()
        for session in ('s', 'another-parent'):
            with self.subTest(session=session):
                running = 'running-' + session
                self.launch(turn=running)
                self.stop(running)
                path = self.parent_path if session == 's' else Path(self.temp.name) / 'another-parent.jsonl'
                if not path.exists(): path.write_text('', newline='\n')
                answer = self.resume_choice(session=session, at=now(), transcript_path=str(path))
                cancellation.hook(self.root, 'codex', {
                    'hook_event_name': 'PreToolUse', 'session_id': session, 'turn_id': answer['turn'],
                    'tool_name': 'resume', 'tool_input': {}, 'tool_use_id': 'resuming'})
                def result(*args):
                    self.stop(answer['turn'], session=session, path=path)
                    raise authority.Saving('The model is still generating')
                with patch('oh.authority.native_result', side_effect=result):
                    with self.assertRaisesRegex(Refused, 'stopped after this Resume answer'):
                        native.resume(self.root, answer)
                state = load_run(self.root)[1]
                self.assertNotEqual(state['human']['turn'], answer['turn'])
                self.assertEqual(state['attempts'][-1]['outcome'], 'cancelled')
                self.native_results[self.attempt] = {
                    'status': 'completed', 'text': json.dumps({'summary': 'Late evidence',
                        'findings': [{'severity': 'blocking', 'description': 'Keep this finding'}]})}
                native.retain(self.root, self.attempt, {})
                retained = load_run(self.root)[1]['attempts'][-1]
                self.assertEqual(retained['outcome'], 'cancelled')
                self.assertEqual(retained['findings'][0]['description'], 'Keep this finding')
                native.resume(self.root, self.resume_choice())

    def test_terminal_model_does_not_override_unfinished_tools(self):
        self.approve()
        self.launch()
        # A rejected sibling in Promise.all can cancel a read without its post-hook.
        # It cannot hold a writer alive. An edit requires a completion boundary;
        # commands and external tools still need their own execution evidence.
        self.tool('mcp__o_harness__resource', {'path':'prompts/implementation.md'},use='cancelled-read')
        self.tool('mcp__o_harness__command_format',use='cancelled-format')
        self.tool('apply_patch', use='unfinished-edit')
        self.native_results[self.attempt] = {'status': 'completed', 'text': ''}
        with self.assertRaisesRegex(Refused, 'tools are still running'):
            native.retain(self.root, self.attempt, {})
        # Old completion, another child and interrupted/synthetic completion do
        # not settle a later file edit whose own callback is absent.
        for result in ({'completed_at':'2000-01-01T00:00:00Z'},
                       {'completed_at':now(),'native_id':'another-child'},
                       {'completed_at':now(),'status':'interrupted'}):
            with patch('oh.authority.native_result',return_value={'status':'completed','native_id':self.worker,**result}):
                with self.assertRaisesRegex(Refused, 'tools are still running'):
                    native.retain(self.root,self.attempt,{})
        self.native_results[self.attempt]['completed_at']=now()
        self.tool('mcp__o_harness__verify', use='nested-failure')
        self.tool('apply_patch', use='nested-patch')
        helper = shlex.join(cancellation.command_prefix(self.root, self.attempt)[:-3] + ['status'])
        self.tool('Bash', {'command': helper}, use='nested-helper')
        def completed(thread, **item):
            with self.parent_path.open('a', newline='\n') as stream:
                stream.write(json.dumps({'type': 'event_msg', 'payload': {
                    'type': 'item_completed', 'thread_id': thread,
                    'item': {'type': 'McpToolCall', 'id': 'nested-failure', **item}}}) + '\n')
        completed('other-child', status='failed', result={'isError': True})
        completed(self.worker, status='in_progress', result={})
        completed(self.worker, status='failed', error={'message': 'transport timed out'})
        with self.parent_path.open('a',newline='\n') as stream:
            stream.write(json.dumps({'type':'event_msg','payload':{'type':'task_complete'}})+'\n')
        with self.assertRaisesRegex(Refused, 'tools are still running'):
            native.retain(self.root, self.attempt, {})
        self.assertEqual(cancellation._read(self.root)['tools']['unfinished-edit']['completion_source'],'native-child-completed')
        completed(self.worker, status='failed', result={'isError': True, 'content': []})
        completed(self.worker, type='FileChange', id='nested-patch', status='failed', stderr='patch did not apply')
        completed(self.worker, type='CommandExecution', id='nested-helper', status='completed', exit_code=None)
        with self.assertRaisesRegex(Refused, 'tools are still running'):
            native.retain(self.root, self.attempt, {})
        completed(self.worker, type='CommandExecution', id='nested-helper', status='completed', exit_code=0)
        native.retain(self.root, self.attempt, {})
        self.assertTrue(load_run(self.root)[1]['attempts'][0]['finished'])

    def test_child_only_stop_rejects_older_resume_but_coordinator_cleanup_does_not(self):
        home = Path(self.temp.name) / 'host'
        parent = home / '.claude/projects/p/parent.jsonl'
        child = parent.with_suffix('') / 'subagents/agent-child.jsonl'
        child.parent.mkdir(parents=True)
        parent.write_text('', newline='\n')
        other = parent.with_name('other.jsonl'); other.write_text('', newline='\n')
        stamp = lambda seconds: '2026-10-20T12:00:' + seconds + 'Z'
        original = {'host': 'claude', 'session': 'parent', 'turn': 'original',
                    'prompt': 'approved', 'at': stamp('00'), 'transcript_path': str(parent)}
        attempt = {'id': 'child-stop-attempt', 'started_at': stamp('01'), 'evidence': str(child.parent),
                   'parent': original, 'native_child': {'parent_session': 'parent', 'child_session': 'child',
                                                       'tool_use_id': 'spawn', 'transcript_path': str(child)}}
        state = {'id': 'child-stop-run', 'host': 'claude', 'human': original, 'attempts': [attempt]}
        cancellation.register_attempt(self.root, state, attempt)
        cancellation.bind(self.root, attempt, 'child')
        # Retention is allowed before the pending Resume's final ordering check.
        cancellation.finished(self.root, attempt['id'])
        child.write_text(json.dumps({'type': 'user', 'isSidechain': True, 'sessionId': 'parent',
            'agentId': 'child', 'uuid': 'personal-stop', 'cwd': str(self.root), 'timestamp': stamp('03'),
            'message': {'content': [{'type': 'text', 'text': '[Request interrupted by user for tool use]'}]}})
            + '\n', newline='\n')
        metadata = {'stoppedByUser': True, 'toolUseId': 'spawn'}
        child.with_suffix('.meta.json').write_text(json.dumps(metadata), newline='\n')
        with patch('pathlib.Path.home', return_value=home):
            saved_child = child.read_text(); child.write_text('', newline='\n')
            with self.assertRaisesRegex(authority.Saving, 'Stop occurrence is still saving'):
                with cancellation.continuation(self.root, state, original | {'at': stamp('02')}):pass
            child.write_text(saved_child, newline='\n')
            for session, transcript in (('parent', parent), ('other', other)):
                answer = original | {'session': session, 'turn': 'resuming', 'prompt': 'Resume',
                                     'at': stamp('02'), 'transcript_path': str(transcript)}
                with self.subTest(session=session), self.assertRaisesRegex(Refused, 'stopped after this Resume answer'):
                    with cancellation.continuation(self.root, state, answer):pass
                with cancellation.continuation(self.root, state, answer | {'at': stamp('04')}):pass
            # A successful TaskStop, correlated to this child, settles old work.
            # Even a delayed marker/sidecar must not turn that cleanup into a human Stop.
            request = {'type': 'assistant', 'sessionId': 'parent', 'timestamp': stamp('02.500'),
                'message': {'content': [{'type': 'tool_use', 'id': 'cleanup', 'name': 'TaskStop',
                                        'input': {'task_id': 'child'}}]}}
            reply = {'type': 'user', 'sessionId': 'parent', 'timestamp': stamp('02.900'),
                'message': {'content': [{'type': 'tool_result', 'tool_use_id': 'cleanup', 'is_error': False}]},
                'toolUseResult': {'task_id': 'child', 'task_type': 'local_agent'}}
            parent.write_text(json.dumps(request)+'\n'+json.dumps(reply)+'\n', newline='\n')
            with cancellation.continuation(self.root, state, answer):pass
            child.write_text('', newline='\n')
            with self.assertRaisesRegex(authority.Saving, 'Stop occurrence is still saving'):
                with cancellation.continuation(self.root, state, answer):pass
            child.write_text(saved_child, newline='\n')
            # Cleanup initiated after an already-observed personal Stop cannot erase it.
            request['timestamp'] = stamp('03.500'); reply['timestamp'] = stamp('03.900')
            parent.write_text(json.dumps(request)+'\n'+json.dumps(reply)+'\n', newline='\n')
            with self.assertRaisesRegex(Refused, 'stopped after this Resume answer'):
                with cancellation.continuation(self.root, state, answer):pass
            # Model-driven messaging/resumption cannot replace a later human Stop.
            for name, args in (('SendMessage', {'to': 'child', 'message': 'Send your handback'}),
                               ('Agent', {'resume': 'child', 'prompt': 'Send your handback'})):
                message = {'type': 'assistant', 'sessionId': 'parent', 'timestamp': stamp('04'),
                    'message': {'content': [{'type': 'tool_use', 'id': 'message', 'name': name, 'input': args}]}}
                acknowledgement = {'type': 'user', 'sessionId': 'parent', 'timestamp': stamp('05'),
                    'message': {'content': [{'type': 'tool_result', 'tool_use_id': 'message'}]},
                    'toolUseResult': {'success': True, 'resumedAgentId': 'child'}}
                parent.write_text(json.dumps(message)+'\n'+json.dumps(acknowledgement)+'\n', newline='\n')
                with self.subTest(lifecycle=name), self.assertRaisesRegex(Refused, 'stopped after this Resume answer'):
                    with cancellation.continuation(self.root, state, answer):pass
                with cancellation.continuation(self.root, state, answer | {'at': stamp('06')}):pass
            # Cleanup is attributed to the lifecycle at the interruption, not a
            # later message; cleanup from an earlier lifecycle cannot hide a new Stop.
            request['timestamp'] = stamp('02.500'); reply['timestamp'] = stamp('02.600')
            parent.write_text(''.join(json.dumps(r)+'\n' for r in (request, reply, message, acknowledgement)), newline='\n')
            with cancellation.continuation(self.root, state, answer):pass
            message['timestamp'] = stamp('02.700'); acknowledgement['timestamp'] = stamp('02.800')
            parent.write_text(''.join(json.dumps(r)+'\n' for r in (request, reply, message, acknowledgement)), newline='\n')
            with self.assertRaisesRegex(Refused, 'stopped after this Resume answer'):
                with cancellation.continuation(self.root, state, answer):pass
            acknowledgement['message']['content'][0]['is_error'] = True
            parent.write_text(''.join(json.dumps(r)+'\n' for r in (request, reply, message, acknowledgement)), newline='\n')
            with cancellation.continuation(self.root, state, answer):pass
            parent.write_text('', newline='\n')
            child.with_suffix('.meta.json').write_text(json.dumps(metadata | {'toolUseId': 'foreign-spawn'}), newline='\n')
            with cancellation.continuation(self.root, state, answer):pass

    def test_stop_before_launch_requires_saved_stop_and_no_launch_evidence(self):
        self.approve()
        admitted = native.admit(self.root, 'assessment')
        attempt = load_run(self.root)[1]['attempts'][0]
        turn = load_run(self.root)[1]['human']['turn']
        cancellation.hook(self.root, 'codex', {
            'hook_event_name': 'Interrupt', 'session_id': 's', 'turn_id': turn})
        stopped = cancellation.interrupted(self.root, attempt=attempt['id'])
        self.assertIsNone(cancellation.unlaunched_stop(self.root, attempt, stopped))
        event = {'type': 'event_msg', 'timestamp': now(), 'payload': {
            'type': 'turn_aborted', 'turn_id': turn, 'reason': 'interrupted'}}
        self.parent_path.write_text(json.dumps(event) + '\n', newline='\n')
        self.assertIsNotNone(cancellation.unlaunched_stop(self.root, attempt, stopped))
        with patch('oh.authority.native_child', side_effect=authority.Saving('No launch exists')):
            native.resume(self.root, self.resume_choice())
        retained = load_run(self.root)[1]['attempts'][0]
        self.assertEqual(retained['outcome'], 'cancelled')
        self.assertNotIn('native_child', retained)
        # Even a failed or unresolved spawn defeats the "never launched" inference.
        with self.parent_path.open('a', newline='\n') as stream:
            stream.write(json.dumps({'type': 'response_item', 'timestamp': now(), 'payload': {
                'type': 'function_call', 'name': 'spawn_agent', 'call_id': 'uncertain',
                'arguments': json.dumps({'task_name': admitted['native_task_name']})}}) + '\n')
        self.assertIsNone(cancellation.unlaunched_stop(self.root, attempt, stopped))

    def test_finished_failed_launch_does_not_capture_an_unrelated_child(self):
        with patch.object(self, 'human', return_value={'host': 'claude', 'session': 's',
                         'turn': '1', 'prompt': 'approve', 'transcript_path': str(self.parent_path)}):
            self.approve()
        admitted = native.admit(self.root, 'assessment')
        def event(kind, **extra):
            return cancellation.hook(self.root, 'claude', {
                'hook_event_name': kind, 'session_id': 's', **extra})
        event('PreToolUse', tool_use_id='failed-launch', tool_name='Agent',
              tool_input={'prompt': admitted['request']})
        # A rejected PreToolUse can have a saved result without a failure callback.
        self.parent_path.write_text(json.dumps({'type': 'user', 'sessionId': 's',
            'message': {'content': [{'type': 'tool_result', 'tool_use_id': 'failed-launch',
                                    'is_error': True, 'content': 'Launch rejected'}]}}) + '\n', newline='\n')
        self.native_results[admitted['id']] = {'status': 'failed', 'text': 'Native launch failed'}
        with patch('oh.authority.native_child', side_effect=authority.Saving('No child was launched')):
            native.retain(self.root, admitted['id'], {'tool_use_id': 'failed-launch'})
        event('SubagentStart', agent_id='unrelated-child')
        self.assertIsNone(cancellation._read(self.root)['attempts'][admitted['id']]['child'])
        self.assertEqual(event('PreToolUse', agent_id='unrelated-child', tool_name='Read',
                               tool_use_id='unrelated-read'), {})
        # A genuinely pending replacement still gets its native child attribution.
        replacement = native.admit(self.root, 'assessment')
        event('PreToolUse', tool_use_id='replacement-launch', tool_name='Agent',
              tool_input={'prompt': replacement['request']})
        event('SubagentStart', agent_id='replacement-child')
        self.assertEqual(cancellation._read(self.root)['attempts'][replacement['id']]['child'],
                         'replacement-child')

    def _rejected_launch_retry(self, host):
        with patch.object(self, 'human', return_value={'host': host, 'session': 's',
                         'turn': '1', 'prompt': 'approve', 'transcript_path': str(self.parent_path)}):
            self.approve()
        admitted = native.admit(self.root, 'assessment')
        before = load_run(self.root)[1]
        def event(kind, **extra):
            return cancellation.hook(self.root, host, {
                'hook_event_name': kind, 'session_id': 's', **extra})
        for use in ('rejected-launch', 'corrected-launch'):
            event('PreToolUse', tool_use_id=use, tool_name='Agent' if host == 'claude' else 'spawn_agent',
                  tool_input={'prompt': admitted['request']})
        child = Path(self.temp.name) / 'child.jsonl'
        child.write_text('', newline='\n')
        binding = {'child_session': 'worker', 'parent_session': 's', 'profile': admitted['profile'],
                   'transcript_path': str(child), 'record_hashes': ['native-spawn']}
        with patch('oh.authority.native_child', return_value=binding):
            native.bind(self.root, admitted['id'], {'child_session': 'worker'})
        event('PreToolUse', agent_id='worker', tool_use_id='worker-read', tool_name='Read')
        def result(use, **extra):
            if host == 'claude':
                return {'type': 'user', 'sessionId': 's', 'message': {'content': [
                    {'type': 'tool_result', 'tool_use_id': use, 'is_error': True}]}, **extra}
            return {'type': 'response_item', 'payload': {
                'type': 'function_call_output', 'call_id': use, 'output': 'Launch rejected'}}
        records = [result('unrelated-launch'), result('worker-read')]
        if host == 'claude':
            records += [result('rejected-launch', sessionId='another-parent'),
                        result('rejected-launch', isSidechain=True)]
        self.parent_path.write_text(''.join(json.dumps(r) + '\n' for r in records), newline='\n')
        self.native_results[admitted['id']] = {'status': 'completed', 'text': json.dumps({
            'difficulty': 'standard', 'rationale': 'Contained change'})}
        with self.assertRaisesRegex(Refused, 'still running'):
            native.retain(self.root, admitted['id'], {})
        self.assertNotIn('ended', cancellation._read(self.root)['tools']['rejected-launch'])
        # The parent's exact launch result settles only that call, not child tools.
        with self.parent_path.open('a', newline='\n') as stream:
            stream.write(json.dumps(result('rejected-launch')) + '\n')
        with self.assertRaisesRegex(Refused, 'still running'):
            native.retain(self.root, admitted['id'], {})
        tools = cancellation._read(self.root)['tools']
        self.assertEqual(tools['rejected-launch']['completion_source'], 'native-parent-record')
        self.assertNotIn('ended', tools['worker-read'])
        event('PostToolUse', agent_id='worker', tool_use_id='worker-read')
        self.assertEqual(native.retain(self.root, admitted['id'], {})['outcome'], 'assessed')
        native.retain(self.root, admitted['id'], {})  # Recovery remains idempotent.
        after = load_run(self.root)[1]
        for key in ('granted', 'scope_id', 'config', 'decisions'):
            self.assertEqual(after[key], before[key])
        self.assertEqual(len(after['attempts']), 1)

    def test_claude_rejected_launch_retry_settles_without_callback(self):
        self._rejected_launch_retry('claude')

    def test_codex_rejected_launch_retry_settles_without_callback(self):
        self._rejected_launch_retry('codex')

    def test_two_resume_claimants_do_not_both_take_ownership(self):
        self.approve()
        self.launch()
        self.stop()
        self.native_results[self.attempt] = {'status': 'cancelled', 'text': ''}
        answers = [self.resume_choice(session=session, at=now()) for session in ('first', 'second')]
        barrier = threading.Barrier(2)
        outcomes = []
        def resume(answer):
            barrier.wait()
            try:
                native.resume(self.root, answer)
                outcomes.append(('accepted', answer['session']))
            except Refused as exc:
                outcomes.append(('refused', str(exc)))
        threads = [threading.Thread(target=resume, args=(answer,)) for answer in answers]
        for thread in threads: thread.start()
        for thread in threads: thread.join(timeout=15)
        self.assertFalse(any(thread.is_alive() for thread in threads))
        self.assertEqual(sorted(result[0] for result in outcomes), ['accepted', 'refused'])
        winner = next(result[1] for result in outcomes if result[0] == 'accepted')
        self.assertEqual(load_run(self.root)[1]['human']['session'], winner)


if __name__ == '__main__':
    unittest.main()
