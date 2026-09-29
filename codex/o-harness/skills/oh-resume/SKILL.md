---
name: oh-resume
description: Resume the same paused OH run with its existing allowances.
---
Resolve the `scripts/oh` command at the plugin root, two levels above this skill directory (from PowerShell or cmd on Windows, use `scripts\oh.cmd` there). Use that absolute path; never create integration files in a product repository. If setup is missing, run the command with `setup` explicitly. Never install or start anything merely because this skill was discovered.

In Codex, call the o-harness `resume` tool with the checkout's absolute path as `root`; in Claude, run `<plugin>/scripts/oh --root <project-root> resume`. Report the actual run and status. PAUSING and STOPPING are pending states, not completion. Resume never renews allowances. If the host is busy and cannot dispatch this skill, the user can run this same command directly in a terminal.

If Codex lists no o-harness tools, OH's tool server did not start: tell the person to type `/mcp` to see why, then start a new Codex session; don't run these OH commands from Codex's shell instead.
