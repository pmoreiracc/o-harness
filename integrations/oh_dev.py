"""Use an OH snapshot (or --live checkout) in both hosts without replacing the released plugin.

Only this contributor tool and its generated launchers know about development mode.
Host CLIs install a separate local marketplace; their enablement settings select it.
"""
import argparse
from contextlib import contextmanager
import json
import os
from pathlib import Path
import queue
import re
import runpy
import shutil
import subprocess
import sys
import threading
import time
import uuid
import webbrowser
from urllib.error import URLError
from urllib.request import ProxyHandler, build_opener

SOURCE = Path(__file__).resolve().parents[1]
PLUGIN = 'o-harness@oh-dev'
MARKETPLACE = 'oh-dev'
HOSTS = ('codex', 'claude')
DEV_PORT = 4319
RELEASE_PORT = 4318
sys.dont_write_bytecode = True
sys.path.insert(0, str(SOURCE / 'runtime'))
from oh.storage import atomic_json, lock
from oh import system
from oh.config import version
from oh.installation import build as package, inventory, verify_package


def home():
    location = (Path.home() / '.local/share/oh-dev').resolve()
    validate_storage(location, location / 'data')
    return location


def normal_data():
    # Preserve the caller's normal root when a development hook launches its sibling CLI.
    return Path(os.environ.get('OH_DEV_NORMAL_DATA_HOME') or os.environ.get('OH_DATA_HOME') or
                Path.home() / '.local/share/o-harness').expanduser().resolve()


def validate_storage(location, data):
    """Keep the fixed development folder outside repositories and normal OH data."""
    paths = (location.resolve(), data.resolve(), (location / 'builds').resolve())
    for path in paths:
        for parent in (path, *path.parents):
            if (parent / '.git').exists() or ((parent / 'HEAD').is_file() and
                    ((parent / 'objects').is_dir() or (parent / 'commondir').is_file())):
                raise RuntimeError('The development folder must be outside Git checkouts and Git metadata.')
    normal = {(Path.home() / '.local/share/o-harness').resolve(), normal_data()}
    if any(p.is_relative_to(n) or n.is_relative_to(p) for p in paths for n in normal):
        raise RuntimeError('Development data overlaps normal OH data. Remove that override before using oh-dev.')


def read(path, default=None):
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else default


@contextmanager
def development_data():
    # The shared packager/writer also locks OH state; keep that guard in development.
    data = home() / 'data'
    previous = {key: os.environ.get(key) for key in ('OH_DATA_HOME', 'OH_DEV_NORMAL_DATA_HOME')}
    os.environ['OH_DEV_NORMAL_DATA_HOME'] = str(normal_data())
    os.environ['OH_DATA_HOME'] = str(data)
    try:
        yield
    finally:
        for key, value in previous.items():
            if value is None:os.environ.pop(key, None)
            else:os.environ[key] = value


def write(path, value):
    with development_data():atomic_json(path, value)


def target_repository(path=None):
    target = (Path.cwd() if path is None else path).resolve()
    for parent in (target, *target.parents):
        if (parent / '.git').exists():
            return parent
    return None


def command_environment():
    target = target_repository()
    directories = [Path(p).resolve() for p in os.environ.get('PATH', '').split(os.pathsep) if p and Path(p).is_absolute()]
    path = os.pathsep.join(str(p) for p in directories if target is None or not p.is_relative_to(target))
    # shutil.which itself must suppress Windows' implicit cwd search before launching a host.
    os.environ['NoDefaultCurrentDirectoryInExePath'] = '1'
    return os.environ | {'PATH': path}


def host_program(host, environment):
    found = shutil.which(host, path=environment['PATH'])
    if not found:
        raise RuntimeError(f'{host} is not installed or on PATH outside the target repository. Install it, or select the other host with --host.')
    executable = Path(found).resolve()
    target = target_repository()
    if target is not None and executable.is_relative_to(target):
        raise RuntimeError(f'{host} resolves into the target repository. Use an installation outside it.')
    return str(executable)


def call(host, *args):
    environment = command_environment()
    executable = host_program(host, environment)
    done = subprocess.run([executable, *map(str, args)], cwd=home() if home().is_dir() else Path.home(), env=environment, capture_output=True,
                          text=True, encoding='utf-8', errors='replace', timeout=120)
    if done.returncode:
        raise RuntimeError(f'{host} {" ".join(map(str, args))}: {done.stderr.strip() or done.stdout.strip()}')
    return done.stdout


