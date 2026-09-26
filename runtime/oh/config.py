from __future__ import annotations

from copy import deepcopy
import json
import re
from pathlib import Path
from .storage import Refused, digest, git, read_json

HOME = Path(__file__).resolve().parents[2]
ROLES = ('simple', 'standard', 'complex', 'review', 'orchestrator')
EFFORTS = {'codex': {'low', 'medium', 'high', 'xhigh', 'max', 'ultra'},
           'claude': {'low', 'medium', 'high', 'xhigh', 'max'}}


SCHEMA_URL = 'https://raw.githubusercontent.com/pmoreiracc/o-harness/main/config/oh.schema.json'
MODEL = r'[A-Za-z0-9][A-Za-z0-9._:/-]*'
ROLE_MEANING = {'simple': 'small, bounded tasks', 'standard': 'ordinary tasks',
                'complex': 'cross-cutting or safety-sensitive tasks, and retries after a failure',
                'review': 'independent reviews', 'orchestrator': 'the session you talk to (a recommendation only)'}


def rules():
    """Every setting, once: validation, `oh config` and the published JSON Schema all derive from this."""
    def number(low, high):return {'type': 'integer', 'minimum': low, 'maximum': high}
    result = [('tasks_per_batch', number(1, 100), 'Tasks one approval covers; each "continue" approves this many more'),
              ('review_rounds', number(1, 100), 'Review rounds a task may use before OH asks you'),
              ('max_escalations', number(0, 2), 'Retries on the complex model after a failed attempt, before OH asks you'),
              ('context.handoff_chars', number(1000, 100000), 'Maximum task handoff text sent to a worker'),
              ('context.result_chars', number(1000, 100000), 'Maximum feedback text kept in model prompts'),
              ('context.compact_at_tokens', number(1000, 100000), 'Context size at which Codex workers compact (Codex only)')]
    for host in ('claude', 'codex'):
        for role in ROLES:
            result.append((f'models.{host}.{role}.model', {'type': 'string', 'pattern': '^' + MODEL + '$'},
                           f'{host.title()} model for {ROLE_MEANING[role]}'))
            result.append((f'models.{host}.{role}.effort', {'type': 'string', 'enum': sorted(EFFORTS[host])},
                           f'{host.title()} reasoning effort for {ROLE_MEANING[role]}'))
    return result


def lookup_key(value, key):
    for part in key.split('.'):
        value = value[part]
    return value


def merge(base, patch, origin=None, source=None, prefix=''):
    if not isinstance(patch, dict):
        raise Refused(f'{prefix.rstrip(".") or "Configuration"} must be an object')
    for key, value in patch.items():
        if key not in base:
            raise Refused(f'Unknown setting: {prefix}{key}. Run oh config to list the settings')
        if isinstance(base[key], dict):
            merge(base[key], value, origin, source, prefix + key + '.')
        else:
            base[key] = value
            if origin is not None:origin[prefix + key] = source
    return base


def allowed(spec):
    if 'enum' in spec:return 'one of: ' + ', '.join(spec['enum'])
    if spec['type'] == 'integer':return f'whole number from {spec["minimum"]} to {spec["maximum"]}'
    return 'a model name your subscription offers'


def validate(value):
    if type(value['schema_version']) is not int or value['schema_version'] != 1:
        raise Refused('Unsupported configuration version')
    for key, spec, _ in rules():check(key, spec, lookup_key(value, key))
    return value


def check(key, spec, item):
    if spec['type'] == 'integer':valid = type(item) is int and spec['minimum'] <= item <= spec['maximum']
    elif 'enum' in spec:valid = item in spec['enum']
    else:valid = isinstance(item, str) and bool(re.fullmatch(MODEL, item))
    if not valid:raise Refused(f'{key} must be {allowed(spec)}; got {json.dumps(item)}')


