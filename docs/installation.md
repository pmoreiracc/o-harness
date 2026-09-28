# Installation and updates

## Requirements

- macOS or Linux. Native Windows support is in progress: CI runs the Windows-sensitive tests on each PR and all tests nightly and before a release,
  but no real Claude Code or Codex run has been done there yet. The dashboard auto-start service is macOS only; on other
  systems run `oh serve` yourself.
- Python 3.11+ as `python3`, and Git.
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
Batches already in progress finish on the version they started with. The dashboard service
restarts itself on the new version; if you installed it before version 0.3.0, run
`oh service-install` once more.

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
