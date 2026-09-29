---
name: oh-deliver
description: Deliver an approved design, propose a quick-fix task list for approval, or list ready work when explicitly invoked.
disable-model-invocation: true
---
Resolve the `scripts/oh` command at the plugin root, two levels above this skill directory (from PowerShell or cmd on Windows, use `scripts\oh.cmd` there). Use that absolute path; never create integration files in a product repository. If setup is missing, run the command with `setup` explicitly. Never install or start anything merely because this skill was discovered.

Read that workflow and follow it: in Codex, call the o-harness `resource` tool with `path` `workflows/deliver/SKILL.md` and the checkout's absolute path as `root`; in Claude, run `<plugin>/scripts/oh --root <project-root> resource workflows/deliver/SKILL.md`. Keep the coordinator small; the shared runner owns workers, checks, reviews, commits and batch boundaries. Do not recreate that loop in the parent conversation.
