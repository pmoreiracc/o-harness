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


def merge(base, patch):
    if not isinstance(patch, dict):
        raise Refused('Configuration must be an object')
    for key, value in patch.items():
        if key not in base:
            raise Refused(f'Unknown configuration key: {key}')
        if isinstance(base[key], dict):
            merge(base[key], value)
        else:
            base[key] = value
    return base


def validate(value):
    if type(value['schema_version']) is not int or value['schema_version'] != 1:
        raise Refused('Unsupported configuration version')
    for key in ('tasks_per_batch', 'review_rounds'):
        if type(value[key]) is not int or not 1 <= value[key] <= 100:
            raise Refused(f'{key} must be an integer from 1 to 100')
    if type(value['max_escalations']) is not int or not 0 <= value['max_escalations'] <= 2:
        raise Refused('At most two model escalations are supported')
    for key, number in value['context'].items():
        if type(number) is not int or not 1000 <= number <= 100000:
            raise Refused(f'Invalid context limit: {key}')
    for host, profiles in value['models'].items():
        for role in ROLES:
            profile = profiles[role]
            if not isinstance(profile['model'], str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._:/-]*',profile['model']):
                raise Refused(f'Invalid {host}/{role} model')
            if profile['effort'] not in EFFORTS[host]:
                raise Refused(f'Unsupported {host}/{role} effort')
    return value


def load(root):
    defaults = read_json(HOME / 'config/defaults.json')
    config = deepcopy(defaults)
    for filename in ('config.json', 'config.local.json'):
        path = Path(root) / '.oh' / filename
        if path.exists():
            merge(config, read_json(path))
    validate(config)
    return config


def version():
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
