import ast
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
    @unittest.skipUnless(os.name == 'nt', 'Requires Windows PowerShell')
    def test_acceptance_steps_retain_native_command_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            bad=Path(tmp)/'fail.cmd';bad.write_bytes(b'@exit /b 23\r\n')
            helper=str(HOME/'integrations/windows-status.ps1').replace("'","''")
            fixture=str(bad).replace("'","''")
            command=f". '{helper}'; Run 'fixture' {{ Native '{fixture}'; Write-Host 'UNREACHABLE' }}; Run 'later evidence' {{ Write-Host 'collected' }}; if ($script:Failures.Count -eq 1) {{ exit 7 }} else {{ exit 2 }}"
            result=subprocess.run(['powershell','-NoProfile','-NonInteractive','-Command',command],capture_output=True,text=True)
            self.assertEqual(result.returncode,7,result.stdout+result.stderr)
            self.assertIn('FAIL fixture',result.stdout)
            self.assertIn('status 23',result.stdout)
            self.assertIn('OK   later evidence',result.stdout)
            self.assertNotIn('OK   fixture',result.stdout)
            self.assertNotIn('UNREACHABLE',result.stdout)

    @unittest.skipIf(os.name == 'nt', 'Uses POSIX sh and symlinks')
    def test_launcher_and_hook_probes_never_import_project_code(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp);bin=folder/'bin';bin.mkdir();project=folder/'project';project.mkdir()
            (bin/'dirname').symlink_to(shutil.which('dirname'))
            (project/'sitecustomize.py').write_text('from pathlib import Path\nPath("planted").touch()\n')
            script=folder/'safe.py';script.write_text('print("isolated")\n')
            env=dict(os.environ,PATH=str(bin),HOME=tmp,PYTHONPATH=str(project),OH_DATA_HOME=str(folder/'data'))
            for name in ('python3','python','py','private'):
                if name=='private':
                    own=folder/'data/python/test';own.mkdir(parents=True)
                    (own/'python.exe').symlink_to(sys.executable)
                    (own.parent/'current').write_text('test');(bin/'cat').symlink_to(shutil.which('cat'))
                    env['OS']='Windows_NT';env.pop('USERPROFILE',None)
                elif name=='py':
                    import shlex
                    (bin/name).write_text('#!/bin/sh\nshift\nexec '+shlex.quote(sys.executable)+' "$@"\n');(bin/name).chmod(0o755)
                else:(bin/name).symlink_to(sys.executable)
                for mode in ('--launcher','--hook'):
                    with self.subTest(name=name,mode=mode):
                        result=subprocess.run(['/bin/sh',str(SCRIPTS/'python.sh'),mode,str(script)],cwd=project,env=env,capture_output=True,text=True)
                        self.assertEqual(result.returncode,0,result.stderr)
                        self.assertEqual(result.stdout.strip(),'isolated')
                        self.assertFalse((project/'planted').exists())
                if name!='private':(bin/name).unlink()

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
        from .installation import LAUNCHERS
        source = (SCRIPTS / 'oh').read_bytes()
        compile(source, 'oh', 'exec');self.assertTrue(source.startswith(LAUNCHERS))
        for name in ('oh.cmd', 'python.cmd', 'hook.cmd'):
            data = (SCRIPTS / name).read_bytes()
            self.assertEqual(data.count(b'\n'), data.count(b'\r\n'), f'{name} needs CRLF line endings')
        # Stored as they are checked out, so a review of this repository compares equal bytes.
        stored = subprocess.run(['git', '-C', str(HOME), 'ls-files', '--eol', '--', 'plugins/o-harness/scripts/oh.cmd'], capture_output=True, text=True).stdout
        self.assertIn('i/crlf', stored)

    @unittest.skipIf(os.name == 'nt', 'POSIX symlinks')
    def test_a_symlinked_launcher_still_finds_its_helpers(self):
        links = Path(tempfile.mkdtemp());self.addCleanup(shutil.rmtree, links)
        (links / 'oh').symlink_to(SCRIPTS / 'oh')
        result = subprocess.run([str(links / 'oh'), 'status'], env=os.environ | {'OH_DATA_HOME': str(links / 'data')}, capture_output=True, text=True)
        self.assertEqual(result.returncode, 1, result.stderr);self.assertIn('OH is not set up', result.stderr)

    def test_codex_gets_a_windows_hook_that_needs_no_sh(self):
        from .installation import build
        with tempfile.TemporaryDirectory() as tmp:
            build(Path(tmp) / 'codex/o-harness', 'codex');build(Path(tmp) / 'claude/o-harness', 'claude')
            codex = json.loads((Path(tmp) / 'codex/o-harness/hooks/hooks.json').read_text())['hooks']['UserPromptSubmit'][0]['hooks'][0]
            claude = json.loads((Path(tmp) / 'claude/o-harness/hooks/hooks.json').read_text())['hooks']['UserPromptSubmit'][0]['hooks'][0]
            self.assertEqual(codex['commandWindows'], '"%PLUGIN_ROOT%\\scripts\\hook.cmd" codex')
            self.assertNotIn('commandWindows', claude)
            for name in ('python.cmd', 'hook.cmd', 'oh.cmd', 'python.sh', 'get-python.ps1'):self.assertTrue((Path(tmp) / 'codex/o-harness/core' / name).is_file())

    @unittest.skipUnless(os.name == 'nt', 'Requires the actual Windows cmd hook runner')
    def test_packaged_codex_hook_runs_through_outer_cmd_quotes(self):
        from .installation import build
        with tempfile.TemporaryDirectory(prefix='OH hook spaces ') as tmp:
            package=Path(tmp)/'o-harness';build(package,'codex')
            # Keep the packaged hook.cmd, python.cmd and human-event.py. Replace only the
            # OH subprocess boundary: host attestation is tested separately, never forged here.
            (package/'scripts/oh').write_text('import json,sys\nassert sys.argv[-2:]==["--host","codex"]\nprint(json.dumps({"received":json.load(sys.stdin),"authorized":False}))\n')
            hook=json.loads((package/'hooks/hooks.json').read_text())['hooks']['UserPromptSubmit'][0]['hooks'][0]['commandWindows']
            shell=os.environ['ComSpec']
            # Mirrors command_runner.rs: cmd.exe /C plus raw_arg("\"{command_line}\"").
            command=f'"{shell}" /C "{hook}"'
            payload={'hook_event_name':'UserPromptSubmit','session_id':'fixture','prompt':'/oh-design auth','cwd':tmp}
            env=dict(os.environ,PLUGIN_ROOT=str(package));env.pop('OH_CHILD_ATTEMPT',None)
            result=subprocess.run(command,executable=shell,env=env,cwd=tmp,input=json.dumps(payload),capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            output=json.loads(result.stdout)['hookSpecificOutput']
            self.assertEqual(output['hookEventName'],'UserPromptSubmit')
            forwarded=json.loads(output['additionalContext'].removeprefix('OH: '))
            self.assertEqual(forwarded,{'received':payload,'authorized':False})

    def test_json_values_can_come_from_a_file(self):
        test = fixtures.WorkflowTest('test_initial_and_continue_same_batch_snapshot_and_idempotent_restart')
        test.setUp();self.addCleanup(test.doCleanups)
        from .cli import main
        from .config import project_checks
        value = Path(test.temp.name) / 'checks.json'
        value.write_text('\ufeff[{"name": "t", "command": ["git", "diff", "--check"]}]')  # PowerShell 5 writes a BOM
        with patch('sys.stdout'):main(['--root', str(test.root), 'config', 'set', 'checks', '@' + str(value)])
        self.assertEqual(project_checks(test.root), [{'name': 't', 'command': ['git', 'diff', '--check']}])

    def test_relative_config_file_uses_invocation_directory_even_with_root_override(self):
        test = fixtures.WorkflowTest('test_initial_and_continue_same_batch_snapshot_and_idempotent_restart')
        test.setUp();self.addCleanup(test.doCleanups)
        from .cli import main
        from .config import project_checks,change
        invocation=Path(test.temp.name)
        (invocation/'checks.json').write_text('[{"name":"relative","command":["git","status"]}]')
        original=Path.cwd()
        def save(*args,**kwargs):
            # Simulate only the CLI's Windows directory change; storage uses the real platform lock.
            with patch('oh.system.WINDOWS',os.name=='nt'):return change(*args,**kwargs)
        try:
            os.chdir(invocation)
            with patch('oh.system.WINDOWS', True), patch('oh.config.change',save), patch('sys.stdout'):
                main(['--root',str(test.root),'config','set','checks','@checks.json'])
            self.assertEqual(Path.cwd(),HOME)
            self.assertEqual(project_checks(test.root),[{'name':'relative','command':['git','status']}])
        finally:os.chdir(original)

    def test_codex_is_never_trusted_from_inside_the_project(self):
        from .capabilities import validate_profile
        with patch('oh.hosts.executable', side_effect=RuntimeError('stop')) as executable:
            with self.assertRaises(RuntimeError):validate_profile('codex', {'model': 'm', 'effort': 'high'}, Path('/the/project'))
        self.assertEqual(executable.call_args.args, ('codex', Path('/the/project')))

    def test_line_ending_conversion_alone_is_accepted_for_review(self):
        from .verification import candidate_tree
        origin = Path(tempfile.mkdtemp());self.addCleanup(shutil.rmtree, origin, ignore_errors=True)
        subprocess.run(['git', 'init', '-q', str(origin)], check=True)
        (origin / 'a.txt').write_text('one\ntwo\n')
        subprocess.run(['git', '-C', str(origin), 'add', '.'], check=True)
        subprocess.run(['git', '-C', str(origin), '-c', 'user.name=t', '-c', 'user.email=t@example.invalid', 'commit', '-qm', 'a'], check=True)
        clone = origin.parent / (origin.name + '-clone');self.addCleanup(shutil.rmtree, clone, ignore_errors=True)
        subprocess.run(['git', 'clone', '-q', '-c', 'core.autocrlf=true', str(origin), str(clone)], check=True)
        self.assertEqual((clone / 'a.txt').read_bytes(), b'one\r\ntwo\r\n')
        candidate_tree(clone)
        (clone / 'a.txt').write_bytes(b'one\r\ntwo\r\nthree\r\n')
        self.assertTrue(candidate_tree(clone))

    def test_the_dashboard_starts_at_logon_through_task_scheduler(self):
        from . import service
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {'OH_DATA_HOME': tmp, 'USERDOMAIN': 'PC', 'USERNAME': 'me'}), \
                patch('oh.system.WINDOWS', True), patch('oh.service.schtasks', side_effect=TaskScheduler()) as schtasks:
            (Path(tmp) / 'bin').mkdir();(Path(tmp) / 'bin/oh').write_text('launcher')
            self.assertEqual(service.install()['service'], 'OH dashboard')
            task = (Path(tmp) / 'service/dashboard-task.xml').read_text(encoding='utf-16')
            self.assertIn('<LogonTrigger><Enabled>true</Enabled><UserId>PC\\me</UserId>', task)
            self.assertIn('<RunLevel>LeastPrivilege</RunLevel>', task);self.assertIn('dashboard.pyw', task)
            starter = (Path(tmp) / 'bin/dashboard.pyw').read_text()
            syntax = ast.parse(starter, 'dashboard.pyw')
            assignment = next(node for node in syntax.body if isinstance(node, ast.Assign)
                              and any(isinstance(target, ast.Name) and target.id == 'CONFIG' for target in node.targets))
            config = json.loads(ast.literal_eval(assignment.value.args[0]))
            self.assertEqual(Path(config['env']['OH_DATA_HOME']), Path(tmp).resolve())
            self.assertEqual([c.args[0] for c in schtasks.call_args_list], ['/Query', '/Create', '/Run'])
            self.assertIn('<MultipleInstancesPolicy>StopExisting</MultipleInstancesPolicy>', task)
            service.uninstall()
            self.assertFalse((Path(tmp) / 'bin/dashboard.pyw').exists())
            self.assertEqual(schtasks.call_args_list[-1].args[:2], ('/Delete', '/F'))

    def test_failed_service_start_restores_the_prior_task_and_starter(self):
        from . import service
        from .storage import Refused
        for previous in (None, b'<previous-task/>'):
            with self.subTest(previous=previous), tempfile.TemporaryDirectory() as tmp, \
                    patch.dict(os.environ, {'OH_DATA_HOME': tmp}), patch('oh.service.schtasks', side_effect=TaskScheduler(previous, ['/Run'])) as calls:
                starter=Path(tmp)/'bin/dashboard.pyw';starter.parent.mkdir();(starter.parent/'oh').write_text('launcher')
                if previous:starter.write_bytes(b'old starter')
                with self.assertRaisesRegex(Refused, 'previous task and starter were restored'):service.install_windows()
                scheduler=calls.side_effect
                self.assertEqual(scheduler.definition, previous)
                self.assertEqual(starter.read_bytes() if starter.exists() else None, b'old starter' if previous else None)
                self.assertEqual(scheduler.running, bool(previous))

    def test_failed_service_removal_keeps_the_starter_and_reports_recovery(self):
        from . import service
        from .storage import Refused
        for failure in ('/End', '/Delete'):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as tmp, \
                    patch.dict(os.environ, {'OH_DATA_HOME': tmp}), patch('oh.system.WINDOWS', True), \
                    patch('oh.service.schtasks', side_effect=TaskScheduler(b'<task/>', [failure])) as calls:
                starter=Path(tmp)/'bin/dashboard.pyw';starter.parent.mkdir();starter.write_bytes(b'old starter')
                with self.assertRaisesRegex(Refused, 'starter was retained'):service.uninstall()
                self.assertTrue(starter.exists());self.assertIsNotNone(calls.side_effect.definition)

    def test_failed_service_rollback_keeps_recovery_files(self):
        from . import service
        from .storage import Refused
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {'OH_DATA_HOME': tmp}), \
                patch('oh.service.schtasks', side_effect=TaskScheduler(b'<old/>', ['/Run', '/Delete'])):
            starter=Path(tmp)/'bin/dashboard.pyw';starter.parent.mkdir();starter.write_bytes(b'old starter');(starter.parent/'oh').write_text('launcher')
            with self.assertRaisesRegex(Refused, 'rollback is incomplete'):service.install_windows()
            self.assertEqual((Path(tmp)/'service/dashboard-previous.xml').read_bytes(), b'<old/>')
            self.assertEqual((Path(tmp)/'service/dashboard-previous.pyw').read_bytes(), b'old starter')
            self.assertTrue(starter.exists())

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
        def hiding(host, root, profile, prompt, role, directory, context, **kw):
            if role != 'review':(Path(root) / '.gitattributes').write_text('* -diff\n')  # a worker hiding its change
            return fake(host, root, profile, prompt, role, directory, context, **kw)
        run(test.root, hiding)
        diff, prompt = seen[0]
        self.assertIn('+++ b/output.txt', diff);self.assertIn('+1', diff);self.assertNotIn('Binary files', diff)
        self.assertIn('subject.diff', prompt)


