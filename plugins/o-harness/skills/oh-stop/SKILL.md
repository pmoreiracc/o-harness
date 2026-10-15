---
name: oh-stop
description: Cancel and end the current OH run, preserving its work and evidence.
disable-model-invocation: true
---
Load `workflows/runtime.md` through OH's resource entry. Stop the current run through
the host's native cancellation tools for its known active agents and commands, then
record the direct human stop decision. Start no later check, review or completion.
Retain completed results, attempts and edits. Report stopped only after native work is
confirmed cancelled; otherwise name the remaining work and the native action needed.
Never substitute an OH process supervisor or claim that interrupting the parent alone
establishes child cancellation.
After retaining terminal cancellation/results, record `decision stop
<native-locator.json>` (Codex `decision`, kind `stop`) from the person's actual request.

Resolve the absolute plugin launcher two levels above this skill: `scripts/oh`
(`scripts\oh.cmd` on native Windows). Keep OH configuration and evidence outside
consumer repositories. Discovery alone does not authorize setup or execution.

In Codex use the connected OH tools with the checkout's absolute `root`; read resources
with `resource`. In Claude use `<plugin>/scripts/oh --root <checkout> resource <path>`.
If the Codex connection is missing, report it with the `/mcp` recovery step; do not
bypass it with shell writes to OH state.
