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
  Claude Code that happens at OH's `setup`, which the first OH command runs and which says so
  first; in Codex, when the first session starts OH's tools. OH then uses that Python first. Set `OH_PYTHON_DOWNLOAD=0`
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

After the one-time setup below, open **Actions → Release → Run workflow**, select `main`,
and enter a version such as `0.4.0`. Only Pedro can start or rerun it.

The workflow opens a PR changing only the Claude and Codex version fields, waits for the
required checks, and merges it through GitHub's normal protected-branch merge. This
version-only PR is the owner's explicitly authorized exception to human-merged development
PRs. It needs no separate **Approve and run** click: a dedicated GitHub App opens it.
Ordinary code PRs remain human-merged. Merging unrelated PRs no longer starts a release.

After main's checks pass on that exact merge commit, the release runs the existing full
Windows suite and installs the package in Claude Code and Codex on Windows, macOS and Linux
(`integrations/install-check.py`, no AI login needed). Only after all checks pass does it
create `vX.Y.Z`, publish the tested package to `dist`, and create the GitHub release with
release notes. The package format and Windows test selection are unchanged.

For a failure, run **Release** again with the same version. An existing release PR is
reused only after checking that it contains just the requested version change. A changed
or conflicting PR stops the run; inspect it, close it and delete its release branch before
starting again. Before a tag exists, a retry can include fixes merged to main. After the
tag exists, retries use that same tagged commit; source fixes then require a new version.
The workflow refuses older versions and never moves a published version tag. Cancellation
stops the automation; it does not undo a PR that has already merged.

Authorization, version-only PR recovery, changed PR rejection, tag pinning and exact-commit
verification are covered by `.github/scripts/test_release.py`:

```sh
python3 -m unittest discover -s .github/scripts -p 'test_*.py' -v
```

### One-time release setup (owner)

Merge the workflow PR before completing the publishing permissions in step 4.
No release is run by this setup.

1. In your GitHub account's **Settings → Developer settings → GitHub Apps → New GitHub App**,
   create a private App, for example `pmoreiracc-oh-release`. Use this repository's URL as
   its homepage, disable the webhook, and select **Only on this account**. Grant only
   **Contents: Read and write**, **Pull requests: Read and write**, and **Actions: Read-only**
   (Metadata read is automatic). No workflow-editing or administration permission is needed.
2. Install it on **only `pmoreiracc/o-harness`**. Note its numeric **App ID** and generate a
   private key from the App's General page.
3. In the repository's **Settings → Environments → release**, add an environment secret
   named **`RELEASE_APP_PRIVATE_KEY`** containing the downloaded PEM file. Keep it in this
   environment, not in repository-wide secrets. The environment allows only the `main`
   branch; it needs no additional approval click.
4. With `gh` authenticated as `pmoreiracc`, run from the merged checkout (replace `12345`):

   ```sh
   python3 .github/scripts/configure-release.py --app-id 12345
   ```

   This sets `RELEASE_APP_ID`, preserves main's existing required PR/check protections,
   restricts merging to Pedro and this App, and restricts publishing `dist` and version tags
   to those two identities. The App can bypass only the rule identifying who may merge;
   it cannot bypass required checks. Version tags cannot be changed or deleted.
   The setup also restricts Release, full suite and install check to Pedro. Other workflows
   accept only automatic events, so contributors' PR tests still run. Use **full suite** for
   manual test runs; **verify** runs automatically on PRs and main pushes.

The setup script can be rerun. Its `--prepare` option configures the main merge restriction
and environment before the App exists, leaving existing publication permissions alone.
Only the release jobs receive the App credential. Ordinary workflows have a read-only
`GITHUB_TOKEN`; an automation that needs to propose a PR must receive only the additional
permissions it needs and is still blocked from merging to main by the repository rules.
Contributors can propose changes through forks without write access to this repository.
Keep the App credential private and do not grant other people repository write/admin access
merely to accept contributions. The App is a separate publishing identity; its private key
must not be shared with other workflows or services.

GitHub enforces these settings outside the source files. The setup verifies their API
responses; a real first release still needs to be checked after the App is installed.

To try a build locally without releasing, run `integrations/package.sh <empty-folder>`
and add that folder as a local marketplace. OH only switches automatically to a higher
version, so activate a local build with `scripts/oh setup` from the installed plugin
(`setup --development` if the checkout had uncommitted changes).
