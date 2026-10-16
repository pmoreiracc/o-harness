---
name: oh-resume
description: Continue saved OH work or its pending decision in this session, on either host, with existing allowances.
disable-model-invocation: true
---
Load `workflows/runtime.md` through OH's resource entry, then inspect `status --saved`
and `resume --run ID` facts (Codex `status` with `saved`, `resume` with `run`).
Discovery never changes the selected run. Select the requested saved work explicitly.
Continue the saved task or decision with its original scope, settings, findings and
remaining allowances. Confirm old native work is quiescent before a fresh agent starts;
never reuse a completed reviewer or renew allowances to switch hosts. Preserve useful
unfinished edits. Report the actual resumed work, not a new implementation introduction
when only a decision or publication remains.
Bind a requested ownership transfer with `resume --run ID --human <native-locator.json>`
(Codex `resume` with its human locator); a factual status read alone grants nothing.

Resolve the absolute plugin launcher two levels above this skill: `scripts/oh`
(`scripts\oh.cmd` on native Windows). Keep OH configuration and evidence outside
consumer repositories. Discovery alone does not authorize setup or execution.

In Codex use the connected OH tools with the checkout's absolute `root`; read resources
with `resource`. In Claude use `<plugin>/scripts/oh --root <checkout> resource <path>`.
If the Codex connection is missing, report it with the `/mcp` recovery step; do not
bypass it with shell writes to OH state.