def schema():
    """JSON Schema for oh.json, so editors show each setting's meaning and allowed values."""
    defaults = read_json(HOME / 'config/defaults.json')
    root = {'$schema': 'https://json-schema.org/draft/2020-12/schema', '$id': SCHEMA_URL, 'title': 'OH settings (oh.json)',
            'description': 'Project settings for OH. Run `oh config` to list them, or change one with /oh-config.',
            'type': 'object', 'additionalProperties': False,
            'properties': {'$schema': {'type': 'string', 'description': 'Lets editors show these descriptions'},
                           'schema_version': {'const': 1, 'description': 'Settings format version; optional'}}}
    for key, spec, meaning in rules():
        node = root
        for part in key.split('.')[:-1]:
            node = node['properties'].setdefault(part, {'type': 'object', 'additionalProperties': False, 'properties': {}})
        node['properties'][key.split('.')[-1]] = spec | {'description': meaning, 'default': lookup_key(defaults, key)}
    return root


def settings_names(names):
    """Names a file system may resolve to oh.json: case and Unicode compatibility variants too."""
    import unicodedata
    return sorted(n for n in names if unicodedata.normalize('NFKC', n).casefold() == 'oh.json')


def committed_entry(root, treeish='HEAD'):
    """The exact `oh.json` entry of a Git tree as (mode, object id), or None."""
    import subprocess
    from .storage import git_bytes
    try:raw = git_bytes(root, 'ls-tree', '-z', treeish, quiet=True)
    except subprocess.CalledProcessError:return None  # no commit yet
    for entry in raw.split(b'\0'):
        if entry:
            meta, name = entry.split(b'\t', 1)
            if name == b'oh.json':
                mode, _, oid = meta.decode().split()
                return mode, oid
    return None


def committed_settings(root):
    """oh.json exactly as in the last commit. Runs read nothing else from the repository, so no
    uncommitted, ignored or differently named file can change a run's settings."""
    entry = committed_entry(root)
    if not entry:return None
    label = f'{Path(root) / "oh.json"} (last commit)'
    if entry[0] not in ('100644', '100755'):raise Refused(f'{label} must be a regular file')
    try:value = json.loads(git(root, 'cat-file', 'blob', entry[1]))
    except ValueError as exc:raise Refused(f'{label} is not valid JSON: {exc}') from None
    if not isinstance(value, dict):raise Refused(f'{label} must contain a JSON object')
    return {k: v for k, v in value.items() if k != '$schema'}


def settings_edited(root):
    """Whether committing the checkout now would change the committed oh.json. Asks Git about that
    one path, so line-ending rules, modes and ignore rules agree exactly with what a commit takes."""
    return bool(git(root, 'status', '--porcelain', '--untracked-files=all', '--', ':(literal)oh.json'))


def tree_changes_settings(root, tree):
    return committed_entry(root, tree) != committed_entry(root)


def restore_settings(root, keep):
    """Undo a change to oh.json, keeping a copy that backups never parse (a .txt file, or a .tar of a
    directory). Returns the copy's path, or None when nothing could be kept."""
    import shutil
    import tarfile
    path, kept = Path(root) / 'oh.json', None
    Path(keep).mkdir(parents=True, exist_ok=True)
    try:
        if path.is_file() and not path.is_symlink():
            kept = Path(keep) / 'changed-oh.json.txt';shutil.copyfile(path, kept)
        elif path.is_dir() and not path.is_symlink():
            kept = Path(keep) / 'changed-oh.json.tar'
            with tarfile.open(kept, 'w') as archive:archive.add(path, arcname='oh.json')
    except (OSError, tarfile.TarError):
        if kept:kept.unlink(missing_ok=True)
        kept = None  # the restore matters more than the copy
    if path.is_dir() and not path.is_symlink():shutil.rmtree(path)
    elif path.is_symlink() or path.exists():path.unlink()
    if committed_entry(root):git(root, 'checkout', 'HEAD', '--', 'oh.json')
    return str(kept) if kept else None


def settings_location(root):
    """Where a run's project settings come from: the committed oh.json or the private file; never both."""
    from .registry import profile_path
    private = profile_path(root, 'config.json')
    if committed_entry(root) and private.exists():
        raise Refused(f'Project settings exist in both {Path(root) / "oh.json"} (committed) and {private}; delete the one you don\'t want')
    if committed_entry(root):return Path(root) / 'oh.json', 'repo'
    if private.exists():return private, 'private'
    return None, None


