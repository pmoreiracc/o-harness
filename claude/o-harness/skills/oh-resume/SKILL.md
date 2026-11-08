---
name: oh-resume
description: Continue saved OH work or its pending decision in this session, on either host, with existing allowances.
disable-model-invocation: true
---
Load `workflows/runtime.md` through OH's resource entry, then inspect `status --saved`
and `resume --run ID` facts (Codex `status` with `saved`, `resume` with `run`).
Discovery never changes the selected run. Show the requested saved subject, branch,
next step and remaining allowance. Read `workflows/recovery.md` and `workflows/decisions.md`,
then prepare `decision-request recover --run ID` for delivery, or `decision-request resume --run ID`
for planning/review, before asking its returned question once. Delivery presents the
returned disclosure in chat before its short question. For a single option use only
the direct chat reply. The usual choices are Continue, Start fresh and Stop and take over.
Bind the selected action from its returned `actions`
map with `decision` and the same human locator. Call Claude `AskUserQuestion` or
Codex Default mode `functions.request_user_input_async` following the shared fallback rules.
Do not ask a preliminary Resume question. Wait; this invocation alone does not answer it.
After acceptance, load the selected workflow's procedure (`workflows/deliver/SKILL.md`,
`workflows/design/SKILL.md`, `workflows/propose/SKILL.md` or `workflows/review/SKILL.md`).
Enter its saved phase, not its initial scope setup. Follow its remaining steps through
the completion checkpoint; Resume is an entry into that workflow, not a separate ending.
Continue the saved task or decision with its original scope, settings, findings and
remaining allowances. Confirm old native work is quiescent before a fresh agent starts;
never reuse a completed reviewer or renew allowances to switch hosts. Preserve useful
unfinished edits. Report the actual resumed work, not a new implementation introduction
when only a decision or publication remains.
For the ordinary Resume question, bind continuation with `resume --run ID --human <native-locator.json>`
(Codex `resume` with its human locator). Stop and take over binds `decision stop`
using the same run and prepared decision. A factual status read alone grants nothing.
The old conversation may remain open. Require no prior Stop/Pause when no attempt or
check is executing, even if legacy saved status still says running. After continuation,
only the current coordinator launches further OH operations; keep earlier attempts
bound to their original native parents. Await any executing native check and retry
the same still-valid continuation without another question.

Resolve the absolute plugin launcher two levels above this skill: `scripts/oh`
(`scripts\oh.cmd` on native Windows). Keep OH configuration and evidence outside
consumer repositories. Discovery alone does not authorize setup or execution.

In Codex first call `mcp__o_harness__resource` with the checkout's absolute `root`
and `path: "workflows/runtime.md"`. In code mode, call
`text(await tools.mcp__o_harness__resource({root: "<checkout>", path: "workflows/runtime.md"}))`
inside `functions.exec`. In Claude use
`<plugin>/scripts/oh --root <checkout> resource workflows/runtime.md`.

OH's `resource` is a tool. MCP resource/template listings do not discover OH tools
or establish connection health. If tool lookup is needed, match `mcp__o_harness__`
in the available tool inventory. A failed text search is not a connection failure.
Retry a failed read once using the actual tool. For an uncertain state-changing call,
inspect its saved outcome before retrying with the same inputs. Preserve the current
request and approvals through recovery. Diagnose a connection failure from the actual
OH tool error; report an unavoidable host action only after supported recovery fails.
