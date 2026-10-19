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
    def test_release_updater_reports_versions_and_continues_after_host_failure(self):
        from . import updater
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {'OH_DATA_HOME': tmp}), \
                patch.object(updater.hosts, 'executable') as executable, \
                patch.object(updater.hosts, 'trust', return_value={'path': 'codex'}) as trust, \
                patch.object(updater.hosts, 'installed') as installed, \
                patch.object(updater.hosts, 'codex_app_bin', return_value=Path(tmp) / 'app-bin'), \
                patch.object(updater.shutil, 'which') as which:
            native = Path(tmp) / 'native-codex';native.write_text('')
            app_copy = Path(tmp) / 'app-bin/0123456789abcdef/codex.exe';app_copy.parent.mkdir(parents=True);app_copy.write_text('')
            removed = Path(tmp) / 'removed/codex.exe'
            # On Windows a remembered path the Codex app removed or will replace is found again through the app;
            # elsewhere the remembered path is revalidated as before.
            saved_paths = {'missing_path': native, 'revalidation_timeout': native, 'posix_removed': removed,
                           'stale_app_path': Path(tmp) / 'app-bin/fedcba9876543210/codex.exe', 'app_copy': app_copy,
                           'undecided_app': app_copy, 'removed': removed, 'undecided_removed': removed, 'windows_native': native}
            windows = ('stale_app_path', 'app_copy', 'app_only', 'undecided_app', 'removed', 'undecided_removed', 'windows_native')
            for outcome in ('updated', 'missing_path', 'unavailable', 'current', 'failed', 'absent', 'invalid', 'downgrade',
                            'resolution_timeout', 'revalidation_timeout', *windows, 'posix_removed'):
                with self.subTest(outcome=outcome):
                    calls = []
                    trust.reset_mock();executable.reset_mock()
                    installed.side_effect = lambda name: app_copy if outcome == 'app_only' else None
                    versions = dict.fromkeys(updater.HOSTS, '0.5.0')
                    def resolve(name, root):
                        if name == 'codex' and outcome == 'resolution_timeout':raise subprocess.TimeoutExpired('codex --version', 10)
                        if name == 'codex' and outcome in ('undecided_app', 'undecided_removed'):raise updater.hosts.Undecided('Several app copies; reopen the app and retry.')
                        if name == 'codex' and outcome == 'removed':raise Refused('codex was not found on PATH. Install it or open the Codex app once.')
                        return name
                    def revalidate(name, path, root, **kwargs):
                        if outcome == 'revalidation_timeout':raise subprocess.TimeoutExpired('codex --version', 10)
                        return {'path': name}
                    executable.side_effect = resolve
                    trust.side_effect = revalidate
                    which.side_effect = lambda name, **kw: None if outcome in ('unavailable', *saved_paths, *windows) and name == 'codex' else 'installed'
                    record = Path(tmp) / 'hosts/codex.json'
                    if outcome in saved_paths:
                        record.parent.mkdir(exist_ok=True)
                        record.write_text(json.dumps({'path': str(saved_paths[outcome]), 'pinned': False}))
                    def command(args, **kwargs):
                        name, _, action, *rest = args
                        calls.append(args)
                        self.assertEqual(kwargs['cwd'], Path.home())
                        if action == 'list':
                            if name == 'codex':self.assertEqual(rest, ['--marketplace', 'o-harness', '--json'])
                            else:self.assertEqual(rest, ['--json'])
                            item = {'pluginId' if name == 'codex' else 'id': updater.PLUGIN,
                                    'version': versions[name], 'scope': 'user'}
                            items = [] if outcome == 'absent' and versions[name] == '0.5.0' else [item]
                            if outcome == 'invalid':item['version'] = None
                            return SimpleNamespace(returncode=0, stdout=json.dumps({'installed': items} if name == 'codex' else items))
                        if outcome == 'failed' and name == 'codex':
                            return SimpleNamespace(returncode=1, stdout='', stderr='network unavailable')
                        if action == 'marketplace':
                            expected = (['add', 'pmoreiracc/o-harness', '--ref', 'dist'] if name == 'codex' else
                                        ['add', 'pmoreiracc/o-harness#dist']) if outcome == 'absent' else \
                                       ['upgrade' if name == 'codex' else 'update', 'o-harness']
                            self.assertEqual(rest, expected)
                            if name == 'codex' and outcome != 'absent':
                                versions[name] = '0.4.0' if outcome == 'downgrade' else '0.5.0' if outcome == 'current' else '0.6.0'
                        else:
                            self.assertEqual([action, *rest], ['add', updater.PLUGIN] if name == 'codex' else
                                             ['install' if outcome == 'absent' else 'update', updater.PLUGIN, '--scope', 'user'])
                            versions[name] = '0.4.0' if outcome == 'downgrade' else '0.5.0' if outcome == 'current' else '0.6.0'
                        return SimpleNamespace(returncode=0, stdout='')
                    output, error = io.StringIO(), io.StringIO()
                    with patch.object(updater.subprocess, 'run', side_effect=command), \
                            patch.object(updater.hosts, 'WINDOWS', outcome in windows), \
                            contextlib.redirect_stdout(output), contextlib.redirect_stderr(error):
                        result = updater.update(Path(tmp))
                    self.assertEqual(result, int(outcome in ('failed', 'invalid', 'downgrade', 'resolution_timeout', 'revalidation_timeout', 'removed', 'undecided_removed')))
                    if outcome != 'absent':
                        self.assertFalse(any(args[0] == 'codex' and args[2] == 'add' for args in calls),
                                         'An installed Codex plugin must not be reinstalled after marketplace refresh')
                    if outcome in ('updated', 'missing_path', 'posix_removed', *windows) and outcome not in ('removed', 'undecided_removed'):
                        for name in updater.HOSTS:self.assertIn(f'{name}: 0.5.0 -> 0.6.0', output.getvalue())
                        self.assertIn('new host session', output.getvalue())
                        if outcome in ('missing_path', 'posix_removed', 'undecided_app', 'windows_native'):
                            # An existing remembered copy stays usable when the app's copies are ambiguous.
                            trust.assert_called_once_with('codex', str(saved_paths[outcome]), Path(tmp), pinned=False)
                        elif outcome != 'updated':
                            trust.assert_not_called()
                            executable.assert_any_call('codex', Path(tmp))
                        if outcome in saved_paths:record.unlink()
                    elif outcome in ('removed', 'undecided_removed'):
                        # A removed remembered binary is named with its remedies; it is not an OS error or install advice.
                        remedy = ('Several app copies; reopen the app and retry.' if outcome == 'undecided_removed' else
                                  'Open the Codex app once so it installs its command-line binary, or name its native binary with: '
                                  'oh trust-host codex <absolute-path>.')
                        self.assertIn(f'codex: The codex executable OH remembered is gone: {removed}. {remedy} '
                                      'You can also run oh-update from a codex session.', error.getvalue())
                        self.assertNotIn('nstall it', error.getvalue())
                        trust.assert_not_called()
                        self.assertIn('claude: 0.5.0 -> 0.6.0', output.getvalue())
                        record.unlink()
                    elif outcome in ('resolution_timeout', 'revalidation_timeout'):
                        self.assertIn('codex: host identity check timed out. Retry oh-update.', error.getvalue())
                        self.assertIn('claude: 0.5.0 -> 0.6.0', output.getvalue())
                        if outcome == 'revalidation_timeout':record.unlink()
                    elif outcome == 'unavailable':
                        self.assertIn('codex: not found on PATH', output.getvalue())
                        self.assertIn('claude: 0.5.0 -> 0.6.0', output.getvalue())
                    elif outcome == 'current':
                        for name in updater.HOSTS:self.assertIn(f'{name}: 0.5.0 — up to date', output.getvalue())
                        self.assertNotIn('new host session', output.getvalue())
                    elif outcome == 'failed':
                        self.assertIn('network unavailable', error.getvalue())
                        self.assertIn('claude: 0.5.0 -> 0.6.0', output.getvalue())
                    elif outcome == 'absent':
                        for name in updater.HOSTS:self.assertIn(f'{name}: not installed -> 0.6.0', output.getvalue())
                    elif outcome == 'invalid':
                        self.assertTrue(all(args[2] == 'list' for args in calls))
                        self.assertNotIn('up to date', output.getvalue())
                    else:self.assertIn('older version', error.getvalue())

    @staticmethod
    def development():
        import importlib.util
        from .config import HOME
        spec = importlib.util.spec_from_file_location('oh_dev', HOME / 'integrations/oh_dev.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def assert_plugin_branding(self, plugin, development=False):
        from .config import HOME
        expected = (HOME / 'plugins/o-harness/assets' / ('dev.png' if development else 'prod.png')).read_bytes()
        interface = json.loads((plugin / '.codex-plugin/plugin.json').read_text())['interface']
        self.assertEqual(interface['displayName'], 'OH DEV' if development else 'OH')
        for field in ('composerIcon', 'logo'):
            self.assertEqual((plugin / interface[field]).read_bytes(), expected)
        for skill in (plugin / 'skills').iterdir():
            icons = {}
            for line in (skill / 'agents/openai.yaml').read_text().splitlines():
                key, _, value = line.strip().partition(': ')
                if key in ('icon_small', 'icon_large'):icons[key] = json.loads(value)
            self.assertEqual(set(icons), {'icon_small', 'icon_large'})
            for relative in icons.values():
                self.assertEqual((skill / relative).read_bytes(), expected)

    def test_development_switch_restores_both_hosts_after_refresh_and_failure(self):
        """CONTRIBUTING: switching keeps releases installed and preserves their enabled state."""
        dev = self.development()
        show_dashboard = dev.show_dashboard
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
                    patch.object(dev, 'show_dashboard') as dashboard, \
                    contextlib.redirect_stdout(io.StringIO()):
                dev.switch('on', dev.HOSTS)
                self.assertEqual(dashboard.call_args.args[2], 'on')
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
                self.assertEqual(dashboard.call_args.args[2], 'off')
                self.assertEqual(dashboard.call_args.args[0]['claude']['phase'], 'on')
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
                # A dashboard failure is reported after a successful switch, never a plugin rollback.
                protocol.clear();bad_response.clear()
                with patch.object(dev, 'sync_dashboard', side_effect=OSError('dashboard unavailable')), \
                        patch.object(dev.webbrowser, 'open', return_value=True), contextlib.redirect_stderr(io.StringIO()) as error:
                    dashboard.side_effect = show_dashboard
                    dev.switch('on', ('codex',))
                    self.assertEqual(dev.read(dev.home() / 'switch.json')['codex']['phase'], 'on')
                    self.assertTrue(plugins['codex'][dev.PLUGIN])
                    self.assertIn('Retry with oh-dev dashboard --host codex', error.getvalue())
                dashboard.side_effect = None
                dev.switch('off', dev.HOSTS)
                # A stalled browser launcher cannot hold the switch's final dashboard step open.
                import threading
                release=threading.Event();entered=threading.Event();finished=threading.Event()
                def stalled_browser(url):entered.set();release.wait(5);return True
                def show():
                    try:show_dashboard(dev.read(dev.home()/'switch.json'),('codex',),'on')
                    finally:finished.set()
                with patch.object(dev,'sync_dashboard'), patch.object(dev.webbrowser,'open',side_effect=stalled_browser):
                    worker=threading.Thread(target=show);worker.start()
                    try:
                        self.assertTrue(entered.wait(2))
                        self.assertTrue(finished.wait(3))
                    finally:release.set();worker.join(timeout=2)
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
            self.assert_plugin_branding(plugin, development=True)
            normal = Path(tmp) / '.local/share/o-harness'
            self.assertFalse(normal.exists())
            self.assertEqual(list(normal.parent.glob('.oh-snapshot-*.lock')), [])
            self.assertNotIn('OH_DATA_HOME', os.environ)
            # The packaged core remains intact; development changes its entry points and branding.
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
            from .cli import main as cli_main
            for arguments, port in ((['serve'],4319), (['serve','--port','8123'],8123)):
                with patch.dict(os.environ), patch('sys.argv',['oh',*arguments]), \
                        patch.object(dev.runpy,'run_path',side_effect=lambda *a,**k:cli_main()), patch('oh.server.serve') as serve:
                    dev.launch(HOME,base/'data','cli',launcher)
                    serve.assert_called_once_with(port)
            with patch.dict(os.environ,{'OH_DASHBOARD_MODE':'release'}), patch('oh.server.serve') as serve:
                cli_main(['serve']);serve.assert_called_once_with(4318)
            self.assertEqual(list(consumer.iterdir()), [])
            subprocess.run(['git', 'init', '-q', str(consumer)], check=True)
            registered = run('init', env=os.environ | {'OH_DATA_HOME': str(Path(tmp) / 'released-data')})
            self.assertEqual(registered.returncode, 0, registered.stderr)
            self.assertTrue(list((base / 'data/registry/checkouts').glob('*.json')))
            self.assertFalse((Path(tmp) / 'released-data').exists())
            self.assertEqual([p.name for p in consumer.iterdir()], ['.git'])
            # A native locator stays available without launching the development runtime.
            hooked = subprocess.run([sys.executable, '-I', str(plugin / 'scripts/human-event.py'), 'codex'],
                input=json.dumps({'prompt': '/oh-propose', 'cwd': str(consumer), 'session_id': 'dev-test',
                                  'hook_event_name': 'UserPromptSubmit', 'turn_id': 'fixture'}), capture_output=True, text=True)
            self.assertEqual(hooked.returncode, 0, hooked.stderr)
            self.assertIn('Native conversation locator', hooked.stdout)

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
                self.assert_plugin_branding(plugin, development=True)
                revision = json.loads((plugin / 'core/revision.json').read_text())
                self.assertEqual(revision['version'], metadata['version'])
                verify_package(plugin / 'core')
                command = [sys.executable, '-I', str(plugin / 'scripts/oh')]
                result = subprocess.run([*command, 'resource', 'workflows/propose/SKILL.md'], capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn('uncommitted fixture workflow', result.stdout)
                for script, args, payload in (('human-event.py', [host], {'prompt': 'hello'}),
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
            # Real packaged servers exercise lease replacement, reuse and both host selections.
            import socket
            with socket.socket() as available:
                available.bind(('127.0.0.1',0));port=available.getsockname()[1]
            health,background=dev.dashboard_health,dev.background_dashboard
            children=[]
            def start(*args,**kwargs):
                child=background(*args,**kwargs);children.append(child);return child
            def local_health(value):
                return {'ok':True,'collector_error':None,'mode':'release'} if value==dev.RELEASE_PORT else health(value)
            def retry_during_switch(before, after, arguments):
                # Hold the real switch lock while an overlapping dashboard command arrives.
                # An unlocked reader captures the old state; a locked reader sees the completed switch.
                import threading
                entered=threading.Event();proceed=threading.Event();errors=[]
                read,locked=dev.read,dev.lock
                switch_path=dev.home()/'switch.json';switch_lock=dev.home()/'switch.lock'
                def reading(path,default=None):
                    value=read(path,default)
                    if path==switch_path:
                        entered.set()
                        if not proceed.wait(3):raise RuntimeError('The fixture switch did not finish')
                    return value
                @contextlib.contextmanager
                def locking(path,**kwargs):
                    if path==switch_lock:entered.set()
                    with locked(path,**kwargs):yield
                def retry():
                    try:dev.main(arguments)
                    except BaseException as exc:errors.append(exc)
                worker=threading.Thread(target=retry)
                with patch.object(dev,'read',side_effect=reading),patch.object(dev,'lock',side_effect=locking):
                    try:
                        with locked(switch_lock):
                            dev.write(switch_path,before);worker.start()
                            self.assertTrue(entered.wait(2))
                            dev.write(switch_path,after)
                    finally:proceed.set();worker.join(timeout=3)
                    self.assertFalse(worker.is_alive())
                    self.assertEqual(errors,[])
            with patch.object(dev,'DEV_PORT',port), patch.object(dev,'dashboard_health',side_effect=local_health), \
                    patch.object(dev,'background_dashboard',side_effect=start), patch.object(dev.webbrowser,'open',return_value=True) as browser, \
                    contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                try:
                    dev.show_dashboard(state,('codex',),'on')
                    current=health(port)
                    self.assertIsNotNone(current)
                    self.assertEqual((current['mode'],current['version']),('development',metadata['version']))
                    self.assertTrue((dev.home()/'data/analytics.sqlite3').is_file())
                    dev.show_dashboard(state,('codex',),'on')
                    self.assertEqual(len(children),1)
                    self.assertEqual(health(port)['instance'],current['instance'])
                    browser.reset_mock()
                    retry_during_switch({h:r|{'phase':'off'} for h,r in state.items()},state,['dashboard','--host','codex'])
                    self.assertEqual(dev.read(dev.home()/'dashboard.json').get('instance'),current['instance'])
                    self.assertEqual(len(children),1)
                    browser.assert_called_once_with(f'http://localhost:{port}')
                    state['codex']['phase']='off';dev.write(dev.home()/'switch.json',state)
                    dev.show_dashboard(state,('codex',),'off')
                    self.assertEqual(health(port)['version'],other['version'])
                    self.assertEqual(len(children),2)
                    children[0].wait(timeout=2)
                    browser.assert_called_with('http://localhost:4318')
                    before={h:dict(r) for h,r in state.items()}
                    state['claude']['phase']='off'
                    browser.reset_mock()
                    retry_during_switch(before,state,['dashboard'])
                    self.assertEqual(dev.read(dev.home()/'dashboard.json'),{})
                    browser.assert_called_once_with('http://localhost:4318')
                    children[1].wait(timeout=2)
                    self.assertIsNone(health(port))
                    # A healthy listener with another identity is never stopped or replaced.
                    state['codex']['phase']='on';dev.write(dev.home()/'switch.json',state)
                    browser.reset_mock()
                    with patch.object(dev,'dashboard_health',return_value={'ok':True,'collector_error':None,'instance':'someone-else'}):
                        dev.show_dashboard(state,('codex',),'on')
                    self.assertEqual(len(children),2)
                    browser.assert_not_called()
                finally:
                    dev.write(dev.home()/'dashboard.json',{})
                    for child in children:
                        try:child.wait(timeout=3)
                        except subprocess.TimeoutExpired:child.kill();child.wait(timeout=2)
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
            for plugin in (first, second):self.assert_plugin_branding(plugin)
            self.assertEqual(a['revision'],b['revision'])
            # Both hosts must receive the current shared interaction contract,
            # including the pending-question lifecycle, through the same resource.
            from .config import HOME
            resources=[p.relative_to(HOME) for folder in ('workflows','prompts') for p in (HOME/folder).rglob('*.md')]
            for plugin in (first,second):
                for resource in resources:
                    self.assertEqual((plugin/'core'/resource).read_bytes(),(HOME/resource).read_bytes())
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

    def test_native_source_hook_never_installs_the_bundled_core_or_grants_work(self):
        with tempfile.TemporaryDirectory() as tmp:
            base=Path(tmp);env=os.environ|{'OH_DATA_HOME':str(base/'state')}
            scripts=self.package(base/'v1/o-harness','1'*40,'0.1.0')
            for prompt in ('continue','Please review this change.','/oh-propose a plan'):
                result=subprocess.run([sys.executable,str(scripts/'human-event.py'),'claude'],
                    input=json.dumps({'prompt':prompt,'cwd':tmp,'session_id':'native-session','turn_id':'turn'}),
                    env=env,capture_output=True,text=True,check=True)
                context=json.loads(result.stdout)['hookSpecificOutput']['additionalContext']
                self.assertIn('native-session',context);self.assertIn('not an approval',context)
                self.assertFalse((base/'state').exists())

    def test_ordinary_prompt_hook_has_no_setup_or_project_side_effects(self):
        from .config import HOME
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            result=subprocess.run([sys.executable,str(HOME/'plugins/o-harness/scripts/human-event.py'),'codex'],
                input=json.dumps({'prompt':'Fix the button styling','cwd':tmp}),cwd=root,capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertEqual(result.stdout,'')
            self.assertEqual(list(root.iterdir()),[])

    def test_native_source_hook_exposes_only_the_parent_locator_and_never_runs_helpers(self):
        import io,runpy
        from unittest.mock import patch
        from .config import HOME
        with tempfile.TemporaryDirectory() as tmp:
            for prompt in ('Search my notes','approve','publish','/oh-design auth'):
                stdin=io.TextIOWrapper(io.BytesIO(json.dumps({'prompt':prompt,'cwd':tmp,'session_id':'s','turn_id':'t'}).encode()))
                stdout=io.StringIO()
                with patch('sys.stdin',stdin),patch('sys.stdout',stdout),patch('sys.argv',['hook','claude']),patch('subprocess.run') as run:
                    runpy.run_path(str(HOME/'plugins/o-harness/scripts/human-event.py'),run_name='__main__')
                run.assert_not_called()
                context=json.loads(stdout.getvalue())['hookSpecificOutput']['additionalContext']
                self.assertIn('not an approval',context);self.assertIn(json.dumps(prompt),context)
            self.assertEqual(list(Path(tmp).iterdir()),[])
