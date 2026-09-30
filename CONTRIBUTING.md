# Contributing

## Issues

- **Bug:** include the OH version (`version` in `~/.local/share/o-harness/runtime/active.json`),
  your host and OS, steps to reproduce, and what you expected. Never post credentials,
  transcripts or your OH data folder.
- **Feature:** open an issue to agree on the problem and scope before building it. Small
  fixes can go straight to a PR.
- **Security:** see [SECURITY.md](SECURITY.md). Don't open a public issue.

## Development

You need Python 3.12+, Git, Node.js and Bash. Tests need no AI subscription or API key.

To develop OH with OH, import this repository's settings once in your fresh clone, before any OH
command: `oh profile-import integrations/oh-profile.json`. OH never reads settings from a repository
by itself, so this is your choice to run its checks: when OH delivers a task here it runs only the
tests the change affects (`integrations/test.sh affected`) and the syntax checks.

```sh
bash integrations/test.sh native   # behavior tests
bash integrations/test.sh syntax   # Python, JavaScript and shell syntax
```

1. Fork the repository and branch from `main`.
2. Read `config/invariants.json` and the code you are changing. Make the smallest complete
   change.
3. Add tests for the behavior or regression you fix. Tests use temporary repositories and
   fake model responses; never use a real project as a fixture.
4. For dashboard changes, check it in a browser at desktop and narrow widths.
5. Open a PR against `main` that explains the problem, the new behavior, how you checked it
   and any limits. Keep docs in sync with what the code actually does.

Maintainers run an independent review of every PR before merging. Only maintainers merge.
Merging to `main` releases nothing unless the merge changes the version; see
[releasing](docs/installation.md#releasing-maintainers).

## Try the local source in Claude Code and Codex

### One-time setup

Use the OH checkout where you actually edit code. Its current branch and uncommitted files
will power the development plugin, even when you use OH in another repository.
The checkout must contain `integrations/oh_dev.py`.

For Bash or Zsh, add this alias to your shell profile (`~/.bashrc` or `~/.zshrc`), replacing
both paths with absolute paths. Find your Python path with
`python3 -I -c 'import sys; print(sys.executable)'`:

```sh
alias oh-dev="'/absolute/path/to/python3' -I '/absolute/path/to/o-harness/integrations/oh_dev.py'"
```

For PowerShell, add this to `$PROFILE`, replacing both paths:

```powershell
$ohDevPython = 'C:\absolute\path\to\python.exe'
$ohDevScript = 'C:\absolute\path\to\o-harness\integrations\oh_dev.py'
function oh-dev { & $ohDevPython -I $ohDevScript @args }
```

Reload your profile or open a new terminal. Python 3.12+ and both host CLIs must be installed.
Once, from that OH checkout, register its checks in the separate development data:

```sh
oh-dev exec profile-import integrations/oh-profile.json
```

### Everyday use

From any directory, run `oh-dev on` to switch or `oh-dev off` to switch back. No repeated
alias setup, profile import, commit, push or version bump is needed.

`oh-dev on` enables a separate local development plugin in **both hosts**, for fresh sessions
in **any repository**. `oh-dev off` restores the previous released-plugin enablement;
`oh-dev status` shows the current state. Add `--host codex` or `--host claude` to select one.
Released plugin files are retained. Changing your terminal's directory does not change the
source checkout. To use another checkout, run `off` with the old definition first, then
update the saved definition and reload your profile.

The development plugin reads runtime, workflows, prompts, config and dashboard from the
linked checkout, including uncommitted edits. New OH commands use those live files;
skills and hook definitions refresh on each `on`. Start fresh host sessions after switching
or refreshing; restart them after MCP changes. Finish active OH runs before changing source.
Project-level plugin overrides take precedence; remove an OH override before testing there.

State lives in `~/.local/share/oh-dev`, separate from normal OH data. No consumer files or
services are installed. `oh-dev exec` runs source CLI commands with development data:

```sh
oh-dev exec status
oh-dev exec serve --port 4319
```

Development launchers refuse `setup` and service installation/removal. If switching fails,
run `oh-dev off --host <reported-host>`, fix the reported cause, and retry.
The helper, these instructions and two installation regression cases are committed;
generated plugins, host settings and development data are not.
