---
name: oh-design
description: Turn one supplied roadmap initiative into an actionable plan through specialist drafting and independent review when explicitly invoked as /oh-design.
argument-hint: "<roadmap-slug>"
disable-model-invocation: true
---
Before asking for missing arguments, follow the shared workflow's saved-work entry.
Show relevant unfinished work and ask once whether to resume it or select new work.
A supplied matching request continues the saved phase without a redundant question.

Load `workflows/design/SKILL.md` through OH's resource entry and follow it. Introduce
the planning agent's draft and the independent reviewer agent's challenge against
the project's requirements.

Resolve the absolute plugin launcher two levels above this skill: `scripts/oh`
(`scripts\oh.cmd` on native Windows). Keep OH configuration and evidence outside
consumer repositories. Discovery alone does not authorize setup or execution.

In Codex use the connected OH tools with the checkout's absolute `root`; read resources
with `resource`. In Claude use `<plugin>/scripts/oh --root <checkout> resource <path>`.
If the Codex connection is missing, report it with the `/mcp` recovery step; do not
bypass it with shell writes to OH state.