@contextmanager
def host_response(host):
    try:
        yield
    except (ValueError, KeyError, TypeError, AttributeError) as exc:
        raise RuntimeError(f'{host} returned invalid plugin protocol data. Check or update the host CLI, then retry.') from exc


def installed(host):
    with host_response(host):
        value = json.loads(call(host, 'plugin', 'list', '--json'))
        entries = value['installed'] if host == 'codex' else value
        if not isinstance(entries, list):raise ValueError('expected plugin list')
        result = {}
        for p in entries:
            plugin = p.get('pluginId', p.get('id'))
            if not isinstance(plugin, str) or not isinstance(p['enabled'], bool):raise ValueError('invalid plugin entry')
            if p.get('name', plugin.split('@')[0]) == 'o-harness' and (host == 'codex' or p.get('scope') == 'user'):
                result[plugin] = p['enabled']
        return result


def marketplace(host):
    with host_response(host):
        value = json.loads(call(host, 'plugin', 'marketplace', 'list', '--json'))
        entries = value['marketplaces'] if host == 'codex' else value
        if not isinstance(entries, list):raise ValueError('expected marketplace list')
        return next((str(Path(p['root'] if host == 'codex' else p['path']).resolve())
                     for p in entries if p['name'] == MARKETPLACE), None)


def codex_enable(plugin, enabled):
    """Use Codex's config writer: preserve other settings, comments and concurrent edits."""
    environment = command_environment()
    executable = host_program('codex', environment)
    with system.spawn([executable, 'app-server'], cwd=home(), env=environment, stdin=subprocess.PIPE,
                          stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, encoding='utf-8') as process:
        replies = queue.Queue()
        def receive():
            for line in process.stdout:
                replies.put(line)
            replies.put(None)
        threading.Thread(target=receive, daemon=True).start()
        try:
            for message in (
                {'id': 1, 'method': 'initialize', 'params': {'clientInfo': {'name': 'oh-dev', 'version': '1'}}},
                {'method': 'initialized'},
                {'id': 2, 'method': 'config/value/write', 'params': {
                    'keyPath': f'plugins.{json.dumps(plugin)}.enabled', 'value': enabled, 'mergeStrategy': 'replace'}},
            ):
                process.stdin.write(json.dumps(message) + '\n')
            process.stdin.flush()
            deadline = time.monotonic() + 30
            while True:
                line = replies.get(timeout=max(0, deadline - time.monotonic()))
                if line is None:raise RuntimeError('Codex app-server exited before updating plugin settings. Run codex doctor, then retry.')
                with host_response('codex'):
                    reply = json.loads(line)
                    if reply.get('id') != 2:continue
                    if 'error' in reply:raise RuntimeError(reply['error']['message'])
                    if reply['result'].get('overriddenMetadata'):
                        raise RuntimeError('A higher-priority Codex setting overrides OH enablement. Resolve it, then retry.')
                    return
        except queue.Empty:
            raise RuntimeError('Codex did not update plugin settings within 30 seconds. Run codex doctor, then retry.') from None
        finally:
            system.stop(process, force=True)


def enable(host, plugin, value):
    if host == 'codex':codex_enable(plugin, value)
    elif installed(host).get(plugin) != value:
        call(host, 'plugin', 'enable' if value else 'disable', plugin, '--scope', 'user')


def host_home(host):
    variable, fallback = ('CODEX_HOME', '.codex') if host == 'codex' else ('CLAUDE_CONFIG_DIR', '.claude')
    return str(Path(os.environ.get(variable, Path.home() / fallback)).expanduser().resolve())


