---
name: review
description: Independently inspect a specified subject and offer bounded repairs when requested.
---
Read `workflows/runtime.md` once through OH's resource entry. Apply its saved-work
entry and communication protocol before new work. For a matching unfinished run,
follow `workflows/recovery.md`; resume its saved phase instead of restarting these steps.
If the subject is missing, discover relevant saved work before asking for it.

Terminal feedback is a completed report. An explicit new review uses a fresh agent;
preserve underlying workflow work when selecting standalone feedback or returning to it.

## 1. Resolve the review subject

Resolve the person’s subject with targeted reads; ask only when it is ambiguous. Selectors are `changes`,
`tree`, `paths <relative paths>`, `commit <ref>`, `range <base> <head>` or
`task <id>` for completed unpublished delivery work. A design number is not a task
number. A merged
change is reviewed as a commit or range. Honor an explicit feedback-only request.

## 2. Bind, launch and retain

Call `review -- <selector...>` (Codex `review` with selector arguments) to bind that
subject, then admit a fresh invariant reviewer agent (`review`) with the configured profile and bounded
packet. Bind its native child identity, wait and retain its complete original report.
Do not require an author report or design document, run product tests or start repairs
merely to obtain feedback. The requested subject and project requirements determine
which evidence is needed.

## 3. Return the feedback

Present the actual outcome, concrete findings, evidence and limits with the readable
report. This standalone receipt is feedback about its exact subject, never a delivery
round, completion approval or repair authorization. Read `workflows/findings.md` for outside-scope follow-ups: preserve and surface findings, offer
context-appropriate tracking when useful, and never require routing just to return feedback.
A clean or feedback-only review ends here. Do not import old finding history into another standalone review unless
requested; preserve each original receipt independently.

## 4. Route requested repairs

For requested repairs, inspect findings against current code and propose only applicable
bounded fixes through ordinary Deliver scope preparation, naming the review source.
Explain obsolete findings and omit their repairs. Include original unreviewed edits or
commits as one coherent task when they will be completed with the fixes. Do not create
a roadmap/design document or redesign classification just to repair manual work.
Resolve real product choices in ordinary conversation before final scope approval.

Show the complete proposed repair scope and included original changes before the single
native quick-fix approval; the person can refine or keep the review as feedback instead.
No preliminary repair menu is needed. Approved repairs follow normal native delivery,
checks, fresh workflow review and exact-candidate completion. The feedback receipt itself
cannot authorize completion. Existing task corrections preserve prior history and spent
allowances; never rewrite an earlier receipt or relabel unreviewed work as OH-reviewed.

## Completed-task review

For `task <id>`, retain the saved delivery scope, task coverage and remaining review
allowance. If entry returns `resume_required`, ask once; after acceptance retry the
same task-review request with that answer's human locator. Do not start a second
review merely to move the existing review to a new session. Review the current exact
candidate without a new task grant. A clean result
returns to its previous decision without another commit. Blocking findings enter the
same task's scoped repair/review cycle and complete as a correction commit; preserve
earlier completion and publication history instead of rewriting the original receipt.
