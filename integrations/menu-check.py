#!/usr/bin/env python3
"""Manual check of OH's clickable menus on each Claude and Codex surface. No model does any work: a sample
run finishes with stand-in workers and waits on its last menu (Open a PR / Stop), owned by the
conversation that asked for it.

  python3 integrations/menu-check.py install   build this checkout's plugins and install them in Claude Code and Codex
  python3 ~/oh-menu-check/menu-check.py menu <claude|codex> <session>   the agent runs this in the test conversation
  python3 ~/oh-menu-check/menu-check.py restore   put the published OH plugins back
"""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

WORK = Path.home() / 'oh-menu-check'
PROJECT = WORK / 'project'
DATA = Path(os.environ.get('OH_DATA_HOME', Path.home() / '.local/share/o-harness')).expanduser()


def sh(*command, **options):
    print('$', ' '.join(map(str, command)), flush=True)
    return subprocess.run([str(c) for c in command], check=True, **options)


def install():
    repo = Path(__file__).resolve().parents[1]
    dist = WORK / 'dist'
    shutil.rmtree(dist, ignore_errors=True);dist.mkdir(parents=True)
    for host in ('claude', 'codex'):
        sh(sys.executable, '-I', repo / 'oh', 'build-plugin', dist / host / 'o-harness', '--host', host, stdout=subprocess.DEVNULL)
    (dist / '.claude-plugin').mkdir();(dist / '.agents/plugins').mkdir(parents=True)
    (dist / '.claude-plugin/marketplace.json').write_text(json.dumps({'name': 'o-harness', 'owner': {'name': 'OH contributors'},
        'plugins': [{'name': 'o-harness', 'source': './claude/o-harness', 'description': 'OH'}]}))
    (dist / '.agents/plugins/marketplace.json').write_text(json.dumps({'name': 'o-harness', 'interface': {'displayName': 'OH'},
        'plugins': [{'name': 'o-harness', 'source': {'source': 'local', 'path': './codex/o-harness'},
                     'policy': {'installation': 'AVAILABLE', 'authentication': 'ON_INSTALL'}, 'category': 'Productivity'}]}))
    for host, add in (('claude', 'install'), ('codex', 'add')):
        subprocess.run([host, 'plugin', 'marketplace', 'remove', 'o-harness'], capture_output=True)
        sh(host, 'plugin', 'marketplace', 'add', dist);sh(host, 'plugin', add, 'o-harness@o-harness')
    sh(dist / 'claude/o-harness/scripts/oh', 'setup', '--development')
    shutil.copy2(__file__, WORK / 'menu-check.py')
    if not PROJECT.exists():
        PROJECT.mkdir()
        for args in (('init', '-q', '-b', 'main'), ('config', 'user.name', 'OH menu check'), ('config', 'user.email', 'menu-check@example.invalid')):
            sh('git', '-C', PROJECT, *args)
        (PROJECT / 'README.md').write_text('# OH menu check\n', newline='\n')
        sh('git', '-C', PROJECT, 'add', '.');sh('git', '-C', PROJECT, 'commit', '-qm', 'start')
        sh('git', '-C', PROJECT, 'switch', '-qc', 'work')
        oh = dist / 'claude/o-harness/scripts/oh'
        sh(oh, '--root', PROJECT, 'init', '--name', 'oh-menu-check')
        sh(oh, '--root', PROJECT, 'config', 'set', 'checks', json.dumps([{'name': 'files', 'command': ['git', 'status', '--short']}]))
    print('\nInstalled. Restart Claude and Codex, then follow the test steps.')


def menu(host, session):
    active = json.loads((DATA / 'runtime/active.json').read_text())
    sys.path.insert(0, str(DATA / 'versions' / active['revision'] / 'runtime'))
    from oh.hosts import LENSES
    from oh.runner import run
    from oh.storage import identifier
    from oh.workflow import human_event, start
    evidence = {'anchors': ['Menu check'], 'attacks': ['None: stand-in worker'], 'limits': ['Stand-in reviewer'],
                'lenses': {lens: 'Stand-in check' for lens in LENSES}}
    def worker(host, root, profile, prompt, role, directory, context, **options):
        if role != 'review':(Path(root) / 'menu-check.txt').write_text(identifier() + '\n', newline='\n')
        return {'failed': False, 'returncode': 0, 'duration_ms': 1, 'text': 'done', 'usage_observed': False,
                'structured': {'verdict': 'clean', 'summary': 'Stand-in review', 'findings': [], 'evidence': evidence}}
    prompt = 'menu check'
    start(PROJECT, {'tasks': [{'id': '1', 'title': 'Menu check', 'instructions': 'Stand-in task'}]},
          human_event({'hook_event_name': 'UserPromptSubmit', 'session_id': session, 'turn_id': 'menu-' + identifier(), 'prompt': prompt}, host))
    print(json.dumps(run(PROJECT, worker), indent=2))


def restore():
    for host, add, source in (('claude', 'install', 'pmoreiracc/o-harness@dist'), ('codex', 'add', 'pmoreiracc/o-harness@dist')):
        subprocess.run([host, 'plugin', 'marketplace', 'remove', 'o-harness'], capture_output=True)
        sh(host, 'plugin', 'marketplace', 'add', source);sh(host, 'plugin', add, 'o-harness@o-harness')
    launchers = sorted((Path.home() / '.claude/plugins/cache/o-harness/o-harness').glob('*/scripts/oh'))
    if launchers:sh(launchers[-1], 'setup')
    print('\nRestored the published OH. Restart Claude and Codex. Delete ~/oh-menu-check when you no longer need it.')


if __name__ == '__main__':
    action = sys.argv[1] if len(sys.argv) > 1 else ''
    if action == 'install':install()
    elif action == 'restore':restore()
    elif action == 'menu' and len(sys.argv) == 4 and sys.argv[2] in ('claude', 'codex') and sys.argv[3]:menu(sys.argv[2], sys.argv[3])
    else:raise SystemExit(__doc__)
