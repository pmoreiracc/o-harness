"""Install a built OH package into the real Claude Code and Codex apps the way a user does, and check that it works:
both apps load it, OH sets up from the installed plugin, Claude's menu hook runs, and Codex starts OH's tools. It
needs no AI login. The release workflow runs it on Windows, macOS and Linux before publishing anything.

  python integrations/install-check.py <package.tgz>   (the package integrations/package.sh builds, as a .tgz)

Set OH_CHECK_BASH to the bash Claude Code runs hooks with (Git Bash on Windows); plain `bash` otherwise.
"""
import json
import os
from pathlib import Path
import queue
import shutil
import subprocess
import sys
import tarfile
import tempfile
import threading


def run(*args, **kwargs):
    print('$', ' '.join(str(a) for a in args), flush=True)
    done = subprocess.run([str(a) for a in args], capture_output=True, text=True, encoding='utf-8', errors='replace', **kwargs)
    if done.returncode:sys.exit(f'Failed with exit code {done.returncode}:\n{done.stdout}\n{done.stderr}')
    return done.stdout


def program(name):
    # npm installs .cmd shims on Windows, which Python only runs by their full path.
    return shutil.which(name) or sys.exit(f'{name} is not installed')


def installed(home):
    """The plugin folder an app installed OH into."""
    found = sorted((home / 'plugins/cache/o-harness/o-harness').glob('*'))
    return found[-1] if found else sys.exit(f'OH is not installed under {home}')


def codex_tools(codex, env, cwd):
    """The tools Codex lists for OH's server, asked through Codex's own app-server protocol."""
    server = subprocess.Popen([codex, 'app-server'], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                              env=env, cwd=cwd, text=True, encoding='utf-8')
    lines = queue.Queue()
    threading.Thread(target=lambda:[lines.put(line) for line in server.stdout], daemon=True).start()
    def send(message):
        server.stdin.write(json.dumps({'jsonrpc': '2.0'} | message) + '\n');server.stdin.flush()
    try:
        send({'id': 1, 'method': 'initialize', 'params': {'clientInfo': {'name': 'oh-install-check', 'version': '1'}}})
        send({'method': 'initialized'})
        send({'id': 2, 'method': 'mcpServerStatus/list', 'params': {}})
        while True:
            try:reply = json.loads(lines.get(timeout=180))
            except queue.Empty:sys.exit('Codex did not answer with its tool servers within 3 minutes')
            if reply.get('id') == 2:break
        if 'error' in reply:sys.exit(f'Codex could not list its tool servers: {reply["error"]}')
        servers = {entry['name']: entry for entry in reply['result']['data']}
        return set((servers.get('o-harness') or {}).get('tools') or {})
    finally:
        server.kill();server.wait()


def main(archive):
    temp = Path(tempfile.mkdtemp(prefix='oh-install-check-'))
    package = temp / 'package'
    with tarfile.open(archive) as bundle:bundle.extractall(package, filter='tar')
    version = json.loads((package / 'claude/o-harness/.claude-plugin/plugin.json').read_text(encoding='utf-8'))['version']
    # Fresh app and OH folders, as on a computer where neither has been used.
    env = dict(os.environ, CLAUDE_CONFIG_DIR=str(temp / 'claude'), CODEX_HOME=str(temp / 'codex'),
               OH_DATA_HOME=str(temp / 'oh'), XDG_CONFIG_HOME=str(temp / 'config'))
    for folder in ('claude', 'codex'):(temp / folder).mkdir()

    print(f'== Claude Code loads OH {version}', flush=True)
    claude = program('claude')
    run(claude, 'plugin', 'marketplace', 'add', package, env=env)
    run(claude, 'plugin', 'install', 'o-harness@o-harness', env=env)
    details = run(claude, 'plugin', 'details', 'o-harness@o-harness', env=env)
    plugin = installed(temp / 'claude')
    expected = [p.parent.name for p in (plugin / 'skills').glob('*/SKILL.md')]
    hooks = json.loads((plugin / 'hooks/hooks.json').read_text(encoding='utf-8'))['hooks']
    missing = [name for name in [f'o-harness {version}', *expected, *hooks] if name not in details]
    if missing:sys.exit(f'Claude Code did not load all of OH: missing {missing}\n{details}')

    print('== Claude runs OH\'s menu hook, which refuses an answer the model filled in', flush=True)
    command = hooks['PreToolUse'][0]['hooks'][0]['command']
    menu = {'tool_name': 'AskUserQuestion', 'tool_input': {'questions': [{'question': 'OH gate check: Approve?', 'header': 'OH',
            'options': [{'label': 'Approve'}, {'label': 'Reconsider'}], 'multiSelect': False}], 'answers': {'OH gate check: Approve?': 'Approve'}}}
    said = run(os.environ.get('OH_CHECK_BASH', 'bash'), '-c', command, input=json.dumps(menu),
               env=env | {'CLAUDE_PLUGIN_ROOT': plugin.as_posix()})
    if '"deny"' not in said:sys.exit(f'OH\'s menu hook did not refuse a filled-in answer: {said!r}')

    print(f'== Codex loads OH {version}', flush=True)
    codex = program('codex')
    run(codex, 'plugin', 'marketplace', 'add', package, env=env)
    run(codex, 'plugin', 'add', 'o-harness@o-harness', env=env)
    plugin = installed(temp / 'codex')

    print('== OH sets up from the installed plugin and registers a project', flush=True)
    oh = plugin / ('scripts/oh.cmd' if os.name == 'nt' else 'scripts/oh')
    project = temp / 'project'
    run('git', 'init', '-q', project)
    run('git', '-C', project, '-c', 'user.name=OH check', '-c', 'user.email=check@example.invalid', 'commit', '-q', '--allow-empty', '-m', 'Start')
    run(oh, 'setup', env=env)
    run(oh, '--root', project, 'init', env=env)
    status = json.loads(run(oh, '--root', project, 'status', env=env))
    if status.get('status') != 'none':sys.exit(f'OH status on a new project said {status}')

    print('== Codex starts OH\'s tools', flush=True)
    tools = codex_tools(codex, env, project)
    if not {'status', 'deliver', 'choose'} <= tools:sys.exit(f'Codex lists these OH tools: {sorted(tools) or "none"}')
    print(f'OK: OH {version} installs and starts in Claude Code and Codex ({len(tools)} tools)', flush=True)


if __name__ == '__main__':
    main(sys.argv[1] if len(sys.argv) > 1 else sys.exit(__doc__))