def build(host, folder, source=SOURCE, snapshot_version=None):
    """Use the real packager, replacing entry points only in the generated development copy."""
    plugin = folder / 'plugins/o-harness'
    with development_data():package(plugin, host)
    data = home() / 'data'
    core = plugin / 'core'
    if snapshot_version:
        # Freeze the adapter and original hooks too: no entry point may import the live checkout.
        (core / 'integrations').mkdir()
        shutil.copy2(source / 'integrations/oh_dev.py', core / 'integrations/oh_dev.py')
        hooks = core / 'plugins/o-harness/scripts';hooks.mkdir(parents=True)
        for name in ('human-event.py', 'gate-hook.py'):
            shutil.copy2(plugin / 'scripts' / name, hooks / name)
        revision = read(core / 'revision.json')
        revision['source_revision'] = revision['revision']
        revision['revision'] += '.snapshot.' + snapshot_version.split('-SNAPSHOT.', 1)[1]
        revision['version'] = snapshot_version
        write(core / 'revision.json', revision)
        write(core / 'package.json', {'schema_version': 1, 'revision': revision['revision'], 'files': inventory(core)})
    # Keep the production shell/Windows interpreter helpers. Every Python entry below imports
    # selected source; human-event's sibling launcher must be the generated development launcher.
    preamble = (plugin / 'scripts/oh').read_text(encoding='utf-8').split('import json', 1)[0]
    for name, kind in (('oh', 'cli'), ('mcp-server', 'mcp'), ('human-event.py', 'human-event'), ('gate-hook.py', 'gate-hook')):
        selected = "Path(__file__).resolve().parents[1] / 'core'" if snapshot_version else f'Path({str(source)!r})'
        script = (preamble if name in ('oh', 'mcp-server') else '') + (
            'import sys\nfrom pathlib import Path\n'
            f'source = {selected}\n'
            'sys.path.insert(0, str(source / "integrations"))\n'
            'from oh_dev import launch\n'
            f'launch(source, Path({str(data)!r}), {kind!r}, Path(__file__))\n')
        (plugin / 'scripts' / name).write_text(script, encoding='utf-8', newline='\n')
    for kind in HOSTS:
        manifest = plugin / ('.' + kind + '-plugin/plugin.json')
        metadata = read(manifest)
        metadata['version'] = snapshot_version or metadata['version'].split('+')[0] + '-SNAPSHOT.live.' + folder.name
        if kind == 'codex':
            metadata['interface'].update(displayName='OH DEV', composerIcon='./assets/dev.png', logo='./assets/dev.png')
        write(manifest, metadata)
    for skill in (plugin / 'skills').iterdir():
        shutil.copyfile(plugin / 'assets/dev.png', skill / 'assets/icon.png')
    if host == 'codex':
        catalog = {'name': MARKETPLACE, 'interface': {'displayName': 'OH development'}, 'plugins': [{
            'name': 'o-harness', 'source': {'source': 'local', 'path': './plugins/o-harness'},
            'policy': {'installation': 'AVAILABLE', 'authentication': 'ON_INSTALL'}, 'category': 'Productivity'}]}
        write(folder / '.agents/plugins/marketplace.json', catalog)
    else:
        write(folder / '.claude-plugin/marketplace.json', {'name': MARKETPLACE, 'owner': {'name': 'OH contributors'},
              'plugins': [{'name': 'o-harness', 'source': './plugins/o-harness'}]})
    return plugin


def create_snapshot():
    """Package both hosts once; publish the selection record only after both packages are complete."""
    for retry in range(2):
        manifests = [read(SOURCE / f'plugins/o-harness/.{host}-plugin/plugin.json')['version'] for host in HOSTS]
        if len(set(manifests)) != 1 or not re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+', manifests[0]):
            raise RuntimeError('Source plugin versions must match as X.Y.Z before building a snapshot.')
        revision = version()
        label = manifests[0] + '-SNAPSHOT.' + str(time.time_ns())
        folder = home() / 'builds' / label
        folder.mkdir(parents=True)
        try:
            for host in HOSTS:build(host, folder / host, source=SOURCE, snapshot_version=label)
            if version() != revision or any(read(folder / host / 'plugins/o-harness/core/revision.json')['source_revision'] != revision for host in HOSTS):
                if retry == 0:continue  # an editor saved during copying: rebuild from its completed changes
                raise RuntimeError('The checkout kept changing during packaging. Finish saving, then retry oh-dev build.')
            metadata = {'version': label, 'source': str(SOURCE), 'source_revision': revision}
            write(folder / 'snapshot.json', metadata)
            return folder, metadata
        finally:
            if not (folder / 'snapshot.json').exists():shutil.rmtree(folder)  # windows-ok: packaged files only, no Git metadata


