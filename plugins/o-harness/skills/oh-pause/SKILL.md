---
name: oh-pause
description: Request a cooperative pause of the current OH run.
disable-model-invocation: true
---
Load `workflows/runtime.md` through OH's resource entry. Request a cooperative pause:
let the current native agent or check finish, retain its actual result, then start no
next phase. Preserve scope, work, findings and consumed allowances. Report whether
pausing is pending or complete; do not describe a still-running agent as paused.
Record the actual human request with `decision pause <native-locator.json>`
(Codex `decision`, kind `pause`).

A later matching work command discovers the saved work in a new native conversation.
Continue only after its actual human Resume answer. This control is optional, never a prerequisite for that continuation;
discovery alone does not lift it.

Resolve the absolute plugin launcher two levels above this skill: `scripts/oh`
(`scripts\oh.cmd` on native Windows). Keep OH configuration and evidence outside
consumer repositories. Discovery alone does not authorize setup or execution.

In Codex use the connected OH tools with the checkout's absolute `root`; read resources
with `resource`. In Claude use `<plugin>/scripts/oh --root <checkout> resource <path>`.
If the Codex connection is missing, report it with the `/mcp` recovery step; do not
bypass it with shell writes to OH state.
