---
name: oh-propose
description: Route one supplied idea to a roadmap row, an approved-design task or an improvement when explicitly invoked as /oh-propose.
argument-hint: "<what you want to add>"
---
Load `workflows/propose/SKILL.md` through OH's resource entry and follow it. Introduce
the proposal agent's routing work and the invariant reviewer agent’s review of any resulting documents.

Resolve the absolute plugin launcher two levels above this skill: `scripts/oh`
(`scripts\oh.cmd` on native Windows). Keep OH configuration and evidence outside
consumer repositories. Discovery alone does not authorize setup or execution.

In Codex use the connected OH tools with the checkout's absolute `root`; read resources
with `resource`. In Claude use `<plugin>/scripts/oh --root <checkout> resource <path>`.
If a connected OH tool fails, retry that same operation once before asking the person
to intervene. If the connection remains unavailable, report the actual error and a
host-supported recovery step; do not assume `/mcp` exists in the desktop app or bypass
the connection with shell writes to OH state.
