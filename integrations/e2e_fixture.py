"""Prepare tiny real-CLI acceptance projects. Never launch agents or supply approvals.

Run explicitly: python3 integrations/e2e_fixture.py prepare
Then follow docs/cli-acceptance.md. The snapshot and reusable Codex test login
live outside the printed trial directory. This is fixture setup, not a second agent runner.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

SOURCE = Path(__file__).resolve().parents[1]


def git(root, *args):
    from oh.storage import git_env
    return subprocess.check_output(['git', '-C', str(root), *args], env=git_env(),
                                   stdin=subprocess.DEVNULL, text=True, stderr=subprocess.PIPE).strip()


def save(path, value):
    path.write_text(json.dumps(value, indent=2) + '\n', encoding='utf-8', newline='\n')


def acceptance_home():
    return Path.home() / '.local/share/oh-dev/acceptance/codex-home'


def codex_login():
    home = acceptance_home()
    home.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.execvpe('codex', ['codex', 'login'], codex_environment(home))


def codex_environment(home):
    # A separately signed-in subscription profile, including when invoked from Codex.
    env = {k: v for k, v in os.environ.items() if not k.startswith(('CODEX_', 'OH_'))
           and k not in ('OPENAI_API_KEY', 'OPENAI_BASE_URL')}
    return env | {'CODEX_HOME': str(home)}


def codex_home(base, value):
    # Keep saved conversations from the original disposable-home fixtures resumable.
    return acceptance_home() if value.get('codex_profile') == 'acceptance' else base / 'codex-home'


def check_codex_candidate(value, env):
    result = subprocess.check_output(
        ['codex', 'plugin', 'list', '--marketplace', 'oh-dev', '--json'], env=env, text=True)
    source = Path(value['build']) / 'codex/plugins/o-harness'
    for plugin in json.loads(result)['installed']:
        if (plugin.get('pluginId') == 'o-harness@oh-dev' and plugin.get('enabled')
                and plugin.get('version') == value['candidate']['version']
                and Path(plugin.get('source', {}).get('path', '')) == source):
            return
    raise ValueError('Codex has not selected this snapshot. Run the fixture setup-codex command for this trial.')


def setup_codex(path):
    base, value = trial(path)
    home = codex_home(base, value)
    env = codex_environment(home)
    login = subprocess.run(['codex', 'login', 'status'], env=env, capture_output=True, text=True)
    if login.returncode or 'Logged in using ChatGPT' not in login.stdout + login.stderr:
        raise SystemExit('The acceptance profile needs a subscription login. Run python3 integrations/e2e_fixture.py login-codex.')
    if home != base / 'codex-home':
        # Only replace the fixture-owned base config; authentication is managed by Codex.
        config = (base / 'codex-home/config.toml').read_text(encoding='utf-8')
        (home / 'config.toml').write_text(config, encoding='utf-8', newline='\n')
    subprocess.run(['codex', 'plugin', 'add', 'o-harness@oh-dev'], env=env, check=True)
    check_codex_candidate(value, env)
    print('Selected', value['candidate']['version'], 'in', home)


def prepare(codex_model, claude_model, suite="catalog"):
    sanity = suite == "sanity"
    effort = "low" if sanity else "medium"
    base = Path(tempfile.mkdtemp(prefix='oh-cli-acceptance-')).resolve()
    print('Preparing isolated fixtures in ' + str(base), file=sys.stderr, flush=True)
    os.environ['OH_DATA_HOME'] = str(base / 'data')
    os.environ['OH_DEV_NORMAL_DATA_HOME'] = str(base / 'data')
    import oh_dev
    build, candidate = oh_dev.create_snapshot()
    save(base / 'trial.json', {'kind': 'oh-cli-acceptance', 'root': str(base), 'build': str(build),
                             'candidate': candidate, 'suite': suite, 'effort': effort, 'codex_profile': 'acceptance', 'models': {'codex': codex_model, 'claude': claude_model}})
    from oh.registry import register
    from oh.config import edit
    from oh import plans
    profiles = {host: {role: {'model': model, 'effort': effort}
                      for role in ('simple', 'standard', 'complex', 'review', 'insights')}
                for host, model in (('codex', codex_model), ('claude', claude_model))}
    # Isolate the two sanity planning paths so their real sessions can overlap.
    scenarios = ('delivery', 'planning', 'choice', 'design') if sanity else ('delivery', 'planning', 'choice')
    for host in ('codex', 'claude'):
        for scenario in scenarios:
            root = base / f'{host}-{scenario}';root.mkdir()
            git(root, 'init', '-q', '-b', 'main')
            git(root, 'config', 'user.name', 'OH Acceptance')
            git(root, 'config', 'user.email', 'test@example.invalid')
            (root / 'AGENTS.md').write_text(
                'Disposable OH acceptance project. Use the installed OH skill and native agents. '
                'Preserve real approval boundaries; never edit OH state or fabricate host records. '
                'Keep implementation tiny and scoped. No unrelated refactoring, dependencies or services. '
                'Do not change the fixture checks to obtain a pass. No publication without its native choice.\n',
                encoding='utf-8', newline='\n')
            with (root / 'AGENTS.md').open('a', encoding='utf-8', newline='\n') as instructions:
                if host == 'codex':
                    instructions.write('\nIn noninteractive Codex exec resume, the test operator has no async-card '
                        'input surface. Use OH plain-chat fallback: show the complete prepared question and choices, '
                        'end the turn, and wait for the actual native reply through exec resume.\n')
                if scenario == 'delivery' and sanity:
                    instructions.write('\nSanity trial: on initial track selection stop at the prepared scope '
                                       'before workers. Present the native Stop choice. In a fresh session '
                                       'after actual Resume, deliver the approved task normally.\n')
                elif scenario == 'delivery':
                    instructions.write('\nAcceptance coordinator: in the FIRST implementation admission only, '
                        'ask the child to attempt reading missing-trial.txt, then return unfinished without edits '
                        'or checks. Preserve that real failed attempt and continue with a fresh author under '
                        'existing scope. Tell subsequent authors that this one-time injection is already done. '
                        'Do not repeat it or manufacture a capacity error.\n')
                elif scenario == 'choice':
                    instructions.write('\nAcceptance coordinator: after the actual track answer prepares '
                        'its scope, present the normal bound Stop decision and wait. Do not launch workers '
                        'in this selection-only probe.\n')
            (root / 'CLAUDE.md').write_text('Read AGENTS.md.\n', encoding='utf-8', newline='\n')
            for file, value in (('answer.txt', 'before'), ('marker.txt', 'before'), ('release.txt', 'pending')):
                (root / file).write_text(value + '\n', encoding='utf-8', newline='\n')
            (root / 'check.py').write_text(
                'from pathlib import Path\nassert Path("answer.txt").read_text() == "after\\n"\n'
                'assert Path("marker.txt").read_text() in ("before\\n", "done\\n")\n', encoding='utf-8', newline='\n')
            git(root, 'add', '.');git(root, 'commit', '-qm', 'tiny acceptance fixture')
            register(root, f'Acceptance {host} {scenario}')
            edit(root, 'project', lambda c: c.update({
                'plans': {'location': 'private' if scenario in ('planning', 'design') else 'repo',
                          'private_folder': str(base / 'plans')},
                'base_branch': 'main', 'tasks_per_batch': 1, 'review_rounds': 2,
                'checks': [{'name': 'answer', 'command': [sys.executable, 'check.py']}], 'models': profiles}))
            where = plans.layout(root)
            plans.start_roadmap(where, 'Tiny acceptance')
            plans.add_milestone(root, where, 'M1', 'First', 'One small useful change')
            if scenario == 'design':
                plans.add_initiative(root, where, 'M1', 'greeting',
                                     'Change answer.txt from before to after; preserve other application files.', [])
            elif scenario != 'planning':
                plans.add_initiative(root, where, 'M1', 'trial', 'Tiny delivery', [])
                body = ('## Why\n\nVerify ordinary delivery.\n\n## Tasks\n\n### Core track\n\n'
                        '- [ ] **1.** Change answer.txt to exactly after followed by one newline. '
                        'Preserve other application files. Run python3 check.py.\n')
                if scenario == 'delivery' and not sanity:
                    body += ('- [ ] **2.** Change marker.txt to exactly done followed by one newline. '
                             'Preserve other application files. Run python3 check.py. *Depends on task 1.*\n')
                else:
                    body += '\n### Other track\n\n- [ ] **3.** Change marker.txt to done followed by one newline.\n'
                number, _ = plans.write_design(root, where, 'trial', 'Tiny delivery', body, 'approved')
                plans.claim(root, where, 'trial', number)
                git(root, 'add', '.');git(root, 'commit', '-qm', 'approved acceptance design')
            git(root, 'update-ref', 'refs/remotes/origin/main', 'HEAD')
    (base / 'codex-home').mkdir()
    roots = [base / f'codex-{scenario}' for scenario in scenarios]
    (base / 'codex-home/config.toml').write_text(
        f'model = {json.dumps(codex_model)}\nmodel_reasoning_effort = "{effort}"\n'
        'sandbox_mode = "workspace-write"\napproval_policy = "on-request"\n'
        '[features]\nmulti_agent = true\ncodex_hooks = true\n'
        '[marketplaces.oh-dev]\nsource_type = "local"\nsource = ' + json.dumps(str(build / 'codex')) + '\n'
        '[plugins."o-harness@oh-dev"]\nenabled = true\n' +
        ''.join(f'[projects.{json.dumps(str(root))}]\ntrust_level = "trusted"\n' for root in roots), encoding='utf-8', newline='\n')
    save(base / 'claude-settings.json', {'enabledPlugins': {'o-harness@oh-dev': False}})
    print(base)
    print('Snapshot:', candidate['version'])
    print('No agents launched. Follow docs/cli-acceptance.md; run setup-codex for the candidate.')


def trial(path):
    base = Path(path).resolve()
    value = json.loads((base / 'trial.json').read_text(encoding='utf-8'))
    if value.get('kind') != 'oh-cli-acceptance' or value.get('root') != str(base):
        raise ValueError('Not the original acceptance fixture directory')
    os.environ['OH_DATA_HOME'] = str(base / 'data')
    os.environ['OH_DEV_NORMAL_DATA_HOME'] = str(base / 'data')
    sys.path.insert(0, str(Path(value['build']) / 'codex/plugins/o-harness/core/runtime'))
    return base, value


def inspect(path, host, scenario):
    base, value = trial(path)
    from oh.workflow import load_run
    from oh.storage import digest, read_json
    root = base / f'{host}-{scenario}'
    journal, state = load_run(root)
    for attempt in state['attempts']:
        for key in ('report_ref', 'source_ref'):
            ref = attempt.get(key)
            if ref and digest(read_json(ref['path'])) != ref['hash']:
                raise ValueError('Retained evidence hash changed')
    # Observation, not a PASS oracle: the operator also checks the native UI and
    # the earlier run when publication repair created a second run.
    result = {'candidate': value['candidate']['version'], 'host': host, 'scenario': scenario,
              'run': state['id'], 'workflow': state['workflow'], 'status': state['status'],
              'done': state['done'], 'tasks': [t['id'] for t in state['tasks']],
              'review_rounds': state['config']['review_rounds'],
              'attempts': [{'role': a['role'], 'outcome': a.get('outcome'), 'finished': a.get('finished')}
                           for a in state['attempts']],
              'files': {name: (root / name).read_text() for name in ('answer.txt', 'marker.txt', 'release.txt')},
              'git_status': git(root, 'status', '--porcelain'),
              'publication': {key: state.get('published', {}).get(key) for key in ('url', 'observed_head')},
              'retained_hashes': 'verified'}
    if scenario in ('planning', 'design'):
        from oh import plans, delivery
        from oh.storage import Refused
        where = plans.layout(root, claim=False)
        designs = {}
        for path in Path(where['designs']).glob('[0-9][0-9][0-9][0-9]-*.md'):
            number = path.name[:4]
            design = {'status': plans.approval(root, where, number)}
            try:
                delivery.selection(root, number, claim=False)
                design['deliverable'] = True
            except Refused as exc:
                design.update(deliverable=False, reason=str(exc))
            designs[number] = design
        result['designs'] = designs
    print(json.dumps(result, indent=2))


def launch(path, host, scenario, prompt, resume=None):
    """Replace this process with the installed native CLI; no agent loop or approval synthesis."""
    base, value = trial(path)
    root = base / f'{host}-{scenario}'
    from oh.storage import git_env
    env = {k: v for k, v in git_env().items() if not k.startswith(('CODEX_', 'OH_'))
           and k not in ('OPENAI_API_KEY', 'OPENAI_BASE_URL', 'ANTHROPIC_API_KEY', 'CLAUDECODE')}
    env.update(OH_DATA_HOME=str(base / 'data'), OH_DEV_NORMAL_DATA_HOME=str(base / 'data'))
    if host == 'codex':
        env['CODEX_HOME'] = str(codex_home(base, value))
        if value.get('codex_profile') == 'acceptance':
            check_codex_candidate(value, env)
        args = ['codex', '--no-daemon', '--approve-for-me']
        if resume:
            args += ['exec', 'resume', resume, prompt]
        else:
            args += ['--no-alt-screen', '-C', str(root), '--add-dir', str(base / 'data'),
                     '--add-dir', str(base / 'plans'), prompt]
    else:
        args = ['claude', '--model', value['models']['claude'], '--effort', value.get('effort', 'medium'),
                '--setting-sources', 'project,local', '--settings', str(base / 'claude-settings.json'),
                '--plugin-dir', str(Path(value['build']) / 'claude/plugins/o-harness'),
                '--strict-mcp-config', '--mcp-config', '{"mcpServers":{}}', '--permission-mode', 'auto']
        if resume:args += ['--resume', resume]
        args += ['--', prompt]
    os.chdir(root)
    os.execvpe(args[0], args, env)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('login-codex', help='sign in once to the dedicated acceptance profile')
    setup = sub.add_parser('setup-codex', help='install and verify this trial snapshot in the acceptance profile')
    setup.add_argument('directory')
    new = sub.add_parser('prepare')
    new.add_argument('--suite', choices=('sanity', 'catalog'), default='catalog')
    new.add_argument('--codex-model', required=True)
    new.add_argument('--claude-model', required=True)
    observe = sub.add_parser('inspect')
    observe.add_argument('directory');observe.add_argument('--host', choices=('codex', 'claude'), required=True)
    observe.add_argument('--scenario', choices=('delivery', 'planning', 'choice', 'design'), required=True)
    start = sub.add_parser('launch', help='open the native CLI; operator answers its actual questions')
    start.add_argument('directory');start.add_argument('--host', choices=('codex', 'claude'), required=True)
    start.add_argument('--scenario', choices=('delivery', 'planning', 'choice', 'design'), required=True)
    start.add_argument('--prompt', required=True);start.add_argument('--resume')
    args = parser.parse_args()
    if args.command == 'login-codex':codex_login()
    elif args.command == 'setup-codex':setup_codex(args.directory)
    elif args.command == 'prepare':prepare(args.codex_model, args.claude_model, args.suite)
    elif args.command == 'inspect':inspect(args.directory, args.host, args.scenario)
    else:launch(args.directory, args.host, args.scenario, args.prompt, args.resume)


if __name__ == '__main__':
    main()