def read_snapshot(path):
    folder = Path(path).expanduser().resolve()
    validate_storage(folder, home() / 'data')
    metadata = read(folder / 'snapshot.json')
    if (not isinstance(metadata, dict) or any(not isinstance(metadata.get(key), str) for key in ('version', 'source', 'source_revision'))
            or not re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+-SNAPSHOT\.[0-9]+', metadata['version'])):
        raise RuntimeError('Select the build folder printed by oh-dev build; its snapshot.json is missing or invalid.')
    for host in HOSTS:
        plugin = folder / host / 'plugins/o-harness'
        verify_package(plugin / 'core')
        revision = read(plugin / 'core/revision.json')
        if revision.get('version') != metadata['version'] or revision.get('source_revision') != metadata.get('source_revision'):
            raise RuntimeError('Snapshot metadata does not match its packaged engine. Rebuild with oh-dev build.')
        for kind in HOSTS:
            if read(plugin / f'.{kind}-plugin/plugin.json').get('version') != metadata['version']:
                raise RuntimeError('Snapshot plugin versions do not match its engine. Rebuild with oh-dev build.')
    return folder, metadata


def selected_entry(host=None):
    """Select the active development runtime; different host builds require an explicit host."""
    state = read(home() / 'switch.json', {})
    for name, record in state.items():
        if (host is None or name == host) and record['phase'] not in ('on', 'off'):
            raise RuntimeError(f'An interrupted switch needs recovery. Run oh-dev off --host {name}, then retry.')
    selected = [(h, r) for h, r in state.items() if (host is None or h == host) and r['phase'] == 'on']
    if not selected:return None  # initial profile setup, before either host is enabled
    if len({(r.get('mode', 'live'), r.get('build'), r['source']) for _, r in selected}) > 1:
        raise RuntimeError('The hosts use different builds. Select oh-dev exec --host codex or --host claude.')
    chosen, record = selected[0]
    if record['host_home'] != host_home(chosen):
        raise RuntimeError(f'{chosen} settings folder changed. Use {record["host_home"]} or turn development off there first.')
    entry = Path(record['marketplace']) / 'plugins/o-harness/scripts/oh'
    if not entry.is_file():raise RuntimeError(f'The selected build is missing. Run oh-dev on --host {chosen} to rebuild it.')
    return entry


def launch(source, data, kind, entry):
    """Development-only routing; execution and approval behavior remain owned by OH."""
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument('--root', type=Path)
    parser.add_argument('command', nargs='?')
    selected, _ = parser.parse_known_args(sys.argv[1:] if kind == 'cli' else [])
    # Both releases use the same service name. Parse the command after global options/--.
    if kind == 'cli' and selected.command in ('setup', 'service-install', 'service-uninstall'):
        raise SystemExit('Development is isolated. Select a build with oh-dev on; run the dashboard with oh-dev exec serve --port 4319.')
    validate_storage(data.parent, data)
    os.environ['OH_DEV_NORMAL_DATA_HOME'] = str(normal_data())
    os.environ['OH_DATA_HOME'] = str(data)
    os.environ['OH_DASHBOARD_MODE'] = 'development'
    manifest = read(entry.parents[1] / '.codex-plugin/plugin.json', {})
    if manifest.get('version'):os.environ['OH_DASHBOARD_VERSION'] = manifest['version']
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(source / 'runtime'))
    if kind == 'mcp':
        from oh.mcp_server import serve
        sys.stdin.reconfigure(encoding='utf-8')
        sys.stdout.reconfigure(encoding='utf-8', newline='\n')
        serve(sys.stdin, sys.stdout, entry.with_name('oh'))
    elif kind == 'cli':
        runpy.run_path(str(source / 'oh'), run_name='__main__')
    else:
        script = source / 'plugins/o-harness/scripts' / (kind + '.py')
        exec(compile(script.read_bytes(), str(script), 'exec'), {'__name__': '__main__', '__file__': str(entry)})


def restore(host, record):
    present = installed(host)
    if PLUGIN in present:enable(host, PLUGIN, False)
    for plugin, was_enabled in record['previous'].items():
        if plugin not in present:
            raise RuntimeError(f'{plugin} is no longer installed in {host}. Reinstall it, then run oh-dev off --host {host}.')
        enable(host, plugin, was_enabled)
    current = installed(host)
    if current.get(PLUGIN, False) or any(current.get(plugin) != value for plugin, value in record['previous'].items()):
        raise RuntimeError('OH plugin settings changed during restoration. Finish the other host operation, then retry off.')


def dashboard_health(port):
    """A bounded localhost read, independent of proxy settings."""
    try:
        with build_opener(ProxyHandler({})).open(f'http://127.0.0.1:{port}/api/health', timeout=.3) as response:
            value = json.loads(response.read(65536))
        return value if isinstance(value, dict) and value.get('ok') is True and 'collector_error' in value else None
    except (OSError, URLError, ValueError):return None


