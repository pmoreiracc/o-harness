---
name: oh-start
description: Choose an OH workflow only when explicitly invoked.
---
Load `workflows/oh/SKILL.md` through OH's resource entry. Select the requested
workflow or ask one ordinary question when the intended work is missing. Follow its
native-agent workflow and report actual results.

Resolve the absolute plugin launcher two levels above this skill: `scripts/oh`
(`scripts\oh.cmd` on native Windows). Keep OH configuration and evidence outside
consumer repositories. Discovery alone does not authorize setup or execution.

In Codex use the connected OH tools with the checkout's absolute `root`; read resources
with `resource`. In Claude use `<plugin>/scripts/oh --root <checkout> resource <path>`.
If the Codex connection is missing, report it with the `/mcp` recovery step; do not
bypass it with shell writes to OH state.
