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

From this checkout, define `oh-dev` once in Bash or Zsh:

```sh
alias oh-dev="'$(python3 -I -c 'import sys; print(sys.executable)')' -I '$PWD/integrations/oh_dev.py'"
oh-dev on
```

For PowerShell:

```powershell
$ohDevPython = (Get-Command python).Source
$ohDevScript = Join-Path $PWD 'integrations/oh_dev.py'
function oh-dev { & $ohDevPython -I $ohDevScript @args }
oh-dev on
```

Save the definition with expanded absolute paths in your shell profile to keep it.
Python 3.12+ and both host CLIs must be installed. No commit, push or version bump is needed.

`oh-dev on` enables a separate local development plugin in **both hosts**, for fresh sessions
in **any repository**. `oh-dev off` restores the previous released-plugin enablement;
`oh-dev status` shows the current state. Add `--host codex` or `--host claude` to select one.
Released plugin files are retained. Use `off` before switching to another source checkout.

The development plugin runs this checkout's runtime, workflows, prompts, config and dashboard.
Skills and hook definitions refresh on each `on`. Start fresh host sessions after switching or
refreshing; restart them after MCP changes. Finish active OH runs before changing source.
Project-level plugin overrides take precedence; remove an OH override before testing there.

State lives in `~/.local/share/oh-dev`, separate from normal OH data. No consumer files or
services are installed. `oh-dev exec` runs source CLI commands with development data:

```sh
oh-dev exec profile-import integrations/oh-profile.json
oh-dev exec status
oh-dev exec serve --port 4319
```

Development launchers refuse `setup` and service installation/removal. If switching fails,
run `oh-dev off --host <reported-host>`, fix the reported cause, and retry.
The helper, these instructions and two installation regression cases are committed;
generated plugins, host settings and development data are not.
