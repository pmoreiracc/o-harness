---
name: oh-start
description: Choose an OH workflow only when explicitly invoked.
---
Load `workflows/oh/SKILL.md` through OH's resource entry. Select the requested
workflow after saved-work discovery; show unfinished work before asking for a missing
subject, and ask once whether to resume or choose different work. Follow its
native-agent workflow and report actual results.

Resolve the absolute plugin launcher two levels above this skill: `scripts/oh`
(`scripts\oh.cmd` on native Windows). Keep OH configuration and evidence outside
consumer repositories. Discovery alone does not authorize setup or execution.

In Codex use the connected OH tools with the checkout's absolute `root`; read resources
with `resource`. In Claude use `<plugin>/scripts/oh --root <checkout> resource <path>`.
If a connected OH tool fails, retry that same operation once before asking the person
to intervene. If the connection remains unavailable, report the actual error and a
host-supported recovery step; do not assume `/mcp` exists in the desktop app or bypass
the connection with shell writes to OH state.
