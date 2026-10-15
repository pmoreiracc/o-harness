---
name: oh-propose
description: Route one supplied idea to a roadmap row, an approved-design task or an improvement when explicitly invoked as /oh-propose.
argument-hint: "<what you want to add>"
disable-model-invocation: true
---
When no idea was supplied, ask what the person wants to propose and wait for the
answer. Do not invent an idea or create a waiting run merely to ask.

Load `workflows/propose/SKILL.md` through OH's resource entry and follow it. Introduce
the proposal agent's routing work and independent review of any resulting documents.

Resolve the absolute plugin launcher two levels above this skill: `scripts/oh`
(`scripts\oh.cmd` on native Windows). Keep OH configuration and evidence outside
consumer repositories. Discovery alone does not authorize setup or execution.

In Codex use the connected OH tools with the checkout's absolute `root`; read resources
with `resource`. In Claude use `<plugin>/scripts/oh --root <checkout> resource <path>`.
If the Codex connection is missing, report it with the `/mcp` recovery step; do not
bypass it with shell writes to OH state.
