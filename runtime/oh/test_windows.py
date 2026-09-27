import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from .config import HOME
from . import test_workflow as fixtures

SCRIPTS = HOME / 'plugins/o-harness/scripts'


class WindowsTest(unittest.TestCase):
    def test_claude_rules_name_windows_paths_the_way_claude_reads_them(self):
        from .hosts import rule_path
        self.assertEqual(rule_path(r'C:\Users\me\.config\o-harness'), '//c/Users/me/.config/o-harness')
        self.assertEqual(rule_path('D:/work'), '//d/work')
        self.assertEqual(rule_path('/Users/me/x'), '//Users/me/x')

    def test_claude_workers_on_windows_edit_files_but_have_no_shell(self):
        from .hosts import command
        root = Path(tempfile.mkdtemp());self.addCleanup(shutil.rmtree, root)
        subprocess.run(['git', 'init', '-q', str(root)], check=True)
        with patch('oh.hosts.executable', return_value='claude'), patch('oh.hosts.WINDOWS', True):
            work = command('claude', {'model': 'opus', 'effort': 'high'}, root, 'implementation', None, 60000)
            review = command('claude', {'model': 'opus', 'effort': 'high'}, root, 'review', None, 60000, root / 'run')
        self.assertEqual(work[work.index('--tools') + 1], 'Read,Glob,Grep,Edit,Write')
        self.assertEqual(review[review.index('--tools') + 1], 'Read,Glob,Grep')
        settings = json.loads(work[work.index('--settings') + 1])
        self.assertEqual(settings['sandbox'], {'enabled': False})
        self.assertLessEqual({'Bash', 'PowerShell', 'Agent'}, set(settings['permissions']['deny']))
        self.assertEqual(review[review.index('--add-dir') + 1], str(root / 'run'))
        self.assertNotIn('--add-dir', work)

    @unittest.skipIf(os.name == 'nt', 'Uses POSIX sh and symlinks')
    def test_the_launcher_finds_python_or_says_how_to_get_it(self):
        bin = Path(tempfile.mkdtemp());self.addCleanup(shutil.rmtree, bin)
        (bin / 'dirname').symlink_to(shutil.which('dirname'))
        env = {'PATH': str(bin), 'HOME': str(bin), 'OH_DATA_HOME': str(bin / 'data')}
        def launch(*args, stdin=''):
            return subprocess.run(['/bin/sh', str(SCRIPTS / 'python.sh'), *args], input=stdin, env=env, capture_output=True, text=True)
        missing = launch('--launcher', str(SCRIPTS / 'oh'), '--root', str(bin), 'setup')
        self.assertEqual((missing.returncode, missing.stderr.strip()), (2, 'OH needs Python 3.11 or newer as python3.'))
        quiet = launch('--hook', str(SCRIPTS / 'human-event.py'), 'claude', stdin='{"prompt":"/oh-propose x"}')
        self.assertEqual((quiet.returncode, quiet.stdout, quiet.stderr), (0, '', ''))
        (bin / 'python3').symlink_to(sys.executable)
        found = launch('--launcher', str(SCRIPTS / 'oh'), '--root', str(bin), 'status')
        self.assertEqual(found.returncode, 1);self.assertIn('OH is not set up', found.stderr)

    def test_the_launcher_is_valid_sh_and_python(self):
        source = (SCRIPTS / 'oh').read_text()
        compile(source, 'oh', 'exec')
        self.assertTrue(source.startswith('#!/bin/sh\n""":"\nexec sh "$(dirname "$0")/python.sh" --launcher "$0" "$@"\n'))
        self.assertTrue((SCRIPTS / 'oh.cmd').read_bytes().count(b'\r\n') > 10, 'cmd files need CRLF line endings')

    def test_the_dashboard_starts_at_logon_through_task_scheduler(self):
        from . import service
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {'OH_DATA_HOME': tmp, 'USERDOMAIN': 'PC', 'USERNAME': 'me'}), \
                patch('oh.system.WINDOWS', True), patch('oh.service.schtasks') as schtasks:
            (Path(tmp) / 'bin').mkdir();(Path(tmp) / 'bin/oh').write_text('launcher')
            self.assertEqual(service.install()['service'], 'OH dashboard')
            task = (Path(tmp) / 'service/dashboard-task.xml').read_text(encoding='utf-16')
            self.assertIn('<LogonTrigger><Enabled>true</Enabled><UserId>PC\\me</UserId>', task)
            self.assertIn('<RunLevel>LeastPrivilege</RunLevel>', task);self.assertIn('dashboard.pyw', task)
            starter = (Path(tmp) / 'bin/dashboard.pyw').read_text()
            compile(starter, 'dashboard.pyw', 'exec');self.assertIn(json.dumps(tmp)[1:-1], starter)
            self.assertEqual([c.args[0] for c in schtasks.call_args_list], ['/Create', '/End', '/Run'])
            service.uninstall()
            self.assertFalse((Path(tmp) / 'bin/dashboard.pyw').exists())
            self.assertEqual(schtasks.call_args_list[-1].args[:2], ('/Delete', '/F'))

    def test_reviewers_get_the_exact_change_as_a_file(self):
        test = fixtures.WorkflowTest('test_initial_and_continue_same_batch_snapshot_and_idempotent_restart')
        test.setUp();self.addCleanup(test.doCleanups)
        from .runner import run
        from .workflow import start
        seen = []
        def fake(host, root, profile, prompt, role, directory, context, **kw):
            if role == 'review':
                admission = json.loads((Path(directory) / 'request.json').read_text())
                seen.append((Path(admission['diff']['path']).read_text(), prompt))
            return test.fake(host, root, profile, prompt, role, directory, context, **kw)
        start(test.root, {'tasks': test.tasks[:1]}, test.event())
        run(test.root, fake)
        diff, prompt = seen[0]
        self.assertIn('+++ b/output.txt', diff);self.assertIn('subject.diff', prompt)


