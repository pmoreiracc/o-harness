import contextlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from .installation import build, verify_package
from .storage import Refused
# POSIX users run OH's scripts directly, so tests do too; Windows needs the interpreter.
RUN=[sys.executable,'-I'] if os.name=='nt' else []


class InstallationTest(unittest.TestCase):
    @staticmethod
    def development():
        import importlib.util
        from .config import HOME
        spec = importlib.util.spec_from_file_location('oh_dev', HOME / 'integrations/oh_dev.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_development_switch_restores_both_hosts_after_refresh_and_failure(self):
        """CONTRIBUTING: switching keeps releases installed and preserves their enabled state."""
        dev = self.development()
        with tempfile.TemporaryDirectory() as tmp, patch.object(Path, 'home', return_value=Path(tmp)), patch.dict(os.environ, {'OH_DEV_NORMAL_DATA_HOME': '',
                'CODEX_HOME': str(Path(tmp) / 'codex'), 'CLAUDE_CONFIG_DIR': str(Path(tmp) / 'claude')}):
            os.environ.pop('OH_DATA_HOME', None)
            original = {'o-harness@released': True, 'o-harness@disabled': False}
            plugins = {host: dict(original) for host in dev.HOSTS}
            marketplaces = {}
            failed = []
            race = []
            protocol = []
            bad_response = []
            parse_installed, parse_marketplace = dev.installed, dev.marketplace
            def inventory(host):
                if bad_response:
                    with patch.object(dev, 'call', return_value=bad_response.pop()):return parse_installed(host)
                return dict(plugins[host])
            def command(host, *args):
                if args[1] == 'marketplace':
                    if args[2] == 'remove':
                        if host not in marketplaces:raise RuntimeError('marketplace not registered')
                        del marketplaces[host]
                    elif args[2] == 'add':
                        if 'register' in failed:raise RuntimeError('registration failed')
                        marketplaces[host] = str(args[3])
                        if 'register-after' in failed:raise RuntimeError('registration failed after applying')
                if args[1] in ('add', 'install'):
                    if 'install' in failed:raise RuntimeError('install failed')
                    plugins[host][dev.PLUGIN] = True
                    plugins[host].setdefault('o-harness@during-install', True)
                    if protocol:bad_response.append(protocol[0])
            def enabled(host, plugin, value):
                plugins[host][plugin] = value
                if 'on' in race and plugin == dev.PLUGIN and value:plugins[host]['o-harness@during-enable'] = True
                if 'off' in race and plugin == 'o-harness@released':plugins[host]['o-harness@disabled'] = True
            snapshot = (dev.home() / 'builds/snapshot', {'version': '0.5.0-SNAPSHOT.1',
                        'source': str(dev.SOURCE), 'source_revision': 'revision'})
            with patch.object(dev, 'installed', side_effect=inventory), \
                    patch.object(dev, 'call', side_effect=command), patch.object(dev, 'enable', side_effect=enabled), \
                    patch.object(dev, 'marketplace', side_effect=lambda host: marketplaces.get(host)), \
                    patch.object(dev, 'build'), patch.object(dev, 'create_snapshot', return_value=snapshot) as packaged, \
                    contextlib.redirect_stdout(io.StringIO()):
                dev.switch('on', dev.HOSTS)
                packaged.assert_called_once()  # the same snapshot powers both hosts
                self.assertEqual({r['build'] for r in dev.read(dev.home() / 'switch.json').values()}, {str(snapshot[0])})
                original['o-harness@during-install'] = True
                for host in dev.HOSTS:
                    self.assertFalse(plugins[host]['o-harness@during-install'])
                original['o-harness@later'] = True
                for host in dev.HOSTS:plugins[host]['o-harness@later'] = True
                with contextlib.redirect_stdout(io.StringIO()) as status:
                    dev.main(['status'])
                self.assertIn('o-harness@later', status.getvalue())
                dev.switch('on', dev.HOSTS)
                for host in dev.HOSTS:
                    self.assertTrue(plugins[host][dev.PLUGIN])
                    for plugin in original:self.assertFalse(plugins[host][plugin])
                dev.switch('off', ('codex',))
                self.assertTrue(plugins['claude'][dev.PLUGIN])
                dev.switch('off', dev.HOSTS)
                for host in dev.HOSTS:self.assertEqual(plugins[host], original | {dev.PLUGIN: False})
                packaged.reset_mock()
                with patch.object(dev, 'read_snapshot', return_value=snapshot):
                    dev.main(['on', '--build', str(snapshot[0])])
                packaged.assert_not_called()  # selecting an existing snapshot must not silently rebuild it
                dev.switch('off', dev.HOSTS)
                dev.switch('on', dev.HOSTS, live=True)
                self.assertEqual({r['mode'] for r in dev.read(dev.home() / 'switch.json').values()}, {'live'})
                dev.switch('off', dev.HOSTS)
                dev.switch('on', ('codex',))
                failed.append('install')
                with self.assertRaisesRegex(RuntimeError, 'install failed'):dev.switch('on', ('codex',))
                self.assertEqual(plugins['codex'], original | {dev.PLUGIN: False})
                self.assertEqual(dev.read(dev.home() / 'switch.json')['codex']['phase'], 'off')
                for boundary in ('register', 'register-after'):
                    failed[:] = [boundary]
                    with self.assertRaisesRegex(RuntimeError, 'registration failed'):dev.switch('on', ('codex',))
                    self.assertEqual('codex' in marketplaces, boundary == 'register-after')
                    failed.clear()
                    dev.switch('on', ('codex',))
                    self.assertTrue(plugins['codex'][dev.PLUGIN])
                race.append('on')
                with self.assertRaisesRegex(RuntimeError, 'settings changed during'):dev.switch('on', ('codex',))
                self.assertFalse(plugins['codex'][dev.PLUGIN])
                original['o-harness@during-enable'] = True
                self.assertEqual(plugins['codex'], original | {dev.PLUGIN: False})
                race.clear()
                dev.switch('on', ('codex',))
                dev.switch('off', ('codex',))
                self.assertEqual(plugins['codex'], original | {dev.PLUGIN: False})
                baseline = {host: dict(flags) for host, flags in plugins.items()}
                dev.switch('on', dev.HOSTS)
                race.append('off')
                with self.assertRaisesRegex(RuntimeError, 'settings changed during restoration'):dev.switch('off', dev.HOSTS)
                for record in dev.read(dev.home() / 'switch.json').values():self.assertEqual(record['phase'], 'needs recovery')
                race.clear()
                dev.switch('off', dev.HOSTS)
                self.assertEqual(plugins, baseline)
                for host, response in (('codex', '{'), ('claude', '{}')):
                    protocol[:] = [response]
                    with contextlib.redirect_stderr(io.StringIO()) as error:
                        with self.assertRaises(SystemExit) as stopped:dev.main(['on', '--host', host])
                    self.assertEqual(stopped.exception.code, 1)
                    self.assertIn('invalid plugin protocol', error.getvalue())
                    self.assertIn(f'oh-dev off --host {host}', error.getvalue())
                    self.assertEqual(dev.read(dev.home() / 'switch.json')[host]['phase'], 'off')
                    self.assertEqual(plugins[host], baseline[host])
                normal = Path(tmp) / '.local/share/o-harness'
                self.assertFalse(normal.exists())
                self.assertEqual(list(normal.parent.glob('.oh-snapshot-*.lock')), [])
                self.assertNotIn('OH_DATA_HOME', os.environ)

    def test_development_bridges_use_live_source_and_isolated_data(self):
        """CONTRIBUTING: every host entry routes to source without activating the installed core."""
        from .config import HOME
        dev = self.development()
        with tempfile.TemporaryDirectory() as tmp, patch.object(Path, 'home', return_value=Path(tmp)), patch.dict(os.environ, {'OH_DEV_NORMAL_DATA_HOME': '',
                'CODEX_HOME': str(Path(tmp) / 'codex'), 'CLAUDE_CONFIG_DIR': str(Path(tmp) / 'claude'), 'HOME': tmp, 'USERPROFILE': tmp}):
            os.environ.pop('OH_DATA_HOME', None)
            base = dev.home();base.mkdir(parents=True)
            plugin = dev.build('codex', base / 'build')
            normal = Path(tmp) / '.local/share/o-harness'
            self.assertFalse(normal.exists())
            self.assertEqual(list(normal.parent.glob('.oh-snapshot-*.lock')), [])
            self.assertNotIn('OH_DATA_HOME', os.environ)
            # The production package remains intact; only the generated entry points differ.
            verify_package(plugin / 'core')
            consumer = base / 'consumer';consumer.mkdir()
            launcher = plugin / 'scripts/oh'
            def run(*args, **options):
                return subprocess.run([sys.executable, '-I', str(launcher), *args], cwd=consumer,
                                      capture_output=True, text=True, **options)
            result = run('resource', 'workflows/propose/SKILL.md')
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn((HOME / 'workflows/propose/SKILL.md').read_text().strip(), result.stdout)
            self.assertFalse((base / 'data/runtime/active.json').exists())
            self.assertEqual(list(consumer.iterdir()), [])
            # Change the generated package's resource: the bridge must still read the source checkout.
            (plugin / 'core/workflows/propose/SKILL.md').write_text('wrong packaged workflow')
            self.assertEqual(run('resource', 'workflows/propose/SKILL.md').stdout, result.stdout)
            # Execute a source hook via its development sibling launcher. An ordinary prompt is inert.
            hook = subprocess.run([sys.executable, '-I', str(plugin / 'scripts/human-event.py'), 'codex'],
                                  input=json.dumps({'prompt': 'hello', 'cwd': str(consumer)}), capture_output=True, text=True)
            self.assertEqual(hook.returncode, 0, hook.stderr)
            self.assertEqual(hook.stdout, '')
            self.assertNotEqual(run('service-install').returncode, 0)
            # Check argument boundaries without ever dispatching a real service/setup command.
            for command in ('setup', 'service-install', 'service-uninstall'):
                for prefix in ([], ['--'], ['--root', str(consumer), '--'], ['--ro=' + str(consumer)]):
                    with patch('sys.argv', ['oh', *prefix, command]), patch.object(dev.runpy, 'run_path') as dispatch:
                        with self.assertRaisesRegex(SystemExit, 'Development is isolated'):
                            dev.launch(HOME, base / 'data', 'cli', launcher)
                        dispatch.assert_not_called()
            self.assertEqual(list(consumer.iterdir()), [])
            subprocess.run(['git', 'init', '-q', str(consumer)], check=True)
            registered = run('init', env=os.environ | {'OH_DATA_HOME': str(Path(tmp) / 'released-data')})
            self.assertEqual(registered.returncode, 0, registered.stderr)
            self.assertTrue(list((base / 'data/registry/checkouts').glob('*.json')))
            self.assertFalse((Path(tmp) / 'released-data').exists())
            self.assertEqual([p.name for p in consumer.iterdir()], ['.git'])
            # A hook passes its intentionally isolated data to the generated sibling CLI.
            hooked = subprocess.run([sys.executable, '-I', str(plugin / 'scripts/human-event.py'), 'codex'],
                input=json.dumps({'prompt': '/oh-propose', 'cwd': str(consumer), 'session_id': 'dev-test',
                                  'hook_event_name': 'UserPromptSubmit', 'turn_id': 'fixture'}), capture_output=True, text=True)
            self.assertEqual(hooked.returncode, 0, hooked.stderr)
            self.assertIn('OH:', hooked.stdout)

    def test_development_snapshot_freezes_all_entries_and_exec_selects_it(self):
        """CONTRIBUTING: snapshots survive source edits/removal and never activate the released core."""
        from . import config, installation
        from .config import HOME
        dev = self.development()
        with tempfile.TemporaryDirectory() as tmp, patch.object(Path, 'home', return_value=Path(tmp)), \
                patch.dict(os.environ, {'OH_DEV_NORMAL_DATA_HOME': '', 'HOME': tmp, 'USERPROFILE': tmp,
                                       'CODEX_HOME': str(Path(tmp) / 'codex'), 'CLAUDE_CONFIG_DIR': str(Path(tmp) / 'claude')}):
            os.environ.pop('OH_DATA_HOME', None)
            # A small source fixture using the real packager, without a second Git repository or run.
            template = Path(tmp) / 'source/o-harness'
            with dev.development_data():build(template, 'claude')
            source = template / 'core'
            shutil.copytree(HOME / 'plugins', source / 'plugins')
            (source / 'integrations').mkdir()
            shutil.copy2(HOME / 'integrations/oh_dev.py', source / 'integrations/oh_dev.py')
            workflow = source / 'workflows/propose/SKILL.md'
            workflow.write_text('uncommitted fixture workflow', encoding='utf-8')
            with patch.object(dev, 'SOURCE', source), patch.object(installation, 'HOME', source), patch.object(config, 'HOME', source):
                revision = config.version()
                with patch.object(dev, 'version', side_effect=[revision, 'editor saved', revision, revision]):
                    first, metadata = dev.create_snapshot()
                self.assertEqual(list((dev.home() / 'builds').iterdir()), [first])  # discarded partial copy was removed
                workflow.write_text('later fixture workflow', encoding='utf-8')
                second, other = dev.create_snapshot()
            self.assertNotEqual(metadata['version'], other['version'])
            self.assertRegex(metadata['version'], r'^\d+\.\d+\.\d+-SNAPSHOT\.\d+$')
            self.assertFalse((dev.home() / 'switch.json').exists())  # build alone changes no host selection
            self.assertEqual(dev.read_snapshot(first), (first, metadata))
            shutil.rmtree(template)  # windows-ok: packager fixture has no Git metadata; all entries must survive source removal
            state = {}
            for host in dev.HOSTS:
                plugin = first / host / 'plugins/o-harness'
                revision = json.loads((plugin / 'core/revision.json').read_text())
                self.assertEqual(revision['version'], metadata['version'])
                verify_package(plugin / 'core')
                command = [sys.executable, '-I', str(plugin / 'scripts/oh')]
                result = subprocess.run([*command, 'resource', 'workflows/propose/SKILL.md'], capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn('uncommitted fixture workflow', result.stdout)
                for script, args, payload in (('human-event.py', [host], {'prompt': 'hello'}),
                                              ('gate-hook.py', ['pre'], {}),
                                              ('mcp-server', [], {'id': 1, 'method': 'initialize', 'params': {}})):
                    invoked = subprocess.run([sys.executable, '-I', str(plugin / 'scripts' / script), *args],
                        input=json.dumps(payload)+'\n', capture_output=True, text=True)
                    self.assertEqual(invoked.returncode, 0, invoked.stderr)
                    if script == 'mcp-server':self.assertIn('protocolVersion', invoked.stdout)
                state[host] = {'phase': 'on', 'mode': 'snapshot', 'source': str(source), 'build': str(first),
                               'marketplace': str(first / host), 'host_home': dev.host_home(host)}
            dev.write(dev.home() / 'switch.json', state)
            self.assertIn(dev.selected_entry(), [first / host / 'plugins/o-harness/scripts/oh' for host in dev.HOSTS])
            with patch.object(dev.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0)) as execute:
                with self.assertRaises(SystemExit) as done:dev.main(['exec', '--root', tmp, 'status'])
                self.assertEqual(done.exception.code, 0)
                self.assertEqual(execute.call_args.args[0][2:], [str(dev.selected_entry()), '--root', tmp, 'status'])
            state['claude'].update(build=str(second), marketplace=str(second / 'claude'))
            dev.write(dev.home() / 'switch.json', state)
            with self.assertRaisesRegex(RuntimeError, 'different builds'):dev.selected_entry()
            self.assertEqual(dev.selected_entry('claude'), second / 'claude/plugins/o-harness/scripts/oh')
            with patch.object(dev.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0)) as execute:
                with self.assertRaises(SystemExit):dev.main(['exec', '--host', 'claude', 'status'])
                self.assertEqual(execute.call_args.args[0][2:], [str(dev.selected_entry('claude')), 'status'])
            # A corrupt build is refused before installation, without touching the released installation.
            (first / 'claude/plugins/o-harness/core/workflows/propose/SKILL.md').write_text('changed')
            with self.assertRaisesRegex(Refused, 'changed or is incomplete'):dev.read_snapshot(first)
            self.assertFalse((Path(tmp) / '.local/share/o-harness').exists())
            self.assertFalse((dev.home() / 'data/runtime/active.json').exists())

    def test_both_hosts_share_one_core_and_setup_is_explicit_and_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            base=Path(tmp);consumer=base/'product';consumer.mkdir()
            (consumer/'manual.txt').write_text('unchanged')
            first=base/'codex/o-harness';second=base/'claude/o-harness'
            a=build(first,'codex');b=build(second,'claude')
            self.assertEqual(a['revision'],b['revision'])
            self.assertNotIn('disable-model-invocation: true',(first/'skills/oh-deliver/SKILL.md').read_text())
            self.assertIn('allow_implicit_invocation: false',(first/'skills/oh-deliver/agents/openai.yaml').read_text())
            self.assertIn('disable-model-invocation: true',(second/'skills/oh-deliver/SKILL.md').read_text())
            env=os.environ|{'OH_DATA_HOME':str(base/'state')}
            entry=first/'core/oh'
            for _ in range(2):
                result=subprocess.run([*RUN,str(entry),'setup','--development'],cwd=consumer,env=env,capture_output=True,text=True)
                self.assertEqual(result.returncode,0,result.stderr)
            launcher=base/'state/bin/oh'
            status=subprocess.run([*RUN,str(launcher),'resource','workflows/deliver/SKILL.md'],cwd=consumer,env=env,capture_output=True,text=True)
            self.assertEqual(status.returncode,0,status.stderr)
            self.assertTrue((first/'core/dashboard/app.js').is_file())
            self.assertEqual([p.name for p in consumer.iterdir()],['manual.txt'])
            self.assertEqual((consumer/'manual.txt').read_text(),'unchanged')
            self.assertEqual(len(list((base/'state/versions').iterdir())),1)
            self.assertEqual(verify_package(first/'core'),a['revision'])
            (first/'core/runtime/oh/cli.py').write_text('changed')
            with self.assertRaises(Refused):verify_package(first/'core')

    @staticmethod
    def package(path,revision,version):
        from .installation import inventory
        from .storage import atomic_json
        build(path,'codex');core=path/'core'
        atomic_json(core/'revision.json',{'revision':revision,'version':version})
        atomic_json(core/'package.json',{'schema_version':1,'revision':revision,'files':inventory(core)})
        return path/'scripts'

    def test_plugin_update_activates_only_a_newer_core(self):
        from .storage import read_json
        with tempfile.TemporaryDirectory() as tmp:
            base=Path(tmp);env=os.environ|{'OH_DATA_HOME':str(base/'state')}
            plugins={n:self.package(base/f'v{n}/o-harness',str(n)*40,f'0.{n}.0') for n in (1,2,3)}
            def use(n):
                result=subprocess.run([*RUN,str(plugins[n]/'oh'),'--root',tmp,'resource','workflows/oh/SKILL.md'],env=env,capture_output=True,text=True)
                self.assertEqual(result.returncode,0,result.stderr)
                return read_json(base/'state/runtime/active.json')['revision'][0]
            self.assertEqual(use(1),'1')
            self.assertEqual(use(3),'3')
            # An older plugin still installed in another host never downgrades the shared core.
            self.assertEqual(use(2),'3')
            self.assertEqual(use(1),'3')
            # The same rule holds under the install lock, for hosts racing the launcher's check.
            older=subprocess.run([*RUN,str(plugins[2].parent/'core/oh'),'setup','--if-newer'],env=env,capture_output=True,text=True)
            self.assertEqual(older.returncode,0,older.stderr)
            self.assertEqual(read_json(base/'state/runtime/active.json')['revision'][0],'3')

    def test_bare_choices_never_install_the_bundled_core(self):
        with tempfile.TemporaryDirectory() as tmp:
            base=Path(tmp);env=os.environ|{'OH_DATA_HOME':str(base/'state')}
            scripts=self.package(base/'v1/o-harness','1'*40,'0.1.0')
            def send(prompt):
                return subprocess.run([sys.executable,str(scripts/'human-event.py'),'claude'],input=json.dumps({'prompt':prompt,'cwd':tmp}),
                    env=env,capture_output=True,text=True,check=True).stdout
            self.assertEqual(send('continue'),'')
            self.assertFalse((base/'state').exists())
            self.assertIn('not registered',send('/oh-propose a plan'))
            self.assertTrue((base/'state/runtime/active.json').is_file())

    def test_ordinary_prompt_hook_has_no_setup_or_project_side_effects(self):
        from .config import HOME
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            result=subprocess.run([sys.executable,str(HOME/'plugins/o-harness/scripts/human-event.py'),'codex'],
                input=json.dumps({'prompt':'Fix the button styling','cwd':tmp}),cwd=root,capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertEqual(result.stdout,'')
            self.assertEqual(list(root.iterdir()),[])

    def test_a_plain_message_reaches_oh_only_while_oh_waits_for_it(self):
        import io,runpy
        from unittest.mock import patch
        from .config import HOME
        with tempfile.TemporaryDirectory() as tmp:
            def launched(session,prompt='Search my notes',recognized=False):
                stdin=io.TextIOWrapper(io.BytesIO(json.dumps({'prompt':prompt,'cwd':tmp,'session_id':session}).encode()))
                with patch.dict(os.environ,{'OH_DATA_HOME':tmp}),patch('sys.stdin',stdin),patch('sys.argv',['hook','claude']),\
                        patch('subprocess.run') as run:
                    run.return_value.returncode,run.return_value.stdout=0,''
                    with self.assertRaises(SystemExit) if not recognized and not (Path(tmp)/'waiting'/(session+'.json')).exists() else contextlib.nullcontext():
                        runpy.run_path(str(HOME/'plugins/o-harness/scripts/human-event.py'),run_name='__main__')
                    return run.called
            (Path(tmp)/'waiting').mkdir();(Path(tmp)/'waiting/s.json').write_text('{}')
            self.assertTrue(launched('s'))
            self.assertFalse(launched('other'))
            from .entry import CHOICES
            for choice in CHOICES:self.assertTrue(launched('other',choice,recognized=True),choice)
            for removed in ('fix scope','fix findings'):self.assertFalse(launched('other',removed),removed)