def background_dashboard(entry, data, port, *, instance=None):
    environment = {k:v for k,v in os.environ.items() if not k.startswith('OH_DASHBOARD_')
                   and k not in ('OH_CHILD_ATTEMPT', 'OH_SERVICE_FOLLOWS_ACTIVE', 'OH_STATE_ROOT')}
    environment.update(OH_DEV_NORMAL_DATA_HOME=str(normal_data()), OH_DATA_HOME=str(data))
    if instance:
        environment.update(OH_DASHBOARD_INSTANCE=instance, OH_DASHBOARD_LEASE=str(home() / 'dashboard.json'))
    options = ({'creationflags': subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP}
               if os.name == 'nt' else {'start_new_session': True})
    logs = home() / 'logs';logs.mkdir(parents=True, exist_ok=True)
    with (logs / f'dashboard-{port}.log').open('ab') as output:
        return subprocess.Popen([sys.executable, '-I', str(entry), 'serve', '--port', str(port)],
            cwd=home(), env=environment, stdin=subprocess.DEVNULL, stdout=output,
            stderr=subprocess.STDOUT, close_fds=True, **options)


def wait_dashboard(port, instance, child):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        value = dashboard_health(port)
        if value and (instance is None or value.get('instance') == instance):return
        if child.poll() is not None:break
        time.sleep(.1)
    # This process was just created by us, not found by an unverified PID/port.
    child.terminate()
    try:child.wait(timeout=1)
    except subprocess.TimeoutExpired:child.kill();child.wait(timeout=1)
    raise RuntimeError(f'Dashboard did not start on port {port}; see {home() / "logs" / f"dashboard-{port}.log"}.')


def sync_dashboard(state, preferred):
    """Refresh only the dashboard whose lease OH owns; never touch a release service."""
    with lock(home() / 'dashboard.lock'):
        active = [h for h in (*preferred, *HOSTS) if state.get(h, {}).get('phase') == 'on']
        lease_path = home() / 'dashboard.json'
        previous = read(lease_path, {})
        current = dashboard_health(DEV_PORT)
        if active:
            entry = selected_entry(active[0])
            if current and previous.get('instance') and previous.get('entry') == str(entry) and current.get('instance') == previous['instance']:
                return
            instance = str(uuid.uuid4())
            write(lease_path, {'entry': str(entry), 'instance': instance})
        else:
            instance = None;write(lease_path, {})
        # A managed server observes its replaced lease and shuts itself down.
        if current and previous.get('instance') and current.get('instance') == previous['instance']:
            deadline = time.monotonic() + 3
            while dashboard_health(DEV_PORT) and time.monotonic() < deadline:time.sleep(.1)
            current = dashboard_health(DEV_PORT)
        if active:
            if current:raise RuntimeError(f'Port {DEV_PORT} is still occupied; finish or stop that dashboard before retrying.')
            child = background_dashboard(entry, home() / 'data', DEV_PORT, instance=instance)
            try:wait_dashboard(DEV_PORT, instance, child)
            except BaseException:
                write(lease_path, {});raise


def show_dashboard(state, preferred=(), action='on'):
    """Dashboard/browser failures never undo a completed plugin switch."""
    port = RELEASE_PORT if action == 'off' else DEV_PORT
    available = True
    try:sync_dashboard(state, preferred)
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
        selector = f' --host {preferred[0]}' if len(preferred) == 1 else ''
        print(f'Dashboard: {exc} Retry with oh-dev dashboard{selector}.', file=sys.stderr)
        if action == 'on':available = False
    if action == 'off':
        try:
            current = dashboard_health(RELEASE_PORT)
            if current and current.get('mode') == 'development':
                raise RuntimeError(f'Port {RELEASE_PORT} is serving development data; stop that listener and run oh-dev dashboard again.')
            if not current:
                entry = normal_data() / 'bin/oh'
                if not entry.is_file():raise RuntimeError('Released dashboard is not installed; start it with oh serve.')
                wait_dashboard(RELEASE_PORT, None, background_dashboard(entry, normal_data(), RELEASE_PORT))
        except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
            print(f'Dashboard: {exc}', file=sys.stderr)
            available = False
    url = f'http://localhost:{port}'
    print(f'{"Release" if action == "off" else "Development"} dashboard: {url}{" (unavailable)" if not available else ""}')
    if not available:return
    opened = queue.Queue()
    def open_page():
        try:opened.put(webbrowser.open(url))
        except (OSError, webbrowser.Error):opened.put(False)
    threading.Thread(target=open_page, daemon=True).start()
    try:success = opened.get(timeout=1)
    except queue.Empty:success = False
    if not success:print(f'Open {url} in your browser.')


