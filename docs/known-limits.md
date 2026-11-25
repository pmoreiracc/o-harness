# Known limits

These are the current boundaries of OH v1.0, with the issue that tracks each one.

## Hosts and platforms

- **Native Windows is in preview.** Plugin setup and startup are checked on Linux, macOS and Windows for every release, and native Windows delivery has passed real runs. In Windows preview testing, Claude Code planning has needed assisted recovery after the first planning answer ([#229](https://github.com/pmoreiracc/o-harness/issues/229)). See [Windows](installation.md#windows) and the [Windows test status](windows-live-nightly.md).
- **In Codex, a stopped run's child agent can keep running.** When you press Stop, OH blocks the agent from running further tools and stops the commands OH started. Whether Codex also ends the child model is up to Codex, so the child may run until it finishes. This is an accepted host limitation ([#81](https://github.com/pmoreiracc/o-harness/issues/81), [openai/codex#55521](https://github.com/openai/codex/issues/55521)).
- **Downgrades need a fresh data folder.** Newer versions install an `oh` command that older versions can't replace. See [Older versions](installation.md#older-versions).

## Delivery and publication

- **CI handoff covers checks, not review threads.** After publishing, OH reports the GitHub checks and statuses for the published commit. Read the PR's review threads, including security-app comments, on GitHub ([#176](https://github.com/pmoreiracc/o-harness/issues/176)).
- **A delivery keeps the checks it started with.** If you change a project's checks during a delivery, that delivery continues with its original check configuration. Follow the recovery guidance OH gives when a saved check environment needs correcting ([#121](https://github.com/pmoreiracc/o-harness/issues/121)).
- **A design checkbox can stay unchecked after a task completes.** The saved delivery record and the reviewed commit are the source of truth. If you see this, compare them before editing the design, and add the case to [#199](https://github.com/pmoreiracc/o-harness/issues/199).
- **Progress updates vary by host.** OH reports each workflow step and relays agent activity when the host exposes it. Long tasks can have quiet stretches, and CI waits can repeat an unchanged status ([#102](https://github.com/pmoreiracc/o-harness/issues/102)).

## Dashboard

- Token and time figures depend on what the host reports. Missing values are shown as missing, not estimated ([#109](https://github.com/pmoreiracc/o-harness/issues/109)).
- New dashboard analysis is off in v1.0. Suggestions saved by earlier versions stay readable. See [Dashboard and data](analytics.md).
