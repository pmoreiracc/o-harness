---
name: review
description: Independently inspect a specified subject, or challenge a completed unpublished Deliver task again.
---
Read `workflows/runtime.md` once and use its host execution, progress and decision protocol.

Resolve the person's requested subject using targeted reads when needed. Native selectors:
`changes` (all current uncommitted work), `tree` (current code), `paths <relative paths>`,
`commit <ref>`, `range <base> <head>`, or `task <id>` (completed unpublished Deliver work).
Append `--feedback-only` when the person explicitly requests feedback without a repair offer.
Use one argument per path in Codex; quote paths containing spaces in Claude's shell.
Ask only when the intended subject is ambiguous.
Do not interpret a design number as a task number. A merged change is a commit/range review.

Call OH `review` with the selector (`arguments` in Codex; `review -- <selector>` in Claude).
The runtime retains the original human request and binds the subject before launching a fresh
reviewer. Do not create an implementation report, require a design document, run tests or
start implementation merely to obtain feedback. The runtime owns receipt validation.

Present the actual outcome, concrete findings, limits and readable report. A standalone
receipt is feedback about its exact subject, never a workflow round or completion approval.
A clean or feedback-only review ends here. Do not carry its finding history into later
standalone reviews unless the person explicitly requests that context.

When the result returns `prepare` and `review_source`, inspect the findings against current
code and prepare a bounded quick-fix task list through the existing `prepare` tool with
`review` set to that ID (Claude: `prepare --review <id> <manifest>`). Historical findings
may already be fixed: explain that and omit obsolete repairs. If none apply, end with the report.
When original edits or unreviewed commits are included, prepare one coherent repair task
covering that included change. Its full contents are checked and reviewed before commit;
do not split an existing uncommitted change across partially completed repair tasks.
Resolve genuine product choices in ordinary conversation before preparing the final scope.
Do not create roadmap/design documents or add a redesign classification.

The returned existing menu offers Approve fixes / Refine / Keep as feedback. Show the
scope and all original edits included in completion first. There is no preliminary repair
menu. Refine is ordinary text followed by a revised preview. Keep as feedback ends the
operation; do not retain an open repair series. Approval enters normal Deliver, including
implementer-owned affected checks, fresh review, reviewed commit and publication decision.

For `task <id>`, the runtime retains the existing delivery and allowances. A clean re-review
returns to its decision without a commit. Blocking findings enter the existing scoped repair
loop and produce a correction commit; no checked task or previous receipt is rewritten.
