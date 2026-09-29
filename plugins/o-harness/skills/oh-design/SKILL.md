---
name: oh-design
description: Write the reviewed design doc for one roadmap initiative, only when explicitly invoked as /oh-design <slug>.
argument-hint: "<roadmap-slug>"
disable-model-invocation: true
---
Resolve the `scripts/oh` command at the plugin root, two levels above this skill directory (from PowerShell or cmd on Windows, use `scripts\oh.cmd` there). Use that absolute path; never create integration files in a product repository. If setup is missing, run the command with `setup` explicitly. Never install or start anything merely because this skill was discovered.

Read that workflow and follow it: in Codex, call the o-harness `resource` tool with `path` `workflows/design/SKILL.md` and the checkout's absolute path as `root`; in Claude, run `<plugin>/scripts/oh --root <project-root> resource workflows/design/SKILL.md`. Keep the coordinator small; the shared runner owns workers, checks, reviews, commits and batch boundaries. Do not recreate that loop in the parent conversation.
