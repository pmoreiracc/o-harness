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
Maintainers decide when to publish releases. For local testing, see
[local builds](docs/installation.md#local-build).

## Try the local source in Claude Code and Codex

### One-time setup

Use the OH checkout where you actually edit code. Its current branch and uncommitted files
will be packaged for the development plugin, even when you use OH in another repository.
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

`oh-dev on` builds a fixed snapshot and enables it as a separate development plugin in
**both hosts**, for fresh sessions in **any repository**. Each build gets a unique version
such as `0.5.0-SNAPSHOT.1790853731453599000`, shared by both plugins and their packaged engine.
It prints its version and folder under `~/.local/share/oh-dev/builds/`. Uncommitted edits are
included; later edits and commits do not change the snapshot. This is the default for testing
OH while OH itself changes. Run `on` again when you want a new build.

`oh-dev off` restores the previous released-plugin enablement. `oh-dev status` shows each
host's mode, snapshot version, source revision and build path. Add `--host codex` or
`--host claude` to `on`, `off` or `status` to select one host.
Released plugin files are retained. Changing your terminal's directory does not change the
source checkout. To use another checkout, run `off` with the old definition first, then
update the saved definition and reload your profile.

To build without changing either host, or reuse an earlier build:

```sh
oh-dev build
oh-dev on --build /absolute/path/printed/by/build
```

The folder must be a complete `oh-dev build` snapshot. Both hosts are packaged even when
only one is selected for activation. Keep build folders while their sessions or runs are in use.
Snapshots use the existing packager, including the platform launchers, and retain their own
runtime, workflows, hooks and development adapter; release manifests and release version
ordering are not changed.

For rapid iteration against another repository, `oh-dev on --live` keeps the old behavior:
runtime, workflows, prompts, config and dashboard come directly from the linked checkout.
Skills and hook definitions refresh on each `on`. Live plugin versions are marked
`-SNAPSHOT.live.<build-id>`. Finish active live runs before editing OH's source.

Start fresh host sessions after switching or refreshing. Finish active OH runs before
selecting a different build; `off` restores plugin enablement but does not stop a run.
Project-level plugin overrides take precedence; remove an OH override before testing there.

State lives in `~/.local/share/oh-dev`, separate from normal OH data. No consumer files or
services are installed. `oh-dev exec` uses the selected development runtime and data:

```sh
oh-dev exec status
oh-dev exec serve --port 4319
```

If the hosts use different builds, select `oh-dev exec --host codex <command>` or
`oh-dev exec --host claude <command>`. Before development is enabled, `exec` uses the source
checkout so the one-time profile import still works.

Development launchers refuse `setup` and service installation/removal. If switching fails,
run `oh-dev off --host <reported-host>`, fix the reported cause, and retry.
The installation tests `test_development_switch_restores_both_hosts_after_refresh_and_failure`,
`test_development_bridges_use_live_source_and_isolated_data` and
`test_development_snapshot_freezes_all_entries_and_exec_selects_it` cover switching,
restoration, source isolation and selecting the packaged runtime. Generated plugins,
host settings and development data are not committed.
