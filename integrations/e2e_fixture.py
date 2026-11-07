"""Prepare tiny real-CLI acceptance projects. Never launch agents or supply approvals.

Run explicitly: python3 integrations/e2e_fixture.py prepare
Then follow docs/cli-acceptance.md. Everything except the packaged snapshot lives
in the printed temporary folder. This is fixture setup, not a second agent runner.
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


def prepare(codex_model, claude_model):
    base = Path(tempfile.mkdtemp(prefix='oh-cli-acceptance-')).resolve()
    print('Preparing isolated fixtures in ' + str(base), file=sys.stderr, flush=True)
    os.environ['OH_DATA_HOME'] = str(base / 'data')
    os.environ['OH_DEV_NORMAL_DATA_HOME'] = str(base / 'data')
    import oh_dev
    build, candidate = oh_dev.create_snapshot()
    save(base / 'trial.json', {'kind': 'oh-cli-acceptance', 'root': str(base), 'build': str(build),
                             'candidate': candidate, 'models': {'codex': codex_model, 'claude': claude_model}})
    from oh.registry import register
    from oh.config import edit
    from oh import plans
    profiles = {host: {role: {'model': model, 'effort': 'medium'}
                      for role in ('simple', 'standard', 'complex', 'review', 'insights')}
                for host, model in (('codex', codex_model), ('claude', claude_model))}
    for host in ('codex', 'claude'):
        for scenario in ('delivery', 'planning', 'choice'):
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
                if scenario == 'delivery':
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
                'plans': {'location': 'private' if scenario == 'planning' else 'repo',
                          'private_folder': str(base / 'plans')},
                'base_branch': 'main', 'tasks_per_batch': 1, 'review_rounds': 2,
                'checks': [{'name': 'answer', 'command': [sys.executable, 'check.py']}], 'models': profiles}))
            where = plans.layout(root)
            plans.start_roadmap(where, 'Tiny acceptance')
            plans.add_milestone(root, where, 'M1', 'First', 'One small useful change')
            if scenario != 'planning':
                plans.add_initiative(root, where, 'M1', 'trial', 'Tiny delivery', [])
                body = ('## Why\n\nVerify ordinary delivery.\n\n## Tasks\n\n### Core track\n\n'
                        '- [ ] **1.** Change answer.txt to exactly after followed by one newline. '
                        'Preserve other application files. Run python3 check.py.\n')
                if scenario == 'delivery':
                    body += ('- [ ] **2.** Change marker.txt to exactly done followed by one newline. '
                             'Preserve other application files. Run python3 check.py. *Depends on task 1.*\n')
                else:
                    body += '\n### Other track\n\n- [ ] **3.** Change marker.txt to done followed by one newline.\n'
                number, _ = plans.write_design(root, where, 'trial', 'Tiny delivery', body, 'approved')
                plans.claim(root, where, 'trial', number)
                git(root, 'add', '.');git(root, 'commit', '-qm', 'approved acceptance design')
            git(root, 'update-ref', 'refs/remotes/origin/main', 'HEAD')
    (base / 'codex-home').mkdir()
    roots = [base / f'codex-{scenario}' for scenario in ('delivery', 'planning', 'choice')]
    (base / 'codex-home/config.toml').write_text(
        f'model = {json.dumps(codex_model)}\nmodel_reasoning_effort = "medium"\n'
        'sandbox_mode = "workspace-write"\napproval_policy = "on-request"\n'
        '[features]\nmulti_agent = true\ncodex_hooks = true\n'
        '[marketplaces.oh-dev]\nsource_type = "local"\nsource = ' + json.dumps(str(build / 'codex')) + '\n'
        '[plugins."o-harness@oh-dev"]\nenabled = true\n' +
        ''.join(f'[projects.{json.dumps(str(root))}]\ntrust_level = "trusted"\n' for root in roots), encoding='utf-8', newline='\n')
    save(base / 'claude-settings.json', {'enabledPlugins': {'o-harness@oh-dev': False}})
    print(base)
    print('Snapshot:', candidate['version'])
    print('No agents launched. Follow docs/cli-acceptance.md; authenticate/trust only this test profile.')


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
    if scenario == 'planning':
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
           and k not in ('OPENAI_API_KEY', 'ANTHROPIC_API_KEY', 'CLAUDECODE')}
    env.update(OH_DATA_HOME=str(base / 'data'), OH_DEV_NORMAL_DATA_HOME=str(base / 'data'))
    if host == 'codex':
        env['CODEX_HOME'] = str(base / 'codex-home')
        args = ['codex', '--no-daemon', '--approve-for-me']
        if resume:
            args += ['exec', 'resume', resume, prompt]
        else:
            args += ['--no-alt-screen', '-C', str(root), '--add-dir', str(base / 'data'),
                     '--add-dir', str(base / 'plans'), prompt]
    else:
        args = ['claude', '--model', value['models']['claude'], '--effort', 'medium',
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
    new = sub.add_parser('prepare')
    new.add_argument('--codex-model', required=True)
    new.add_argument('--claude-model', required=True)
    observe = sub.add_parser('inspect')
    observe.add_argument('directory');observe.add_argument('--host', choices=('codex', 'claude'), required=True)
    observe.add_argument('--scenario', choices=('delivery', 'planning', 'choice'), required=True)
    start = sub.add_parser('launch', help='open the native CLI; operator answers its actual questions')
    start.add_argument('directory');start.add_argument('--host', choices=('codex', 'claude'), required=True)
    start.add_argument('--scenario', choices=('delivery', 'planning', 'choice'), required=True)
    start.add_argument('--prompt', required=True);start.add_argument('--resume')
    args = parser.parse_args()
    if args.command == 'prepare':prepare(args.codex_model, args.claude_model)
    elif args.command == 'inspect':inspect(args.directory, args.host, args.scenario)
    else:launch(args.directory, args.host, args.scenario, args.prompt, args.resume)


if __name__ == '__main__':
    main()