def switch(action, hosts, *, build_path=None, live=False):
    location = home()
    location.mkdir(parents=True, exist_ok=True)
    with lock(location / 'switch.lock'):
        path = location / 'switch.json'
        state = read(path, {})
        # Preflight both hosts before changing either; a missing CLI must never look like success.
        inventories = {host: installed(host) for host in hosts}
        for host in hosts:
            if PLUGIN in inventories[host] and host not in state:
                raise RuntimeError(f'{host} has {PLUGIN} without a switch record. Restore the original OH plugin and remove that development registration before retrying.')
            if host in state and state[host]['host_home'] != host_home(host):
                raise RuntimeError(f'{host} settings folder changed. Use {state[host]["host_home"]} to turn development off first.')
            if action == 'on' and host in state and state[host]['phase'] != 'off' and state[host]['source'] != str(SOURCE):
                raise RuntimeError(f'{host} already uses {state[host]["source"]}. Run oh-dev off --host {host} first.')
            registered = marketplace(host)
            record = state.get(host, {})
            if registered and registered not in (record.get('marketplace'), record.get('pending_marketplace')):
                raise RuntimeError(f'{host} has a different oh-dev marketplace at {registered}. Remove the conflicting oh-dev marketplace before switching.')
        selected = None
        if action == 'on' and not live:
            selected = read_snapshot(build_path) if build_path else create_snapshot()
        failures = []
        for host in hosts:
            if action == 'off' and host not in state:
                print(f'{host}: development is already off')
                continue
            record = state.get(host)
            if not record or action == 'on' and record['phase'] == 'off':
                record = {'source': str(SOURCE), 'host_home': host_home(host),
                          'marketplace': (record or {}).get('marketplace'),
                          'pending_marketplace': (record or {}).get('pending_marketplace'),
                          'previous': {k: v for k, v in inventories[host].items() if k != PLUGIN}}
            if action == 'on':
                for plugin, enabled in inventories[host].items():
                    if plugin != PLUGIN:record['previous'].setdefault(plugin, enabled)
            try:
                if action == 'on':
                    if selected:
                        folder = selected[0] / host
                        record.update(mode='snapshot', build=str(selected[0]), version=selected[1]['version'],
                                      source_revision=selected[1]['source_revision'], build_source=selected[1]['source'])
                    else:
                        folder = location / 'builds' / host / str(time.time_ns())
                        build(host, folder)
                        base_version = read(SOURCE / f'plugins/o-harness/.{host}-plugin/plugin.json')['version']
                        record.update(mode='live', build=None, version=base_version + '-SNAPSHOT.live.' + folder.name,
                                      source_revision=version(), build_source=str(SOURCE))
                    record['phase'] = 'switching'
                    state[host] = record
                    write(path, state)  # Recovery exists before the first host mutation.
                    if PLUGIN in inventories[host]:enable(host, PLUGIN, False)
                    # Each generated marketplace has the same identity and a fresh plugin version.
                    # Hosts require removing the old source before registering the new local folder.
                    registered = marketplace(host)
                    if registered and registered not in (record.get('marketplace'), record.get('pending_marketplace')):
                        raise RuntimeError(f'{host} has a different oh-dev marketplace at {registered}. Remove the conflicting oh-dev marketplace before switching.')
                    if registered:
                        call(host, 'plugin', 'marketplace', 'remove', MARKETPLACE)
                    record['marketplace'] = None
                    record['pending_marketplace'] = str(folder)
                    write(path, state)
                    call(host, 'plugin', 'marketplace', 'add', folder)
                    record['marketplace'] = str(folder)
                    record.pop('pending_marketplace', None)
                    write(path, state)
                    call(host, 'plugin', 'add' if host == 'codex' else 'install', PLUGIN)
                    current = installed(host)
                    for plugin, enabled in current.items():
                        if plugin != PLUGIN:record['previous'].setdefault(plugin, enabled)
                    write(path, state)
                    for plugin in record['previous']:enable(host, plugin, False)
                    enable(host, PLUGIN, True)
                    current = installed(host)
                    if not current.get(PLUGIN) or any(value for plugin, value in current.items() if plugin != PLUGIN) or marketplace(host) != record['marketplace']:
                        raise RuntimeError('OH plugin settings changed during the switch. Finish the other host operation, then retry.')
                    record['phase'] = 'on'
                    write(path, state)
                    print(f'{host}: {record["mode"]} on — {record.get("version") or SOURCE}')
                    if selected:print(f'Build: {selected[0]}')
                else:
                    restore(host, record)
                    record['phase'] = 'off'
                    write(path, state)
                    print(f'{host}: restored previous plugin enablement')
            except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
                if host in state:
                    record['phase'] = 'needs recovery'
                    if action == 'on':
                        try:
                            restore(host, record)
                            record['phase'] = 'off'
                        except (OSError, RuntimeError, subprocess.SubprocessError) as recovery:
                            exc = RuntimeError(f'{exc}\nRestoration also failed: {recovery}')
                    write(path, state)
                failures.append(f'{host}: {exc}\nRecover with oh-dev off --host {host}, then retry.')
        print('Start fresh sessions in the selected hosts. Existing sessions keep their loaded plugins.')
        if failures:raise RuntimeError('\n'.join(failures))
        show_dashboard(state, hosts, action)


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    for action in ('on', 'off', 'status', 'dashboard'):
        sub.add_parser(action).add_argument('--host', choices=HOSTS, help='default: both hosts')
    mode = sub.choices['on'].add_mutually_exclusive_group()
    mode.add_argument('--build', metavar='PATH', help='activate a snapshot previously made by oh-dev build')
    mode.add_argument('--live', action='store_true', help='read the changing checkout instead of a fixed snapshot')
    sub.add_parser('build', help='package both hosts without changing installed plugins')
    execute = sub.add_parser('exec', help='run an OH command with the selected development runtime')
    execute.add_argument('--host', choices=HOSTS, help='required when hosts use different builds')
    execute.add_argument('arguments', nargs=argparse.REMAINDER)
    # Everything after exec belongs to OH, except an optional leading development-host selector.
    prefix = 3 if argv[:2] == ['exec', '--host'] else 2 if len(argv) > 1 and argv[0] == 'exec' and argv[1].startswith('--host=') else 1
    args = parser.parse_args(argv[:prefix] if argv[:1] == ['exec'] else argv)
    try:
        if args.action == 'exec':
            arguments = argv[prefix:]
            if arguments[:1] == ['--']:arguments = arguments[1:]
            if entry := selected_entry(args.host):
                raise SystemExit(subprocess.run([sys.executable, '-I', str(entry), *arguments]).returncode)
            sys.argv = [str(SOURCE / 'oh'), *arguments]
            launch(SOURCE, home() / 'data', 'cli', SOURCE / 'oh')
        elif args.action == 'build':
            folder, metadata = create_snapshot()
            print(f'Built {metadata["version"]}\n{folder}\nActivate: oh-dev on --build "{folder}"')
        elif args.action == 'dashboard':
            state = read(home() / 'switch.json', {})
            active = state.get(args.host, {}).get('phase') == 'on' if args.host else any(r['phase'] == 'on' for r in state.values())
            show_dashboard(state, (args.host,) if args.host else (), 'on' if active else 'off')
        elif args.action == 'status':
            state = read(home() / 'switch.json', {})
            for host in (args.host,) if args.host else HOSTS:
                record = state.get(host)
                actual = installed(host)
                if record:
                    if record['host_home'] != host_home(host):
                        raise RuntimeError(f'{host} settings folder changed. Use {record["host_home"]} to inspect this switch.')
                print(json.dumps({'host': host, 'source': record.get('build_source', record['source']) if record else None,
                                  'mode': record.get('mode', 'live') if record else None,
                                  'phase': record['phase'] if record else 'off',
                                  'version': record.get('version') if record else None,
                                  'source_revision': record.get('source_revision') if record else None,
                                  'build': record.get('build') if record else None,
                                  'plugins': actual, 'marketplace': marketplace(host)}))
            print(f'Development data: {home() / "data"}')
        else:switch(args.action, (args.host,) if args.host else HOSTS,
                    build_path=getattr(args, 'build', None), live=getattr(args, 'live', False))
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
        parser.exit(1, f'oh-dev: {exc}\n')


if __name__ == '__main__':
    main()