class TaskScheduler:
    """Simulates registration and execution separately, including partial failures."""
    def __init__(self, definition=None, failures=()):
        self.definition=definition;self.running=bool(definition);self.failures=list(failures)

    def __call__(self, *args, check=True):
        command=args[0]
        if self.failures and command==self.failures[0]:
            self.failures.pop(0)
            raise subprocess.CalledProcessError(1, args, stderr=b'simulated failure')
        output=b''
        if command=='/Query':
            output=(b'"\\OH dashboard","next","state"\n' if self.definition is not None else b'') if '/CSV' in args or 'CSV' in args else self.definition
        elif command=='/Create':self.definition=Path(args[args.index('/XML')+1]).read_bytes()
        elif command=='/Run':self.running=True
        elif command=='/End':self.running=False
        elif command=='/Delete':self.definition=None
        return subprocess.CompletedProcess(args, 0, stdout=output, stderr=b'')


@unittest.skipUnless(os.name == 'nt', 'Windows only')
class NativeWindowsTest(unittest.TestCase):
    def test_simultaneous_python_bootstraps_keep_the_first_complete_interpreter(self):
        import time
        from . import service
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp);data=folder/'data';wrapper=folder/'bootstrap.ps1'
            old=data/'python/3.13.0';old.mkdir(parents=True)
            for name in ('python.exe','pythonw.exe'):(old/name).write_text('old interpreter')
            (data/'python/current').write_text('3.13.0')
            (data/'bin').mkdir();(data/'bin/oh').write_text('launcher')
            with patch.dict(os.environ,{'OH_DATA_HOME':str(data)}), patch('oh.service.sys.executable',str(old/'python.exe')), patch('oh.service.schtasks',TaskScheduler()):
                service.install_windows()
            from xml.etree import ElementTree
            task=ElementTree.fromstring((data/'service/dashboard-task.xml').read_text(encoding='utf-16'))
            action=Path(task.find('.//{*}Command').text)
            self.assertEqual(action,old/'pythonw.exe')
            quote=lambda value:"'"+str(value).replace("'","''")+"'"
            wrapper.write_text("\n".join([
                'param([string]$Name)', "$ErrorActionPreference = 'Stop'",
                '$env:OH_DATA_HOME = '+quote(data),
                '$env:OH_PYTHON_DOWNLOAD = $null',
                '$fixture = '+quote(folder),
                'function Invoke-WebRequest { param($UseBasicParsing, $Uri, $OutFile) Set-Content $OutFile "fixture" }'.replace('$UseBasicParsing','[switch]$UseBasicParsing'),
                "function Get-FileHash { param($Algorithm, $Path) [pscustomobject]@{Hash='d297e5ff019966817ad8502465176139f2d3d840fa4ed84b13bed399a6ab1f15'} }",
                "$env:PROCESSOR_ARCHITECTURE='AMD64'; $env:PROCESSOR_ARCHITEW6432=$null",
                'function Expand-Archive { param($Path, $DestinationPath)',
                '  New-Item -ItemType Directory $DestinationPath | Out-Null',
                "  Set-Content (Join-Path $DestinationPath 'python.exe') $Name",
                "  Set-Content (Join-Path $fixture ($Name+'.expanded')) 'ready'",
                "  if ($Name -eq 'first') {",
                '    $deadline=[DateTime]::UtcNow.AddSeconds(30)',
                "    while (-not (Test-Path (Join-Path $fixture 'release'))) {",
                "      if ([DateTime]::UtcNow -gt $deadline) { throw 'barrier timeout' }; Start-Sleep -Milliseconds 50",
                '    }',
                '  }',
                '}',
                "Set-Content (Join-Path $fixture ($Name+'.started')) 'ready'",
                '& '+quote(SCRIPTS/'get-python.ps1'),
            ]))
            children=[]
            def start(name):
                child=subprocess.Popen(['powershell','-NoProfile','-ExecutionPolicy','Bypass','-File',str(wrapper),name],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
                children.append(child);return child
            def wait_for(name):
                deadline=time.monotonic()+20
                while not (folder/name).exists():
                    if time.monotonic()>deadline:self.fail('Bootstrap barrier timeout: '+name)
                    time.sleep(.05)
            try:
                start('first');wait_for('first.expanded')
                start('second');wait_for('second.started')
                # Without serialization, the second setup publishes while the first is paused.
                time.sleep(1)
                self.assertFalse((folder/'second.expanded').exists())
                (folder/'release').touch()
                for child in children:
                    out,err=child.communicate(timeout=30)
                    self.assertEqual(child.returncode,0,out+err)
                self.assertEqual((data/'python/3.14.7/python.exe').read_text().strip(),'first')
                self.assertEqual((data/'python/current').read_text().strip(),'3.14.7')
                self.assertEqual(action.read_text(),'old interpreter')
                self.assertEqual((old/'python.exe').read_text(),'old interpreter')
                self.assertFalse((folder/'second.expanded').exists())
                # Recovery after directory publication but before marker publication preserves the winner.
                (data/'python/current').unlink()
                recovery=start('recovery');out,err=recovery.communicate(timeout=30)
                self.assertEqual(recovery.returncode,0,out+err)
                self.assertEqual((data/'python/3.14.7/python.exe').read_text().strip(),'first')
            finally:
                for child in children:
                    if child.poll() is None:child.kill()
                    child.communicate()

    def test_acceptance_check_selects_installed_and_private_python(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp);data=folder/'custom data';private=data/'python/3.14.7/python.exe'
            private.parent.mkdir(parents=True);private.write_bytes(b'fixture')
            (data/'python/current').write_text('3.14.7')
            downloader=folder/'download.ps1';downloader.write_text('$global:downloadCalled = $true')
            quote=lambda value: "'"+str(value).replace("'", "''")+"'"
            script=folder/'check.ps1'
            script.write_text("\n".join([
                "$ErrorActionPreference = 'Stop'",
                '. '+quote(HOME/'integrations/windows-python.ps1'),
                '$expected = '+quote(sys.executable),
                # Test each candidate in isolation, including py's -3 argument.
                "foreach ($name in @('python3', 'python', 'py')) {",
                '  function Get-Command { param($Name, $CommandType, $ErrorAction) if ($Name -eq $script:selected) { [pscustomobject]@{Source=$script:program} } }',
                '  $script:selected = $name',
                '  $script:program = '+quote(folder/'python.cmd'),
                '''  $lines = @('@echo off'); if ($name -eq 'py') { $lines += @('@if not "%1"=="-3" exit /b 7', '@echo '+$expected); } else { $lines += '@echo '+$expected }; $lines += '@exit /b 0' ''',
                '  Set-Content -Encoding ascii $script:program $lines',
                '  $actual = Resolve-CheckPython '+quote(data)+' '+quote(downloader),
                '  if ($actual -ne $expected -or $global:downloadCalled) { throw "Installed Python not selected: $name / $actual" }',
                '}',
                "function Get-Command { param($Name, $CommandType, $ErrorAction) return $null }",
                '$actual = Resolve-CheckPython '+quote(data)+' '+quote(downloader),
                'if ($actual -ne '+quote(private)+' -or -not $global:downloadCalled) { throw "Private Python not selected: $actual" }',
            ]))
            result=subprocess.run(['powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', str(script)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout+result.stderr)

    def test_only_you_or_administrators_may_change_a_host_program(self):
        from .system import untrusted
        folder = Path(tempfile.mkdtemp());self.addCleanup(shutil.rmtree, folder, ignore_errors=True)
        program = folder / 'host.exe';program.write_bytes(b'MZ')
        self.assertIsNone(untrusted(program, 'file'))
        subprocess.run(['icacls', str(program), '/grant', '*S-1-3-4:(M)'], check=True, capture_output=True)
        self.assertIsNone(untrusted(program, 'file'))
        subprocess.run(['icacls', str(program), '/grant', '*S-1-1-0:(M)'], check=True, capture_output=True)
        self.assertIn('S-1-1-0', untrusted(program, 'file'))
        subprocess.run(['icacls', str(folder), '/grant', '*S-1-5-32-545:(OI)(CI)(W)'], check=True, capture_output=True)
        self.assertIn('S-1-5-32-545', untrusted(folder, 'folder'))

    def test_oh_never_runs_a_command_planted_in_the_checkout(self):
        checkout = Path(tempfile.mkdtemp());self.addCleanup(shutil.rmtree, checkout, ignore_errors=True)
        # A self-contained program as "git": whoami answers "git -C ..." with "Invalid argument/option".
        shutil.copy(Path(os.environ['SystemRoot']) / 'System32/whoami.exe', checkout / 'git.exe')
        env = os.environ | {'OH_DATA_HOME': str(checkout / 'state')}
        result = subprocess.run([sys.executable, '-I', '-X', 'utf8', str(HOME / 'oh'), '--root', str(checkout), 'config'],
                                cwd=checkout, env=env, capture_output=True, text=True)
        self.assertNotIn('Invalid argument', result.stderr + result.stdout)
        self.assertIn(result.returncode, (0, 2), result.stderr)

    def test_oh_cmd_never_runs_a_python_planted_in_the_current_folder(self):
        folder = Path(tempfile.mkdtemp());self.addCleanup(shutil.rmtree, folder, ignore_errors=True)
        marker = folder / 'ran'
        for name in ('python3.cmd', 'python.cmd', 'py.cmd', 'powershell.cmd'):(folder / name).write_text(f'@echo x> "{marker}"\r\n')
        subprocess.run(['cmd', '/c', str(SCRIPTS / 'oh.cmd'), 'status'], cwd=folder, env=os.environ | {'OH_DATA_HOME': str(folder / 'state')},
                       capture_output=True, text=True)
        self.assertFalse(marker.exists())

    def test_a_check_may_run_a_script_in_the_project(self):
        from .verification import verify
        root = Path(tempfile.mkdtemp());self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        (root / 'ok.cmd').write_text('@exit /b 0\r\n')
        self.addCleanup(os.chdir, os.getcwd());os.chdir(HOME)
        subprocess.run(['git', 'init', '-q', str(root)], check=True)
        subprocess.run(['git', '-C', str(root), 'add', 'ok.cmd'], check=True)
        subprocess.run(['git', '-C', str(root), '-c', 'user.name=t', '-c', 'user.email=t@example.invalid', 'commit', '-qm', 'check script'], check=True)
        with patch.dict(os.environ, {'OH_DATA_HOME': str(root / 'state')}):
            results = verify(root, [{'name': 'ok', 'command': ['.\\ok.cmd']}, {'name': 'cmd', 'command': ['cmd', '/c', 'ok.cmd']}], 'p')
        self.assertEqual([r['returncode'] for r in results], [0, 0], results)

    def test_oh_cmd_starts_oh_from_cmd_and_powershell(self):
        env = os.environ | {'OH_DATA_HOME': tempfile.mkdtemp()}
        for shell in (['cmd', '/c'], ['powershell', '-NoProfile', '-Command', '&']):
            result = subprocess.run([*shell, str(SCRIPTS / 'oh.cmd'), 'status'], env=env, capture_output=True, text=True)
            self.assertIn('OH is not set up', result.stderr + result.stdout, shell)


if __name__ == '__main__':
    unittest.main()
