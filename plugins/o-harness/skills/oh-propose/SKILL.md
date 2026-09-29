---
name: oh-propose
description: Route one idea to a roadmap row, a task in an approved design, or an improvement, only when explicitly invoked as /oh-propose <idea>.
argument-hint: "<what you want to add>"
disable-model-invocation: true
---
Resolve the `scripts/oh` command at the plugin root, two levels above this skill directory (from PowerShell or cmd on Windows, use `scripts\oh.cmd` there). Use that absolute path; never create integration files in a product repository. If setup is missing, run the command with `setup` explicitly. Never install or start anything merely because this skill was discovered.

Read that workflow and follow it: in Codex, call the o-harness `resource` tool with `path` `workflows/propose/SKILL.md` and the checkout's absolute path as `root`; in Claude, run `<plugin>/scripts/oh --root <project-root> resource workflows/propose/SKILL.md`. Keep the coordinator small; the shared runner owns workers, checks, reviews, commits and batch boundaries. Do not recreate that loop in the parent conversation.

If Codex lists no o-harness tools, OH's tool server did not start: tell the person to type `/mcp` to see why, then start a new Codex session; don't run these OH commands from Codex's shell instead.
