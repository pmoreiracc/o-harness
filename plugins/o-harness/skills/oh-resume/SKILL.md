---
name: oh-resume
description: Continue saved OH work or its pending decision in this session, on either host, with existing allowances.
disable-model-invocation: true
---
Resolve the `scripts/oh` command at the plugin root, two levels above this skill directory (from PowerShell or cmd on Windows, use `scripts\oh.cmd` there). Use that absolute path; never create integration files in a product repository. If setup is missing, run the command with `setup` explicitly. Never install or start anything merely because this skill was discovered.

Read `workflows/runtime.md` through the `resource` tool (Claude: `<plugin>/scripts/oh resource workflows/runtime.md`) before execution. It defines automatic phase continuation, background execution and progress observation as well as decisions and publication.

In Codex, call the o-harness `resume` tool with the checkout's absolute path as `root`; in Claude, run `<plugin>/scripts/oh --root <project-root> resume` using the shared execution protocol. Describe what happened to the named task in one short sentence, for example “Resuming task 9 from its saved implementation.” Use the actual action and result. For PAUSING or STOPPING, say the action is in progress. Mention remaining allowances only when they affect the next step. Keep routing instructions and policy explanations out of routine status reports. If the host is busy and cannot dispatch this skill, the user can run this same command directly in a terminal.

The runtime can transfer saved work from another session or host in the same checkout. Follow
its current decision; do not restart implementation, renew allowances or invent a transfer gate.
An already-requested Stop/Pause may still be cleaning up; retry that pending command after a
short wait. A live run must first be stopped or paused before another session takes control.

If Codex lists no o-harness tools, OH's tool server did not start: tell the person to type `/mcp` to see why, then start a new Codex session; don't run these OH commands from Codex's shell instead.
