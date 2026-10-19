"""Update released OH plugins through their hosts."""
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from . import hosts
from .storage import Refused, read_json, state_home

PLUGIN = 'o-harness@o-harness'
HOSTS = ('codex', 'claude')


def call(program, environment, *args):
    try:
        done = subprocess.run([program, 'plugin', *args], cwd=Path.home(), env=environment,
                              capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=120)
    except subprocess.TimeoutExpired:
        raise Refused('Plugin command timed out. Check your connection, then retry oh-update.') from None
    if done.returncode:
        raise Refused(f'plugin {" ".join(args)} failed: {done.stderr.strip() or done.stdout.strip()}. Retry oh-update after resolving this error.')
    return done.stdout


def installed(host, command):
    try:
        args = ('--marketplace', 'o-harness') if host == 'codex' else ()
        value = json.loads(command('list', *args, '--json'))
        entries = value['installed'] if host == 'codex' else value
        if not isinstance(entries, list):raise ValueError('expected plugin list')
        for entry in entries:
            if entry.get('pluginId' if host == 'codex' else 'id') != PLUGIN:continue
            if host == 'claude' and entry.get('scope') != 'user':continue
            if not isinstance(entry.get('version'), str) or not re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+', entry['version']):
                raise ValueError('expected release version X.Y.Z')
            return entry
    except (ValueError, KeyError, TypeError, AttributeError) as exc:
        raise Refused(f'Cannot read {host} OH release version ({exc}). Check or update the host CLI, then retry oh-update.') from None
    return None


def remembered(name, path, root):
    """Revalidate OH's known binary for a host whose CLI this session's PATH omits."""
    if not hosts.WINDOWS:return hosts.trust(name, path, root, pinned=False)['path']
    known = Path(path)
    if known.is_file() and not hosts.in_codex_app(path):
        return hosts.trust(name, path, root, pinned=False)['path']
    # The Windows Codex app replaces its CLI folder on update, so its copy is found again, not remembered.
    try:return hosts.executable(name, root)
    except Refused as refused:
        if known.is_file():return hosts.trust(name, path, root, pinned=False)['path']
        remedy = (str(refused) if isinstance(refused, hosts.Undecided) else
                  f'Open the Codex app once so it installs its command-line binary, or name its native binary with: '
                  f'oh trust-host {name} <absolute-path>.')
        raise Refused(f'The {name} executable OH remembered is gone: {path}. {remedy} '
                      f'You can also run oh-update from a {name} session.') from None


def update(root, host=None):
    failed = changed = found = False
    environment = hosts.subscription_env(root)
    for name in (host,) if host else HOSTS:
        try:
            record = state_home() / 'hosts' / (name + '.json')
            saved = read_json(record) if record.is_file() else None
            available = shutil.which(name, path=environment['PATH'])
            if not available and saved and not saved.get('pinned'):
                # Another host's session may omit this CLI from PATH. Revalidate OH's known binary.
                program = remembered(name, saved['path'], root)
            elif not host and not available and not saved and not hosts.installed(name):
                print(f'{name}: not found on PATH and no known OH host executable (skipped).', flush=True)
                continue
            else:program = hosts.executable(name, root)
            command = lambda *args: call(program, environment, *args)
            before = installed(name, command)
            found = True
            if before is None:
                source = ('pmoreiracc/o-harness', '--ref', 'dist') if name == 'codex' else ('pmoreiracc/o-harness#dist',)
                command('marketplace', 'add', *source)
            else:command('marketplace', 'upgrade' if name == 'codex' else 'update', 'o-harness')
            # Codex refreshes installed plugins with the marketplace. Re-adding the same version
            # replaces its cache unnecessarily and can fail while a Windows session uses it.
            after = installed(name, command) if name == 'codex' else None
            if name != 'codex' or after is None:
                action = 'add' if name == 'codex' else 'update' if before else 'install'
                command(action, PLUGIN, *(() if name == 'codex' else ('--scope', 'user')))
                after = installed(name, command)
            if after is None:raise Refused('OH is missing after the update. Reinstall o-harness@o-harness, then retry oh-update.')
            old, new = before['version'] if before else 'not installed', after['version']
            if before and tuple(map(int, new.split('.'))) < tuple(map(int, old.split('.'))):
                raise Refused(f'The host changed OH from {old} to older version {new}. Check the o-harness marketplace release source.')
            if old == new:print(f'{name}: {new} — up to date', flush=True)
            else:
                changed = True
                print(f'{name}: {old} -> {new}', flush=True)
        except subprocess.TimeoutExpired:
            failed = True
            print(f'{name}: host identity check timed out. Retry oh-update.', file=sys.stderr, flush=True)
        except (Refused, OSError) as exc:
            failed = True
            print(f'{name}: {exc}', file=sys.stderr, flush=True)
    if not found and not failed:
        print('No supported host found. Install Claude Code or Codex, then run oh-update again.', file=sys.stderr)
        failed = True
    if changed:print('Start a new host session to use the updated plugin.', flush=True)
    return int(failed)
