---
name: deliver
description: Deliver approved design tasks or a bounded quick fix with fresh native agents and independent review.
---
Read `workflows/runtime.md` once through OH's resource entry. Apply its saved-work
entry and communication protocol before new work. For a matching unfinished run,
follow `workflows/recovery.md`; resume its saved phase instead of restarting these steps.
Use its shared recovery gate (Continue, Start fresh, Stop and take over), including
when old native transcripts are unavailable. Do not ask the person to repair OH state.
If the subject is missing, discover relevant saved work before asking for it.

## 1. Select the work

A number identifies a design, not a task. Name the actual task only after selection.
Interpret the requested work as follows:

- No arguments: first show relevant unfinished saved work. For matching work, read
  the recovery and decision references and prepare its Resume question before asking;
  never add a preliminary Resume question. Otherwise use `plans list`, show ready designs,
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

## 2. Bind the required scope approval

Read `workflows/decisions.md` before presenting scope. For a quick fix, Claude's
native plan viewer Accept is the one scope approval;
Codex uses a native question or direct human reply. Bind that actual acceptance with
`scope approve`. Revisions replace the unapproved preview and receive approval of the
new contents. Inspect original user edits and branch ownership; do not reset, stash,
rebase or switch branches to bypass a refusal. An explicit existing-PR correction
keeps that destination and original edits in scope rather than creating another PR.

## 3. Implement one task through its review loop

1. Admit and retain one assessment agent (`assessment`) for a newly selected task.
   Reuse its retained assessment for repairs; do not reassess to obtain another profile.
2. Admit a fresh implementation agent (`implementation`) using that admission's actual
   model and effort. Launch, bind and await it through the shared native protocol.
   It owns implementation, self-review, `candidate`, `verify` and scoped check repairs.
3. Retain its terminal result. If the candidate and checks are ready, admit a fresh
   invariant reviewer agent (`review`), bind it, await it and retain its complete report.
4. Repair blocking families and accompanying concerns within scope, preserving every
   finding. Concern-only outcomes use the person's fix/accept decision. Reverify changes
   and use a fresh reviewer within the remaining allowance. Read the new implementation
   admission on each repair; repeated families can escalate its profile.
5. Complete only the exact reviewed candidate through `complete`, then select the next
   externally pending task inside the finite batch. No parallel implementation or
   parent-authored completion. A completed design admits no further implementation.

Read `workflows/findings.md` for outside-scope tracking in repo and private designs; a follow-up note
never becomes an executable task in the current approved batch. Preserve a successful
review when retaining notes externally; an actual design edit needs checks and fresh review.

## 4. Continue or hand off

At a real batch/allowance/concern boundary ask the native human decision once. Continue
approved work automatically inside its scope; routine failures need repair, not a
Retry menu. After a completed batch, use the complete Continue / Open PR / Stop and take
over checkpoint from `workflows/decisions.md`, keeping all available returned options.
At an exhausted review window, prepare `decision-request grant-review` without
`--rounds` unless the person explicitly requested another count. Follow
`workflows/decisions.md`; publication follows `workflows/publication.md`.
Report the actual review outcome and checks before the commit or publication decision.
