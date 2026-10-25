# Installation and updates

The observed native Codex Stop limitation is tracked in [issue #81](https://github.com/pmoreiracc/o-harness/issues/81)
and does not block activation or release. Required checks and independent review still
apply; see [the validation record](plans/native-workflows.md).

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
2. OH continues the saved command after registration. If setup reports an external obstacle,
   follow its concrete recovery instruction; your original command remains pending.

Native workflow agents run inside the active Claude or Codex host using its signed-in
subscription and ordinary tool permissions. OH no longer starts a separate headless
worker or requires a pinned worker executable. Keep the host and its CLI current;
model/effort availability is checked before admission, with no API fallback.

Registering a project changes nothing in its repository.

## Windows

CI runs the tests on a Windows Server runner, but no real Claude Code or Codex run on
Windows has been recorded yet, so treat Windows support as a preview.

- **Git for Windows**, which includes Git Bash: Claude Code runs OH's hooks through it.
- Codex uses its default Windows `cmd` hook runner. A custom PowerShell hook shell is not
  covered by this preview; keep the default for OH's packaged Windows hooks.
- **Python:** nothing to install. OH uses Python 3.12 or newer if it finds one (`python3`,
  `python` or `py -3`). If there is none, it downloads the official Python 3.14.7 Windows
  package from python.org into `%USERPROFILE%\.local\share\o-harness\python` once: about
  12 MB, checked against its published SHA-256, with no admin rights and no `PATH` change. In
  Claude Code that happens at OH's `setup`, which the first OH command runs and which says so
  first; in Codex, when the first session starts OH's tools. OH then uses that Python first. Set `OH_PYTHON_DOWNLOAD=0`
  to stop the download and install Python yourself.
- From PowerShell or cmd, run OH through `scripts\oh.cmd` (the plugin's, or
  `%USERPROFILE%\.local\share\o-harness\bin\oh.cmd` after setup). cmd re-reads `& | < > ^`
  in arguments, so pass JSON from a file: `oh.cmd config set checks @checks.json`.
- Git for Windows converts line endings by default (`core.autocrlf`); OH accepts files whose
  only difference from what Git stores is their line endings.
- OH uses Windows extended paths for its file operations, including saved evidence,
  locks, recovery and backups. Existing saved path identities stay unchanged; no registry
  change or data migration is needed. External tools retain their own path limits.
- Native Claude and Codex agents use their host's available tools and permissions.
  OH does not remove Claude's shell or install a replacement Windows sandbox.
  Codex shell hooks accept both canonical `Bash` command payloads and native
  `exec_command` payloads (`cmd`); both require the same owned-command reservation.
  Real native Windows workflow and Stop validation are still required before claiming
  support for this candidate.
- `oh service-install` adds a Task Scheduler task that starts the dashboard at logon,
  without admin rights or a window; `oh service-uninstall` removes it.

## Update

Merged changes reach you only when a new version is released.

Inside your session, run `/oh-update` in Claude Code or `$oh-update` in Codex to refresh
the release marketplace and update OH in both installed hosts on Windows, macOS and Linux.
To select one host, use `/oh-update codex` or `$oh-update claude`.

It reports the installed plugin versions, for example `codex: 0.5.0 -> 0.6.0`, or
`codex: 0.6.0 — up to date` after a successful refresh finds no change. A host failure does
not prevent updating the other host; the command reports the error and exits unsuccessfully.
If the release plugin is missing, the command adds the official release marketplace and
installs the latest release, reporting `not installed -> <version>`.
When a session's `PATH` omits another host's CLI, OH revalidates and uses that host's
previously recorded executable. On Windows, the Codex app keeps its CLI in a folder it
replaces on every app update, so when `codex` is not on `PATH`, OH looks that copy up again
on each use and records the current one. `CODEX_CLI_PATH`, the app's own override, is used
first when it is an absolute path to an existing file. If the app has not installed its CLI
yet, open the Codex app once and retry. If a running Codex session keeps an older copy, OH
uses the copy named by the installed app. When it cannot tell which copy is current,
`oh-update` keeps using the copy it recorded if that still exists; otherwise close the
Codex sessions, reopen the app and retry. Hosts it cannot find are reported explicitly as
skipped. A binary named with `oh trust-host <host> <path>` stays pinned until you trust
another.

You can also use the host commands directly:

- **Claude Code:** turn on auto-update for the `o-harness` marketplace in `/plugin` →
  Marketplaces, or run:

  ```sh
  claude plugin marketplace update o-harness
  claude plugin update o-harness@o-harness
  ```

- **Codex:**

  ```sh
  codex plugin marketplace upgrade o-harness
  ```

  The marketplace refresh also updates installed plugins.

Start a new session afterwards. The first OH command you run switches to the new version.
Updates only go forward: versions with Windows support install an `oh` command that older
versions' `setup` refuses to replace, so go back to an older version only with a fresh OH
data folder.
Finish or cancel active native work before switching builds. Current helpers preserve
historical evidence and adopt unfinished work only at a quiet boundary; they do not
restart a retired runner or replenish allowances. The dashboard service
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

## Local build

To try a build locally without releasing, run `integrations/package.sh <empty-folder>`
and add that folder as a local marketplace. The known native Stop limitation is
tracked in [issue #81](https://github.com/pmoreiracc/o-harness/issues/81) and does not block local
activation or release.
OH only switches automatically to a higher
version, so activate a local build with `scripts/oh setup` from the installed plugin
(`setup --development` if the checkout had uncommitted changes).
