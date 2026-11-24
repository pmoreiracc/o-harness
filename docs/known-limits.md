# Known limits

## Hosts and installation

- **Windows native workflows are in preview.** The release checks plugin setup and startup on Linux, macOS and Windows. Native Windows coverage includes successful delivery and external-merge trials. Earlier Windows catalog runs recorded planning and CI-repair gaps. See the [Windows native test status](windows-live-nightly.md) and [installation guide](installation.md#windows).
- **Codex hook trust is per definition.** After an update, use `/hooks` in a fresh Codex terminal session to review changed OH hook definitions. This can also apply to timeout-only changes. [Update guide](installation.md#update)
- **Updates move forward.** Finish or cancel active work before changing builds. Older versions whose launcher cannot replace the current one require a fresh OH data folder. Keep the existing OH data if it contains work you may need. [Upgrade and rollback details](installation.md#update)

## Delivery and publication

- **A design checkbox can lag reviewed completion.** This was observed when the author skipped candidate preparation. The saved delivery record and reviewed commit establish what completed. If you see unchecked progress after completion, compare the saved task and reviewed commit before acting on the design document, and report the recurrence. This issue is deferred. [#199](https://github.com/pmoreiracc/o-harness/issues/199)
- **Progress detail varies by host and task.** OH reports workflow transitions and can relay intermediate author activity when the host makes it available. Long work can have quiet intervals. Some CI waits can repeat an unchanged status. [#102](https://github.com/pmoreiracc/o-harness/issues/102)
- **Codex Stop can leave a native child running.** OH revokes the worker's authority and settles commands it owns. Whether Codex also terminates the child model depends on the host. [#81](https://github.com/pmoreiracc/o-harness/issues/81)
- **GitHub checks and review threads are separate.** The CI handoff reports checks and statuses for the published head. Inspect current GitHub review threads separately, including security-app feedback. [#176](https://github.com/pmoreiracc/o-harness/issues/176)
- **OH preserves the check configuration saved with a delivery.** Editing project settings can leave an in-progress delivery using its original check configuration. Use the current recovery guidance when a saved check environment needs correction. [#121](https://github.com/pmoreiracc/o-harness/issues/121)

## Dashboard

Token and timing measurements depend on host observations. Expect partial or unavailable values when evidence is missing. Previously saved suggestions remain readable and generation of new analysis is unavailable. [Dashboard guide](analytics.md) · [Measurement coverage](https://github.com/pmoreiracc/o-harness/issues/109)
