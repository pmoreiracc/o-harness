# Installation and versions

OH currently has an early local distribution for **Codex and Claude Code**. It is not
published in either vendor's universal public directory. A local marketplace makes it
available in your native plugin manager; it does not publish it for everyone or upload
it to a web account. The public installer is tracked in [issue 2](https://github.com/pmoreiracc/o-harness/issues/2).

## What gets installed

- A host-specific plugin: explicit skills and the native prompt hook.
- An immutable shared core under `~/.local/share/o-harness/versions/<revision>` and a
  stable command at `~/.local/share/o-harness/bin/oh`.
- External project profiles and evidence in that same data home. Products need no OH files.
- Optionally, a macOS login service for the dashboard at `http://localhost:4318`.

The two hosts share the core and data. Removing one plugin does not remove the other host,
shared core, registered projects, review evidence or analytics.

## Try uninstalling and reinstalling an existing local setup

Finish or explicitly stop active runs first. Keep the marketplace and package source in
place so that reinstalling can find them. This exercise preserves your settings/history;
it is not a factory reset and does not test first-time registration.

1. In the Codex plugin manager, select **o-harness** in your local marketplace and uninstall
   it. Alternatively, when the marketplace is named `personal`:

   ```sh
   codex plugin remove o-harness@personal
   ```

2. For Claude Code, if the marketplace is named `oh-local`:

   ```sh
   claude plugin uninstall o-harness@oh-local --scope user --keep-data
   ```

3. If you also want to stop the dashboard, run:

   ```sh
   ~/.local/share/o-harness/bin/oh service-uninstall
   ```

   This preserves all data. There is no combined factory-reset command; do not delete the
   OH data directory to test plugin installation.

4. Reinstall from the same local marketplace in each plugin manager, or run:

   ```sh
   codex plugin add o-harness@personal
   claude plugin install o-harness@oh-local --scope user
   ```

   These are example marketplace names, not public registry identifiers. Use the names
   shown by your local manager. Codex's default personal marketplace is discovered from
   `~/.agents/plugins/marketplace.json`; it does not need a separate marketplace-add step.

5. For the same installed version, the retained core is ready. If it is a new package,
   run its installed `scripts/oh setup` command first. Restart the dashboard when wanted:

   ```sh
   ~/.local/share/o-harness/bin/oh service-install
   ```

6. Start a fresh agent conversation in a registered checkout. Confirm the OH skills are
   listed. Ordinary prose should leave OH inactive; invoke **propose**, **design** or
   **deliver** explicitly to use it. The host may display the `o-harness:` namespace.
   Read any native host trust prompt rather than treating installation as task approval.

## A genuinely new installation

The [usage guide](usage.md#first-setup) describes building a separate package for each host,
installing through its user-level plugin manager, running explicit setup, trusting the
subscription-authenticated host binary and registering a checkout's external checks.
A maintainer currently needs to supply a local marketplace pointing at that built package;
installing the source `plugins/o-harness` directory directly is insufficient because it
has not yet bundled the core. There is no supported one-command public install today.

## Versions, upgrades and releases

OH records two different identifiers:

- **Package version**, currently `0.2.0`, is the human-facing plugin manifest version.
  A public release should update both host manifests together. There is no automated
  release or version-bumping policy yet.
- **Core revision** identifies the exact Git commit used by a run. Uncommitted development
  builds also include a tree digest. Installing a new commit creates a separate immutable
  core, even if the human-facing package version has not changed.

You can make many commits and PRs before publishing a release. To try an improvement
locally, build and install a reviewed package from that revision, then run its explicit
setup. Use the native manager's update/reinstall flow so its cached plugin is refreshed;
Codex local development can use a cachebuster suffix without creating a public release.
Never patch an installed immutable core in place.

New runs use the selected core. Unfinished runs retain their recorded revision and limits;
keep that version until they finish. Dashboard upgrades require `service-install` again
because the service points to an exact installed core. Editing the source checkout alone
updates neither the installed plugin nor the running dashboard.

The target public experience is an intentional versioned release with installable packages,
release notes, and native update support. That distribution work remains in issue 2.
