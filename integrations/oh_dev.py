"""Use this OH checkout in Claude Code and Codex without replacing the released plugin.

Only this contributor tool and its generated launchers know about development mode.
Host CLIs install a separate local marketplace; their enablement settings select it.
"""
import argparse
from contextlib import contextmanager
import json
import os
from pathlib import Path
import queue
import runpy
import shutil
import subprocess
import sys
import threading
import time

SOURCE = Path(__file__).resolve().parents[1]
PLUGIN = 'o-harness@oh-dev'
MARKETPLACE = 'oh-dev'
HOSTS = ('codex', 'claude')
sys.dont_write_bytecode = True
sys.path.insert(0, str(SOURCE / 'runtime'))
from oh.storage import atomic_json, lock
from oh import system
from oh.installation import build as package


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


def build(host, folder, source=SOURCE):
    """Use the real packager, replacing entry points only in the generated development copy."""
    plugin = folder / 'plugins/o-harness'
    with development_data():package(plugin, host)
    data = home() / 'data'
    # Keep the production shell/Windows interpreter helpers. Every Python entry below imports
    # live source; human-event's sibling launcher must be the generated development launcher.
    preamble = (plugin / 'scripts/oh').read_text(encoding='utf-8').split('import json', 1)[0]
    for name, kind in (('oh', 'cli'), ('mcp-server', 'mcp'), ('human-event.py', 'human-event'), ('gate-hook.py', 'gate-hook')):
        script = (preamble if name in ('oh', 'mcp-server') else '') + (
            'import sys\nfrom pathlib import Path\n'
            f'sys.path.insert(0, {str(source / "integrations")!r})\n'
            'from oh_dev import launch\n'
            f'launch(Path({str(source)!r}), Path({str(data)!r}), {kind!r}, Path(__file__))\n')
        (plugin / 'scripts' / name).write_text(script, encoding='utf-8', newline='\n')
    manifest = plugin / ('.codex-plugin/plugin.json' if host == 'codex' else '.claude-plugin/plugin.json')
    metadata = read(manifest)
    metadata['version'] = metadata['version'].split('+')[0] + '+codex.' + folder.name
    write(manifest, metadata)
    if host == 'codex':
        catalog = {'name': MARKETPLACE, 'interface': {'displayName': 'OH development'}, 'plugins': [{
            'name': 'o-harness', 'source': {'source': 'local', 'path': './plugins/o-harness'},
            'policy': {'installation': 'AVAILABLE', 'authentication': 'ON_INSTALL'}, 'category': 'Productivity'}]}
        write(folder / '.agents/plugins/marketplace.json', catalog)
    else:
        write(folder / '.claude-plugin/marketplace.json', {'name': MARKETPLACE, 'owner': {'name': 'OH contributors'},
              'plugins': [{'name': 'o-harness', 'source': './plugins/o-harness'}]})
    return plugin


def launch(source, data, kind, entry):
    """Development-only routing; execution and approval behavior remain owned by OH."""
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument('--root', type=Path)
    parser.add_argument('command', nargs='?')
    selected, _ = parser.parse_known_args(sys.argv[1:] if kind == 'cli' else [])
    # Both releases use the same service name. Parse the command after global options/--.
    if kind == 'cli' and selected.command in ('setup', 'service-install', 'service-uninstall'):
        raise SystemExit('Development uses the checkout directly. Refresh with oh-dev on; run the dashboard with oh-dev exec serve --port 4319.')
    validate_storage(data.parent, data)
    os.environ['OH_DEV_NORMAL_DATA_HOME'] = str(normal_data())
    os.environ['OH_DATA_HOME'] = str(data)
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


def switch(action, hosts):
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
                    folder = location / 'builds' / host / str(time.time_ns())
                    build(host, folder)
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
                    print(f'{host}: development on — {SOURCE}')
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


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    for action in ('on', 'off', 'status'):
        sub.add_parser(action).add_argument('--host', choices=HOSTS, help='default: both hosts')
    execute = sub.add_parser('exec', help='run a source OH command using development data')
    execute.add_argument('arguments', nargs=argparse.REMAINDER)
    args = parser.parse_args(['exec'] if argv[:1] == ['exec'] else argv)
    try:
        if args.action == 'exec':
            arguments = argv[1:]
            if arguments[:1] == ['--']:arguments = arguments[1:]
            sys.argv = [str(SOURCE / 'oh'), *arguments]
            launch(SOURCE, home() / 'data', 'cli', SOURCE / 'oh')
        elif args.action == 'status':
            state = read(home() / 'switch.json', {})
            for host in (args.host,) if args.host else HOSTS:
                record = state.get(host)
                actual = installed(host)
                if record:
                    if record['host_home'] != host_home(host):
                        raise RuntimeError(f'{host} settings folder changed. Use {record["host_home"]} to inspect this switch.')
                print(json.dumps({'host': host, 'source': record['source'] if record else None,
                                  'plugins': actual, 'marketplace': marketplace(host)}))
            print(f'Development data: {home() / "data"}')
        else:switch(args.action, (args.host,) if args.host else HOSTS)
    except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
        parser.exit(1, f'oh-dev: {exc}\n')


if __name__ == '__main__':
    main()
