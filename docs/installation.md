# Installation and updates

## Requirements

- macOS, Linux, or 64-bit Windows 11 (x64 or ARM64) as a preview ([Windows notes](#windows)). The dashboard auto-start
  service covers macOS and Windows; on Linux run `oh serve` yourself.
- Python 3.12+ (on Windows, OH can fetch it for you) and Git.
- Claude Code signed in with a Claude subscription, or Codex signed in with ChatGPT.
  OH refuses API-key logins.

## Install

Claude Code:

```sh
claude plugin marketplace add pmoreiracc/o-harness#dist
claude plugin install o-harness@o-harness
```

Codex:

```sh
codex plugin marketplace add pmoreiracc/o-harness --ref dist
codex plugin add o-harness@o-harness
```

You can install it in both hosts. They share one OH installation and one data folder,
`~/.local/share/o-harness`. The first time a plugin runs OH, it installs its engine there
and creates the `oh` command at `~/.local/share/o-harness/bin/oh`. Add that folder to your
`PATH` if you want to type `oh` directly; the examples below assume you did.

## First use in a project

1. Start a new agent session in your project and run `/oh-propose <idea>`
   (Codex: `$oh-propose <idea>`). The first time, OH installs itself and the agent registers
   the project with `oh init`, saving your project's checks: the commands OH must pass
   before it commits, in your settings file (`~/.config/o-harness/settings.json`). Nothing
   runs yet. `/oh-config` shows them, and `oh config open` opens the file.
2. Run `/oh-propose <idea>` again.

OH finds your `claude` or `codex` binary on `PATH` each time it starts a worker. It starts
workers only with a native binary owned by you or the system, outside temporary and project
folders, that reports itself as Claude Code or Codex (OH runs `--version` to check) and is
signed in with a subscription. When the CLI updates itself, OH checks the new binary the
same way and prints a notice. To use a
binary that isn't on your `PATH`, pin it with `oh trust-host claude <absolute-path>`.

Registering a project changes nothing in its repository.

## Windows

CI runs the tests on a Windows Server runner, but no real Claude Code or Codex run on
Windows has been recorded yet, so treat Windows support as a preview.

- **Git for Windows**, which includes Git Bash: Claude Code runs OH's prompt hook through it.
- Codex uses its default Windows `cmd` hook runner. A custom PowerShell hook shell is not
  covered by this preview; keep the default for OH's packaged Windows hook.
- **Python:** nothing to install. OH uses Python 3.12 or newer if it finds one (`python3`,
  `python` or `py -3`). If there is none, it downloads the official Python 3.14.7 Windows
  package from python.org into `%USERPROFILE%\.local\share\o-harness\python` once: about
  12 MB, checked against its published SHA-256, with no admin rights and no `PATH` change. In
  Claude Code that happens at the first OH command, which says so first; in Codex, when the
  first session starts OH's tools. OH then uses that Python first. Set `OH_PYTHON_DOWNLOAD=0`
  to stop the download and install Python yourself.
- From PowerShell or cmd, run OH through `scripts\oh.cmd` (the plugin's, or
  `%USERPROFILE%\.local\share\o-harness\bin\oh.cmd` after setup). cmd re-reads `& | < > ^`
  in arguments, so pass JSON from a file: `oh.cmd config set checks @checks.json`.
- Git for Windows converts line endings by default (`core.autocrlf`); OH accepts files whose
  only difference from what Git stores is their line endings.
- **Claude workers have no shell on Windows.** Claude Code's sandbox doesn't run on native
  Windows, so OH's Claude workers only read and edit files; OH runs your project's checks
  after each task and sends failures back. Reviewers read the exact change from a file.
  Codex workers keep Codex's own Windows sandbox. For full Claude workers, run OH inside WSL 2,
  where it behaves as on Linux.
- Windows' search of the current folder is off for the commands OH starts (your checks keep
  it, since they run your project's own scripts), and OH starts `claude` or `codex` only when
  no one but you, the system or administrators can change the program, add files next to it,
  or replace a folder above it. Folders on your `PATH` are still searched, including a
  project's activated virtual environment.
- `oh service-install` adds a Task Scheduler task that starts the dashboard at logon,
  without admin rights or a window; `oh service-uninstall` removes it.

## Update

Merged changes reach you only when a new version is released.

- **Claude Code:** turn on auto-update for the `o-harness` marketplace in `/plugin` →
  Marketplaces, or run:

  ```sh
  claude plugin marketplace update o-harness
  claude plugin update o-harness@o-harness
  ```

- **Codex:**

  ```sh
  codex plugin marketplace upgrade o-harness
  codex plugin add o-harness@o-harness
  ```

Start a new session afterwards. The first OH command you run switches to the new version.
Updates only go forward: versions with Windows support install an `oh` command that older
versions' `setup` refuses to replace, so go back to an older version only with a fresh OH
data folder.
Batches already in progress finish on the version they started with. The dashboard service
restarts itself on the new version; if you installed it before version 0.3.0, run
`oh service-install` once more.
On Windows, OH retains earlier downloaded Python versions because an installed dashboard
task or an existing batch can still reference them. `python/current` selects the new version
for new commands. Reinstall the service with `oh service-install` to select the current
interpreter; remove old Python folders only after their batches have ended and no scheduled
task references them.

## Uninstall

```sh
claude plugin uninstall o-harness@o-harness   # or: codex plugin remove o-harness@o-harness
oh service-uninstall                          # only if you installed the dashboard service
```

This keeps your OH data: projects, review evidence and analytics. To remove everything,
delete `~/.local/share/o-harness` after uninstalling from both hosts.

## Releasing (maintainers)

1. Set the same plain `X.Y.Z` version in both `plugins/o-harness/.claude-plugin/plugin.json`
   and `plugins/o-harness/.codex-plugin/plugin.json`, and merge that change to `main`.
2. Tag the merge commit and push the tag:

   ```sh
   git tag v0.3.0
   git push origin v0.3.0
   ```

The release workflow checks that the tag matches both versions, runs the tests, publishes
the built packages to the `dist` branch and creates the GitHub release. Users then receive
the update as described above. Always bump the version: hosts only update when it changes.

To try a build locally without releasing, run `integrations/package.sh <empty-folder>`
and add that folder as a local marketplace. OH only switches automatically to a higher
version, so activate a local build with `scripts/oh setup` from the installed plugin
(`setup --development` if the checkout had uncommitted changes).