@unittest.skipUnless(os.name == 'nt', 'Windows only')
class NativeWindowsTest(unittest.TestCase):
    def test_only_you_or_administrators_may_change_a_host_program(self):
        from .system import untrusted
        folder = Path(tempfile.mkdtemp());self.addCleanup(shutil.rmtree, folder, ignore_errors=True)
        program = folder / 'host.exe';program.write_bytes(b'MZ')
        self.assertIsNone(untrusted(program, 'file'))
        subprocess.run(['icacls', str(program), '/grant', '*S-1-1-0:(M)'], check=True, capture_output=True)
        self.assertIn('S-1-1-0', untrusted(program, 'file'))
        subprocess.run(['icacls', str(folder), '/grant', '*S-1-5-32-545:(OI)(CI)(W)'], check=True, capture_output=True)
        self.assertIn('S-1-5-32-545', untrusted(folder, 'folder'))

    def test_oh_never_runs_a_command_planted_in_the_checkout(self):
        checkout = Path(tempfile.mkdtemp());self.addCleanup(shutil.rmtree, checkout, ignore_errors=True)
        shutil.copy(sys.executable, checkout / 'git.exe')  # a "git" that is really Python
        env = os.environ | {'OH_DATA_HOME': str(checkout / 'state')}
        result = subprocess.run([sys.executable, '-I', '-X', 'utf8', str(HOME / 'oh'), '--root', str(checkout), 'config'],
                                cwd=checkout, env=env, capture_output=True, text=True)
        # Python run as "git -C ..." would say "Unknown option: -C"; the real Git answers instead.
        self.assertNotIn('Unknown option', result.stderr + result.stdout)
        self.assertIn(result.returncode, (0, 2), result.stderr)

    def test_oh_cmd_starts_oh_from_cmd_and_powershell(self):
        env = os.environ | {'OH_DATA_HOME': tempfile.mkdtemp()}
        for shell in (['cmd', '/c'], ['powershell', '-NoProfile', '-Command', '&']):
            result = subprocess.run([*shell, str(SCRIPTS / 'oh.cmd'), 'status'], env=env, capture_output=True, text=True)
            self.assertIn('OH is not set up', result.stderr + result.stdout, shell)


if __name__ == '__main__':
    unittest.main()
