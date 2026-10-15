---
name: oh-update
description: Update OH to the latest release and report the previous and installed versions, or that it is up to date.
---
Resolve the plugin root two levels above this skill directory. Run its `scripts/oh` with `update` in the shell now; on Windows use `scripts\oh.cmd`. Use the absolute plugin path. If the user selected a host, append `--host codex` or `--host claude`; otherwise update both installed hosts.

The update writes user-level host settings and plugin files outside the checkout. Use the host's normal permission mechanism for those writes; if the sandbox denies access, retry this same command with the required execution permission. Keep the update inside this session.

Report the command's actual per-host `from -> to` or `up to date` results. If it fails, report that result and its concrete next step. Include the new-session instruction only when the command reports an update.