def project_file(root):
    """The file `oh config` edits: the working tree's oh.json, or the private file."""
    import os
    from .registry import profile_path
    repo, private = Path(root) / 'oh.json', profile_path(root, 'config.json')
    names = settings_names(os.listdir(root))
    if names and names != ['oh.json']:raise Refused(f'Rename {", ".join(str(Path(root) / n) for n in names)} to oh.json')
    if repo.is_symlink():raise Refused(f'{repo} must be a regular file, not a symlink')
    in_repo = bool(names or committed_entry(root))
    if in_repo and private.exists():
        raise Refused(f'Project settings exist in both {repo} and {private}; delete the one you don\'t want')
    if in_repo:return repo, 'repo'
    if private.exists():return private, 'private'
    return None, None


def read_settings(path):
    if Path(path).is_symlink():raise Refused(f'{path} must be a regular file, not a symlink')
    try:value = json.loads(Path(path).read_text())
    except ValueError as exc:raise Refused(f'{path} is not valid JSON: {exc}') from None
    except OSError as exc:raise Refused(f'Cannot read {path}: {exc.strerror}') from None
    if not isinstance(value, dict):raise Refused(f'{path} must contain a JSON object')
    return {k: v for k, v in value.items() if k != '$schema'}


def load(root, *, origin=None, replace=None):
    """Effective settings. `replace` substitutes the project settings, to validate a change before writing it."""
    config = validate(deepcopy(read_json(HOME / 'config/defaults.json')))
    from .registry import profile_path
    from .storage import state_home
    project, location = settings_location(root)
    layers = [('global', state_home() / 'settings/defaults.json', None)]
    if replace:layers.append(('project', replace[0], replace[1]))
    elif location == 'repo':layers.append(('project', f'{project} (last commit)', committed_settings(root) or {}))
    elif location == 'private':layers.append(('project', project, None))
    layers.append(('personal', profile_path(root, 'config.local.json'), None))
    for source, path, patch in layers:
        if patch is None:
            if not Path(path).exists():continue
            patch = read_settings(path)
        try:validate(merge(config, patch, origin, source))
        except Refused as exc:raise Refused(f'{path}: {exc}') from None
    return config


def uncommitted(root):
    """Whether the working tree's oh.json differs from the committed one OH actually uses."""
    path, entry = Path(root) / 'oh.json', committed_entry(root)
    if not path.is_file():return entry is not None
    if entry is None:return True
    committed = git(root, 'cat-file', 'blob', entry[1])
    return path.read_bytes().replace(b'\r\n', b'\n').strip() != committed.encode().strip()


def describe(root):
    from .registry import profile_path
    defaults, origin = read_json(HOME / 'config/defaults.json'), {}
    effective = load(root, origin=origin)
    try:path, location = project_file(root);problem = None
    except Refused as exc:path, location, problem = None, None, str(exc)
    result = {'file': str(path) if path else None, 'location': location, 'schema': SCHEMA_URL,
              'settings': [{'key': key, 'value': lookup_key(effective, key), 'default': lookup_key(defaults, key),
                            'source': origin.get(key, 'default'), 'allowed': allowed(spec), 'meaning': meaning}
                           for key, spec, meaning in rules()],
              'effective': effective, 'profile_directory': str(profile_path(root).parent), 'version': version(),
              'precedence': ['packaged defaults', 'global settings', 'project settings (committed oh.json, or private)',
                             'personal project settings']}
    if problem:result['note'] = problem + '. Runs are unaffected: they use the committed oh.json only.'
    elif location == 'repo' and uncommitted(root):
        result['note'] = 'oh.json has uncommitted changes. OH uses the last committed version until you commit it.'
    return result


