---
name: design
description: Draft and independently review one roadmap initiative's project plan and acceptance checks.
---
Read `workflows/runtime.md` once through OH's resource entry. Apply its saved-work
entry and communication protocol before new work. For a matching unfinished run,
follow `workflows/recovery.md`; resume its saved phase instead of restarting these steps.
If the subject is missing, discover relevant saved work before asking for it.

## 1. Prepare the initiative

Read `workflows/entry.md` before current planning-readiness advice or branch selection.
Reconcile saved/local/origin differences while preserving useful local drafting work.
For a different branch, use its `workspace` save/switch/restore path with the initiating
request, then prepare with `keep_checkout: true` / `--keep-checkout`. This needs no
additional preservation approval and creates no parallel folder.

Read `plans path`. If the repo/private location is undecided, call Claude
`AskUserQuestion` or Codex Default mode `functions.request_user_input_async` once.
Show the actual folder for the selected location. Respect project policy.

Before dependent drafting, read the initiative and nearby roadmap prose, relevant
decision records and existing decision/Open lists, including an existing design's
Open section. Identify known questions whose answers would change the approach.
Discuss those choices with the person before drafting around them: explain the
context, viable alternatives, consequences and recommendation so the question is
answerable. Use ordinary discussion and actual free-text replies when short choices
are inadequate; follow `workflows/decisions.md` for the native question surface.
A request to discuss or review a proposed decision does not decide it, approve
scope, renew reviews or authorize publication. Honor the consumer's decision and
document conventions; OH requires no ADR or particular decision-log format.

Prepare one bounded planning task for the requested initiative with `scope prepare
<manifest.json> --workflow design --human <native-locator.json>` (Codex `scope_prepare`).
Include `design: "<initiative-slug>"` in the manifest so the saved scope identifies
its initiative. The native request authorizes drafting directly; do not add a scope-approval question.
Keep project requirements, ordered tasks, dependencies and acceptance checks in the
plan; keep difficulty/model/effort in external execution evidence.

## 2. Draft and check

Admit a fresh design agent (`analysis`) with the configured model and effort, the bounded packet
and `prompts/design.md`. It reads the initiative's contracts, writes the actual draft
and required roadmap/log links, then validates documents with `plans check`, prepares provisional content
with `candidate`, and runs `verify` on that candidate. It does not run product tests or decide open product questions.
Preserve direct human refinements when revising an existing plan; do not regenerate
someone's edited prose merely to fit an author report schema.

Research need not wait for every uncertainty to be settled. When evidence is needed
to frame an approach choice, bound the analysis to research or a proposed decision,
with alternatives and consequences, rather than a dependent design presented as ready.
If analysis discovers a new approach-changing question, retain its result and discuss
that choice before dependent drafting or spending a design review. Pass the person's
actual decisions and remaining unknowns to subsequent authors and reviewers. Task-level
questions may remain in Open and block their affected tasks; independent work may proceed.

## 3. Independently review

Retain the original result, then admit a fresh invariant reviewer agent (`review`)
for the actual candidate. Repair blocking families and concerns together when blockers exist; native
human choices handle concern-only outcomes. Read `workflows/findings.md` for outside-scope tracking;
related future tasks are notes until approved, and do not block this design merely for filing. A consequential product
question names the decision required and its effect instead of silently choosing.

## 4. Approve and complete

Repository designs need human merge of the reviewed design PR to become approved.
Private designs need native acceptance of their reviewed contents: show the complete
artifact, prepare `decision-request approve-private --attempt ID`, present its
question with Claude `AskUserQuestion` or Codex Default mode `functions.request_user_input_async`
using `workflows/decisions.md`. Bind acceptance with `decision approve-private`.
Refinement returns to scoped authoring, document checks and a fresh review. Accepting
a proposed decision document does not decide its underlying product question.

For a private design, `candidate` prepares the final `status: approved` bytes before
verification and review. That status is provisional: only a matching native human
approval record grants delivery authority. Preserve it during review/repair; if it
is reverted to draft, prepare the candidate again before verification and review.
Never rewrite accepted bytes at completion. Completion refuses a draft or missing
initiative-linked design; repair the candidate and obtain review and acceptance of
the corrected contents within the remaining allowance. An exhausted window needs
the existing human review-allowance decision, never an automatic renewal.

Use `complete` only for the exact reviewed candidate and retained approval required
by its location. Private completion needs no commit, PR or extra Stop question. Give
the artifact path, actual review result and Deliver command. Repository publication
follows `workflows/publication.md`.
