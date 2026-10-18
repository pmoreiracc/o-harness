---
name: oh-deliver
description: Deliver design tasks or quick fixes, or list ready work through OH, only when explicitly invoked.
disable-model-invocation: true
---
Load `workflows/deliver/SKILL.md` through OH's resource entry and follow it.
A number selects a design, not a task. Check saved work before naming the actual
task. Introduce the implementation agent, affected checks and invariant reviewer
agent once the work is selected. A quick fix needs approval of its bounded scope.

Resolve the absolute plugin launcher two levels above this skill: `scripts/oh`
(`scripts\oh.cmd` on native Windows). Keep OH configuration and evidence outside
consumer repositories. Discovery alone does not authorize setup or execution.

In Codex use the connected OH tools with the checkout's absolute `root`; read resources
with `resource`. In Claude use `<plugin>/scripts/oh --root <checkout> resource <path>`.
If a connected OH tool fails, retry that same operation once before asking the person
to intervene. If the connection remains unavailable, report the actual error and a
host-supported recovery step; do not assume `/mcp` exists in the desktop app or bypass
the connection with shell writes to OH state.
