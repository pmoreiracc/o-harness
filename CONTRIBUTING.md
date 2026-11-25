# Contributing

Contributions to OH start as issues. Open one in [GitHub Issues](https://github.com/pmoreiracc/o-harness/issues) to report a bug, describe a problem you hit, or propose a feature.

## Open an issue

- **Bugs.** Include the OH version (the `version` field in `~/.local/share/o-harness/runtime/active.json`), your host and OS, the steps to reproduce, and what you expected. Never post credentials, transcripts or your OH data folder.
- **Features.** Describe the problem you want solved and how you work today.
- **Security problems.** Follow [SECURITY.md](SECURITY.md). Don't open a public issue.

## Build and test OH locally

The rest of this page describes how OH is built and tested, for reproducing an issue or running OH from source.

### Set up

Building and testing OH needs Python 3.12+, Git, Node.js and Bash. Deterministic tests need no AI credentials. Live sanity and the nightly catalog use real Claude and ChatGPT subscription sign-ins.

OH is developed with OH. To use the project's own checks, import this repository's settings once in your clone, before any other OH command:

```sh
oh profile-import integrations/oh-profile.json
```

OH never reads settings from a repository on its own, so this import is how you opt in to its checks. When OH delivers a task here, it runs the tests the change affects (`integrations/test.sh affected`) and the syntax checks.

### Run the tests

```sh
bash integrations/test.sh core               # fast deterministic core, during development
bash integrations/test.sh pr origin/main     # final local selection, the same one CI runs
bash integrations/test.sh native             # full deterministic suite, usually nightly
bash integrations/test.sh syntax             # Python, JavaScript and shell syntax
```

### Code conventions

Paths and temporary files:

- Use `oh.system.Path` for runtime filesystem paths. It keeps ordinary path strings in saved records and adds Windows' extended-path prefix only for filesystem calls.
- Use `str(path)` for saved identities and for working directories of external processes. Use `os.fspath(path)` for a filesystem API that needs a string.
- Use `system.file_uri` for SQLite file URIs, so long paths and punctuation in file names work.
- Use `storage.state_mkdir` for state subdirectories. On Windows, children inherit the data root's existing access; on Unix, private modes are kept. `state_path` repairs only the old Python-private directory ACL on paths below that root and leaves custom ACLs alone. Don't reset permissions recursively.
- Use `system.temporary_directory`, or `make_temp_directory` when you manage cleanup yourself, for OH scratch directories, so sandboxed Windows commands keep their parent's access.

Windows tests:

- Keep normal fixture writes portable, with LF line endings. Mark tests that deliberately exercise Windows-specific behavior with a comment naming the behavior.
- Windows CI jobs log why each test was selected, a digest of all selected test IDs, and when each module starts. Changing a shared `test_fixtures_*.py` module selects its consumers; editing one consumer doesn't select its siblings.
- The selection runs in two partitions, with module and class setup kept together. The required `windows` check waits for both and uses an assignment digest to confirm they agreed on the split.
- To compare Windows test performance, run the same expanded test IDs on the baseline and the candidate on the same runner image. Compare test time and total job time separately, and account for cases that moved between per-change and full-suite coverage.

Nightly runs full Windows discovery. Each release verifies the candidate package and installation on Linux, macOS and Windows. To try a package locally, see [Local build](docs/installation.md#local-build). How changes are scoped, reviewed and accepted is in [Developing and testing OH](docs/development-testing.md).

## Run local source with `oh-dev`

`oh-dev` packages your working checkout as a separate development plugin and switches both hosts to it, in any repository.

### One-time setup

Use the OH checkout where you edit code. Its current branch and uncommitted files are packaged, even when you use OH in another repository. The checkout must contain `integrations/oh_dev.py`, and Python 3.12+ and both host CLIs must be installed.

For Bash or Zsh, add this alias to `~/.bashrc` or `~/.zshrc`, with absolute paths. Find your Python path with `python3 -I -c 'import sys; print(sys.executable)'`.

```sh
alias oh-dev="'/absolute/path/to/python3' -I '/absolute/path/to/o-harness/integrations/oh_dev.py'"
```

For PowerShell, add this to `$PROFILE`. Windows PowerShell and PowerShell 7 have separate profiles; add it to each one you use.

```powershell
$ohDevPython = 'C:\absolute\path\to\python.exe'
$ohDevScript = 'C:\absolute\path\to\o-harness\integrations\oh_dev.py'
function oh-dev { & $ohDevPython -I $ohDevScript @args }
```

Reload your profile or open a new terminal. Then, once, from the OH checkout, register its checks if it isn't registered yet:

```sh
oh-dev exec profile-import integrations/oh-profile.json
```

### Everyday use

| Command | What it does |
|---|---|
| `oh-dev on` | Builds a fixed snapshot of your checkout and enables it in both hosts |
| `oh-dev off` | Restores the released plugin |
| `oh-dev status` | Shows each host's mode, snapshot version, source revision and build path |
| `oh-dev build` | Builds a snapshot without switching hosts |
| `oh-dev on --build <path>` | Enables an earlier `oh-dev build` snapshot |
| `oh-dev on --live` | Loads runtime, workflows, prompts, config and dashboard directly from the checkout |
| `oh-dev exec <command>` | Runs an `oh` command with the selected development runtime and data |
| `oh-dev dashboard --host codex` | Reopens the development dashboard without rebuilding |

Add `--host codex` or `--host claude` to `on`, `off` or `status` to select one host. Start new host sessions after switching.

Each `oh-dev on` build gets a unique version, such as `0.5.0-SNAPSHOT.1790853731453599000`, shared by both plugins and their engine, and lives under `~/.local/share/oh-dev/builds/`. Uncommitted edits are included; later edits don't change the snapshot, so run `on` again for a new build. Live builds are marked `-SNAPSHOT.live.<build-id>`, and their skills and hook definitions refresh on each `on`. Keep a build folder while sessions or runs use it.

In Codex, development builds show **OH DEV** with the development icon; releases show **OH** with the violet icon.

### Development dashboard

`oh-dev on` also starts the development dashboard at <http://localhost:4319> and opens it. `oh-dev off` opens the release dashboard at <http://localhost:4318> and leaves the release service as it is. The development dashboard stops when the last host leaves development. `oh-dev exec serve` runs it in the foreground on port 4319. No OS service is installed for development.

### Shared or isolated data

By default, `oh-dev on` and `oh-dev build` use your normal OH projects, settings and history, and update them in place. For disposable tests, add `--isolated-data` to use `~/.local/share/oh-dev/data` instead; it also works with `--live` and `--host`. The choice is frozen into each build. `oh-dev status` shows which one is selected.

If the hosts use different builds or data, choose one with `oh-dev exec --host codex <command>` or `oh-dev exec --host claude <command>`. To import a profile for an isolated test, run `oh-dev on --isolated-data` first, then `oh-dev exec profile-import ...`.

### Things to know

- Finish active OH runs before switching to a different build. `off` restores the plugin but doesn't stop a run.
- Don't mix release helpers and DEV in the same session.
- Project-level plugin overrides take precedence. Remove an OH override in a project before testing there.
- Codex trusts each hook definition separately. `oh-dev on` and `oh-dev status --host codex` report OH DEV hook trust. If a review is needed, run `codex` in the project, enter `/hooks`, trust the current OH DEV hooks, and start new sessions. OH never writes hook trust for you.
- Development launchers refuse `setup` and service installation. If switching fails, run `oh-dev off --host <reported-host>`, fix the reported cause, and retry.
- Generated plugins, host settings and development data aren't committed.
