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
    for key, spec, _ in rules():
        item = lookup_key(value, key)
        if spec['type'] == 'integer':valid = type(item) is int and spec['minimum'] <= item <= spec['maximum']
        elif 'enum' in spec:valid = item in spec['enum']
        else:valid = isinstance(item, str) and bool(re.fullmatch(MODEL, item))
        if not valid:raise Refused(f'{key} must be {allowed(spec)}; got {json.dumps(item)}')
    return value


def schema():
    """JSON Schema for oh.json, so editors show each setting's meaning and allowed values."""
    defaults = read_json(HOME / 'config/defaults.json')
    root = {'$schema': 'https://json-schema.org/draft/2020-12/schema', '$id': SCHEMA_URL, 'title': 'OH settings (oh.json)',
            'description': 'Project settings for OH. Run `oh config` to list them, or change one with /oh-config.',
            'type': 'object', 'additionalProperties': False,
            'properties': {'$schema': {'type': 'string', 'description': 'Lets editors show these descriptions'}}}
    for key, spec, meaning in rules():
        node = root
        for part in key.split('.')[:-1]:
            node = node['properties'].setdefault(part, {'type': 'object', 'additionalProperties': False, 'properties': {}})
        node['properties'][key.split('.')[-1]] = spec | {'description': meaning, 'default': lookup_key(defaults, key)}
    return root


def project_file(root):
    """Project settings live in oh.json in the repository or, for private projects, in OH's folder; never both."""
    from .registry import profile_path
    repo, private = Path(root) / 'oh.json', profile_path(root, 'config.json')
    if repo.exists() and private.exists():
        raise Refused(f'Project settings exist in both {repo} and {private}; keep only one')
    if repo.exists():return repo, 'repo'
    if private.exists():return private, 'private'
    return None, None


def read_settings(path):
    try:value = json.loads(Path(path).read_text())
    except ValueError as exc:raise Refused(f'{path} is not valid JSON: {exc}') from None
    if not isinstance(value, dict):raise Refused(f'{path} must contain a JSON object')
    return {k: v for k, v in value.items() if k != '$schema'}


def load(root, *, origin=None, replace=None):
    """Effective settings. `replace` substitutes one file's content, to validate a change before writing it."""
    config = deepcopy(read_json(HOME / 'config/defaults.json'))
    from .registry import profile_path
    from .storage import state_home
    project, _ = project_file(root)
    if replace and project is None:project = replace[0]
    for source, path in (('global', state_home() / 'settings/defaults.json'), ('project', project),
                         ('personal', profile_path(root, 'config.local.json'))):
        if replace and path == replace[0]:patch = replace[1]
        elif path and path.exists():patch = read_settings(path)
        else:continue
        try:validate(merge(config, patch, origin, source))
        except Refused as exc:raise Refused(f'{path}: {exc}') from None
    return config


def describe(root):
    from .registry import profile_path
    defaults, origin = read_json(HOME / 'config/defaults.json'), {}
    effective = load(root, origin=origin)
    path, location = project_file(root)
    return {'file': str(path) if path else None, 'location': location, 'schema': SCHEMA_URL,
            'settings': [{'key': key, 'value': lookup_key(effective, key), 'default': lookup_key(defaults, key),
                          'source': origin.get(key, 'default'), 'allowed': allowed(spec), 'meaning': meaning}
                         for key, spec, meaning in rules()],
            'effective': effective, 'profile_directory': str(profile_path(root).parent), 'version': version(),
            'precedence': ['packaged defaults', 'global settings', 'project settings (oh.json or private)', 'personal project settings']}


def change(root, key, raw=None, *, location=None):
    """The only writer of project settings: an unknown key or invalid value never reaches the file."""
    specs = {k: spec for k, spec, _ in rules()}
    if key not in specs:raise Refused(f'Unknown setting: {key}. Run oh config to list the settings')
    from .registry import profile_path
    path, current = project_file(root)
    if path is None:
        if location not in ('repo', 'private'):
            if raw is None:return {'setting': key, 'unchanged': True}
            raise Refused('This project has no settings file yet. Choose --location repo (oh.json in the repository) '
                          'or --location private (OH\'s folder, nothing in the repository)')
        path, current = (Path(root) / 'oh.json', 'repo') if location == 'repo' else (profile_path(root, 'config.json'), 'private')
    elif location and location != current:
        raise Refused(f'Project settings already live in {path}; change them there')
    data = read_settings(path) if path.exists() else {}
    before = lookup_key(load(root), key)
    node, parts = data, key.split('.')
    if raw is None:
        trail = []
        for part in parts[:-1]:
            if not isinstance(node.get(part), dict):node = None;break
            trail.append((node, part));node = node[part]
        if node is not None:node.pop(parts[-1], None)
        for parent, part in reversed(trail):
            if not parent[part]:parent.pop(part)
    else:
        try:value = json.loads(raw)
        except ValueError:value = raw
        if specs[key]['type'] == 'string' and not isinstance(value, str):value = raw
        for part in parts[:-1]:
            if not isinstance(node.get(part), dict):node[part] = {}
            node = node[part]
        node[parts[-1]] = value
    after = lookup_key(load(root, replace=(path, data)), key)
    write_settings(path, data, current)
    return {'setting': key, 'from': before, 'to': after, 'file': str(path),
            'note': ('Commit oh.json; OH starts a batch only from a clean checkout. ' if current == 'repo' else '')
                    + 'Applies to the next batch you approve; a batch already approved keeps its settings'}


def write_settings(path, data, location):
    import os
    import tempfile
    from .system import replace
    body = ({'$schema': SCHEMA_URL} | data) if location == 'repo' else data
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.oh-settings-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as stream:
            stream.write(json.dumps(body, indent=2) + '\n');stream.flush();os.fsync(stream.fileno())
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