def change(root, key, raw=None, *, location=None):
    """The only writer of project settings: an unknown key or invalid value never reaches the file."""
    specs = {k: spec for k, spec, _ in rules()}
    from .registry import profile_path
    path, current = project_file(root)
    data = read_settings(path) if path and path.exists() else (committed_settings(root) or {} if current == 'repo' else {})
    parts = key.split('.')
    if key not in specs and not (raw is None and present(data, parts)):
        raise Refused(f'Unknown setting: {key}. Run oh config to list the settings')
    if raw is None and not present(data, parts):return {'setting': key, 'unchanged': True, 'note': 'Not set in the project settings'}
    if path is None:
        if location not in ('repo', 'private'):
            raise Refused('This project has no settings file yet. Choose --location repo (oh.json in the repository) '
                          'or --location private (OH\'s folder, nothing in the repository)')
        path, current = (Path(root) / 'oh.json', 'repo') if location == 'repo' else (profile_path(root, 'config.json'), 'private')
    elif location and location != current:
        raise Refused(f'Project settings already live in {path}; change them there')
    if current == 'repo':
        from .workflow import active_file, load_run
        if active_file(root).exists() and load_run(root)[1]['status'] not in ('stopped', 'pr', 'completed'):
            raise Refused('A run is active in this checkout; change oh.json after it ends, or stop it first')
    try:before, whole = lookup_key(load(root), key), True
    except (Refused, KeyError):before, whole = None, False  # a broken file is repaired one setting at a time
    node = data
    if raw is None:
        trail = []
        for part in parts[:-1]:trail.append((node, part));node = node[part]
        node.pop(parts[-1])
        for parent, part in reversed(trail):
            if not parent[part]:parent.pop(part)
    else:
        try:value = json.loads(raw)
        except ValueError:value = raw
        if value is None:raise Refused(f'Use oh config unset {key} to go back to the default')
        if specs[key]['type'] == 'string' and not isinstance(value, str):value = raw
        for part in parts[:-1]:
            if not isinstance(node.get(part), dict):node[part] = {}
            node = node[part]
        old = node.get(parts[-1])
        if type(old) is type(value) and old == value and path.exists():
            return {'setting': key, 'unchanged': True, 'file': str(path)}
        node[parts[-1]] = value
    origin, after = {}, None
    if whole:
        # A valid file stays valid: the whole result is checked before anything is written.
        effective = load(root, origin=origin, replace=(path, data))
        after = lookup_key(effective, key) if key in specs else None
    elif raw is not None:
        check(key, specs[key], value);after = value  # never adds an invalid value to a file being repaired
    write_settings(path, data, current)
    note = 'Applies to the next run you start; continuing a run keeps the settings it was approved with.'
    if current == 'repo':note = 'Commit oh.json to apply it: OH reads settings from the last commit. ' + note
    if origin.get(key) == 'personal':note += ' Your personal config.local.json overrides this value.'
    return {'setting': key, 'from': before, 'to': after, 'file': str(path), 'note': note}


def present(data, parts):
    for part in parts:
        if not isinstance(data, dict) or part not in data:return False
        data = data[part]
    return True


def write_settings(path, data, location):
    import os
    import tempfile
    from .system import replace
    body = ({'$schema': SCHEMA_URL} | data) if location == 'repo' else data
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.oh-settings-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', newline='\n') as stream:
            stream.write(json.dumps(body, indent=2) + '\n');stream.flush();os.fsync(stream.fileno())
        if location == 'repo':
            mask = os.umask(0);os.umask(mask);os.chmod(temporary, 0o666 & ~mask)  # a shared repository file
        replace(temporary, path)
    finally:
        if os.path.exists(temporary):os.unlink(temporary)


def version():
    if (HOME/'revision.json').is_file():
        return read_json(HOME/'revision.json')['revision']
    revision=git(HOME, 'rev-parse', 'HEAD')
    if git(HOME,'status','--porcelain'):
        from .verification import tree
        return revision+'+worktree.'+tree(HOME)[:16]
    return revision


def snapshot(root):
    config = load(root)
    return {'config': config, 'config_hash': digest(config), 'harness_version': version(), 'rubric_version': 1}


def classify(task):
    # Stable pre-execution signals; spend and outcome never change the assigned cohort.
    text = (task['title'] + ' ' + task.get('instructions', '')).lower()
    critical = ('authorization', 'migration', 'concurrency', 'security boundary', 'cryptograph', 'transaction')
    if any(word in text for word in critical) or len(task.get('paths', [])) > 6:
        return 'complex', 'Cross-cutting or safety-sensitive change (rubric 1)'
    if len(task.get('paths', [])) <= 2 and any(word in text for word in ('typo', 'copy edit', 'rename', 'documentation')):
        return 'simple', 'Small bounded editorial change (rubric 1)'
    return 'standard', 'Ordinary implementation or unspecified scope (rubric 1)'
