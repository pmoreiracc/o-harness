---
name: oh-pause
description: Request a cooperative pause of the current OH run.
disable-model-invocation: true
---
Resolve the `scripts/oh` command at the plugin root, two levels above this skill directory (from PowerShell or cmd on Windows, use `scripts\oh.cmd` there). Use that absolute path; never create integration files in a product repository. If setup is missing, run the command with `setup` explicitly. Never install or start anything merely because this skill was discovered.

In Codex, call the o-harness `pause` tool with the checkout's absolute path as `root`; in Claude, run `<plugin>/scripts/oh --root <project-root> pause`. Report the actual run and status. PAUSING and STOPPING are pending states, not completion. Resume never renews allowances. If the host is busy and cannot dispatch this skill, the user can run this same command directly in a terminal.
