---
name: oh-resume
description: Continue saved OH work or its pending decision in this session, on either host, with existing allowances.
---
Load `workflows/runtime.md` through OH's resource entry, then inspect `status --saved`
and `resume --run ID` facts (Codex `status` with `saved`, `resume` with `run`).
Discovery never changes the selected run. Show the requested saved subject, branch,
next step and remaining allowance. Always ask the shared Resume question once and
wait; this invocation alone does not answer it. After acceptance, continue the saved task or decision with its original scope, settings, findings and
remaining allowances. Confirm old native work is quiescent before a fresh agent starts;
never reuse a completed reviewer or renew allowances to switch hosts. Preserve useful
unfinished edits. Report the actual resumed work, not a new implementation introduction
when only a decision or publication remains.
Bind the requested continuation with `resume --run ID --human <native-locator.json>`
(Codex `resume` with its human locator); a factual status read alone grants nothing.
The old conversation may remain open. Require no prior Stop/Pause when no attempt or
check is executing, even if legacy saved status still says running. After continuation,
only the current coordinator launches further OH operations; keep earlier attempts
bound to their original native parents. Await any executing native check and retry
the same still-valid continuation without another question.

Resolve the absolute plugin launcher two levels above this skill: `scripts/oh`
(`scripts\oh.cmd` on native Windows). Keep OH configuration and evidence outside
consumer repositories. Discovery alone does not authorize setup or execution.

In Codex use the connected OH tools with the checkout's absolute `root`; read resources
with `resource`. In Claude use `<plugin>/scripts/oh --root <checkout> resource <path>`.
If a connected OH tool fails, retry that same operation once before asking the person
to intervene. If the connection remains unavailable, report the actual error and a
host-supported recovery step; do not assume `/mcp` exists in the desktop app or bypass
the connection with shell writes to OH state.
