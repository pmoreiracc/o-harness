# Installation and updates

## Requirements

- macOS or Linux. Native Windows 11 (64-bit, x64 or ARM64) is in preview; see [Windows](#windows).
- Python 3.12+ and Git. On Windows, OH can download Python for you.
- Claude Code signed in with a Claude subscription, or Codex signed in with ChatGPT. OH checks the sign-in before it starts agents and doesn't use API keys.

## Install

**Claude Code**

```sh
claude plugin marketplace add pmoreiracc/o-harness#dist
claude plugin install o-harness@o-harness
```

**Codex**

```sh
codex plugin marketplace add pmoreiracc/o-harness --ref dist
codex plugin add o-harness@o-harness
```

You can install OH in both hosts. They share one installation and one data folder, `~/.local/share/o-harness`. The first time a plugin runs OH, it installs the engine there and creates the `oh` command at `~/.local/share/o-harness/bin/oh`. Add that folder to your `PATH` to run `oh` directly. The examples in these docs assume you did.

## First use in a project

Open a new session in your project and give OH an idea:

```text
/oh-propose Add search to my notes app.
```

In Codex, use `$oh-propose`. On first use, OH:

1. Registers the project with `oh init`. Registration writes nothing to your repository.
2. Saves your project's checks, the commands that must pass before OH commits a task, in `~/.config/o-harness/settings.json`. Run `/oh-config` to see them, or `oh config open` to edit the file.
3. Asks **Where should OH keep this project's plans?**, then continues with your original request.

If setup hits a problem outside OH, it names the fix, and your request stays pending until you retry.

OH's agents run inside Claude Code or Codex, with that host's subscription and tool permissions. Keep the host CLI up to date. OH checks that the configured model and effort are available before it starts an agent.

### Codex on Linux

A `workspace-write` sandbox can block OH's writes outside the repository. If a command reports denied access, retry the same command with Codex's native execution permission. The first setup may also need one-time permission to create a lock file next to OH's data folder.

To give Codex ongoing access to the default layout with private plans, start it from a terminal:

```sh
(umask 077; mkdir -p "$HOME/.local/share/o-harness" "$HOME/.config/o-harness" "$HOME/oh-plans")
codex --add-dir "$HOME/.local/share/o-harness" \
  --add-dir "$HOME/.config/o-harness" \
  --add-dir "$HOME/oh-plans"
```

Use your own paths if they differ. With an absolute `XDG_CONFIG_HOME`, settings live in `$XDG_CONFIG_HOME/o-harness`. If you keep plans in the repository, leave out `~/oh-plans`.

## Windows

Native Windows 11 support is in preview. [Known limits](known-limits.md) lists what's still being tested.

- **Git for Windows** is required. Claude Code runs OH's hooks through its Git Bash.
- Codex runs OH's hooks through its default `cmd` hook runner. Keep that default; a custom PowerShell hook shell isn't supported for OH's hooks.
- **Python** needs no setup. OH uses Python 3.12 or newer if it finds one (`python3`, `python` or `py -3`). Otherwise it downloads the official Python 3.14.7 embeddable package from python.org into `%USERPROFILE%\.local\share\o-harness\python`, about 12 MB, checked against its pinned SHA-256, with no admin rights and no `PATH` change. Set `OH_PYTHON_DOWNLOAD=0` to install Python yourself instead.
- From PowerShell or cmd, run OH as `%USERPROFILE%\.local\share\o-harness\bin\oh.cmd`. cmd re-reads `& | < > ^` in arguments, so pass JSON from a file, for example `oh.cmd config set checks @checks.json`.
- Files that differ from Git's copy only in line endings (`core.autocrlf`) count as unchanged.
- OH uses Windows extended paths for its own files, so long paths in its data folder work without registry changes.
- `oh service-install` starts the dashboard at logon through Task Scheduler, with no admin rights and no window. `oh service-uninstall` removes it.

## Update

Run this in a session:

```text
/oh-update
```

In Codex, run `$oh-update`. OH refreshes the release marketplace and updates the plugin in every host where it's installed, on macOS, Linux and Windows. To update one host, add its name, as in `/oh-update codex`.

It reports each host's result as `<host>: <old> -> <new>`, or `<host>: <version> — up to date`. A host where OH isn't installed yet gets the latest release and reports `not installed -> <version>`. A host that isn't found is reported as skipped. If one host fails, the other still updates.

Start a new session afterwards. The first OH command switches to the new version. Your saved work, settings, plans and spent review rounds carry over, and `/oh-resume` continues any saved run in the new session.

### Codex hook trust

Codex trusts each hook definition separately, so a changed OH hook, even a changed timeout, needs your review. Open a terminal in the project, run `codex`, enter `/hooks`, and trust the OH hooks you approve. Then start new sessions. See [Codex hook trust](https://learn.chatgpt.com/docs/hooks#review-and-trust-hooks).

### Update with host commands

**Claude Code:** turn on auto-update for the `o-harness` marketplace in `/plugin` → Marketplaces, or run:

```sh
claude plugin marketplace update o-harness
claude plugin update o-harness@o-harness
```

**Codex:** the marketplace refresh also updates installed plugins.

```sh
codex plugin marketplace upgrade o-harness
```

### Where OH finds the host CLIs

When a session's `PATH` doesn't include the other host's CLI, `oh-update` uses the executable OH recorded earlier, after checking it again. On Windows, the Codex app replaces its CLI folder on every app update, so OH looks the current copy up each time. An absolute `CODEX_CLI_PATH` takes precedence. If the Codex app hasn't installed its CLI yet, open the app once and retry. To pin a specific binary, run `oh trust-host <host> <path>`.

### Older versions

OH only moves forward. Newer versions install an `oh` command that older versions can't replace, so to go back to an older version, use a fresh OH data folder.

The dashboard service restarts on the new version by itself. If you installed it before version 0.3.0, run `oh service-install` once more. On Windows, run `oh service-install` after an update to move the service to the newest downloaded Python. OH keeps earlier Python downloads; remove an old one only once no batch or scheduled task uses it.

## Uninstall

```sh
claude plugin uninstall o-harness@o-harness   # or: codex plugin remove o-harness@o-harness
oh service-uninstall                          # only if you installed the dashboard service
```

Uninstalling keeps your OH data: projects, review evidence and dashboard history. To remove everything, delete `~/.local/share/o-harness` and `~/.config/o-harness` after uninstalling from both hosts.

## Local build

To try a build without releasing it, run `integrations/package.sh <empty-folder>` and add that folder as a local marketplace. OH only switches automatically to a higher version, so activate a local build with `scripts/oh setup` from the installed plugin, or `scripts/oh setup --development` if the checkout has uncommitted changes.

Keep the build that wrote a run available while that run is in use. Newer completion records need a compatible reader, so use separate development data when a trial must switch back to an older runtime. For day-to-day development builds, see `oh-dev` in [CONTRIBUTING.md](../CONTRIBUTING.md).
