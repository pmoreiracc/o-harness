---
name: deliver
description: Deliver approved design tasks or a bounded quick fix with fresh native agents and independent review.
---
Read `workflows/runtime.md` once through OH's resource entry. Follow its native
delegation, evidence, decision and publication rules. Inspect saved facts first;
never select an unrelated active task merely because one exists. Always ask once
whether to resume selected unfinished work, even with a supplied design number or
matching quick fix. Bind the answer before continuing; do not repeat that choice
inside the accepted workflow or while retrying a routine recoverable operation.

A number identifies a design, not a task. Name the actual task only after selection.
Interpret the requested work as follows:

- No arguments: first show relevant unfinished saved work and ask once whether to
  resume it or choose different work. Otherwise use `plans list`, show ready designs,
  unavailable reasons and limits, and ask which design or quick fix the person wants.
  The empty invocation itself grants no continuation authority.
- Approved design number and optional track: use `scope prepare --doc NNNN
  [--track TRACK] --human <native-locator.json>` (Codex `scope_prepare`). The helper
  validates approval and selects the parsed tasks. Do not rebuild them as an arbitrary
  manifest or ask for another trigger. Missing track/selection needs one ordinary
  question; preserve the answer.
- A bounded change in prose: first compare saved quick-fix scope and reports with
  the requested outcome; offer to resume the same work without requiring identical wording.
  For genuinely new work, inspect the relevant code and correct base, then prepare
  an external manifest of ordered tasks with `id`, `title`, `instructions` and optional
  `needs`. Preserve included original unreviewed edits in one coherent task; do not
  split an existing dirty change across partially completed repair tasks. Call
  `scope prepare <manifest.json>` and present its actual scope preview and finite
  task/review limits. Difficulty and model selection stay outside that manifest.
- Existing prepared or interrupted work: use the matching retained scope and remaining
  allowance through `resume`; never convert a preparation ID or agent text into a
  human approval. A complete saved batch proceeds to its actual decision/publication.

For a quick fix, Claude's native plan viewer Accept is the one scope approval;
Codex uses a native question or direct human reply. Bind that actual acceptance with
`scope approve`. Revisions replace the unapproved preview and receive approval of the
new contents. Inspect original user edits and branch ownership; do not reset, stash,
rebase or switch branches to bypass a refusal. An explicit existing-PR correction
keeps that destination and original edits in scope rather than creating another PR.

For each admitted task, use a fresh assessment agent and the resulting configured
implementation profile. The implementation agent owns self-review, candidate preparation,
checks and repairs. After retaining its native result, admit a fresh independent
reviewer. Repair blockers within scope, preserving every finding and disposition;
repeat review only when ready and within the remaining allowance. Complete only the
exact reviewed candidate through `complete`, then select the next externally pending
task within the finite batch. No parallel implementation or parent-authored completion.

At a real batch/allowance/finding boundary ask the native human decision once. Continue
approved work automatically inside its scope; routine failures need repair, not a
Retry menu. A completed design admits no further implementation. Report the actual
review outcome and checks before the commit or publication decision.
