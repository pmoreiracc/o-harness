---
name: propose
description: Route one human idea to a project plan addition or bounded improvement with native approval and review.
---
Read `workflows/runtime.md` once through OH's resource entry. Apply its saved-work
entry and communication protocol before new work. For a matching unfinished run,
follow `workflows/recovery.md`; resume its saved phase instead of restarting these steps.
If the subject is missing, discover relevant saved work before asking for it.

## 1. Prepare the idea

Read `workflows/entry.md` before current plan/readiness claims or branch selection.
Reconcile the relevant saved/local/origin evidence before judging existing work.
For a new repository proposal, choose its intended execution branch through the
`workspace` save/switch/restore path before preparing scope, using the initiating
request. Prepare with `keep_checkout: true` / `--keep-checkout`; later approved additions
stay on that bound branch. Read-only inspection and private artifacts need no unrelated
branch change. Do not move an already bound proposal to another branch after approval.

Read `plans path`. If the repo/private location is undecided, call Claude
`AskUserQuestion` or Codex Default mode `functions.request_user_input_async` once.
Show the actual folder for the selected location. Respect project policy.

Prepare one bounded routing task with `scope prepare <manifest.json> --workflow propose
--human <native-locator.json>` (Codex `scope_prepare`). That request authorizes analysis;
there is no extra approval merely to obtain a recommendation.

## 2. Recommend a route

Admit a fresh proposal agent (`analysis`) with the configured profile, bounded packet,
`prompts/propose.md` and `prompts/proposal-routing.md`. It examines actual plans and code,
then writes its preview/report externally, without modifying project planning documents.
Require a structurally valid prospective preview before asking for approval, using the
existing checker on an external temporary copy as described in `prompts/propose.md`.
Retain its original native result and show the understanding, recommended route, evidence,
complete additions and exact destinations. An improvement or unclear route can end here
with the actual recommendation/question; no unnecessary document or review is required.

## 3. Approve the actual additions

Before additions are written, prepare `decision-request approve-proposal --attempt ID`
for the retained analysis. Summarize the proposed changes and post the supplied Markdown review link in chat before opening the menu. Then call Claude `AskUserQuestion` or Codex Default mode
`functions.request_user_input_async` with its approve/refine/cancel choices using
`workflows/decisions.md`. Bind approval of the latest analysis report with `decision
approve-proposal` and its actual native human locator. Refinement revises the unapproved
proposal; neither permission to analyze nor an author report approves the additions.

## 4. Apply, check and independently review

After approval, admit a fresh proposal agent (`analysis`) to apply exactly those additions with
ordinary tools, safe numbering/links and `plans check`. It prepares the candidate and
verifies documents without product tests. Retain its result, then admit a fresh
invariant reviewer agent to challenge routing, dependencies, duplication and requirements.
If review requires a different route or materially different additions, show the changed
preview and obtain approval before applying it. Repair other scoped document failures
within existing authority and remaining review allowance. Syntax-only corrections
that preserve the accepted semantic additions do not need another approval; changed
route, content, dependencies or destinations do.

Read `workflows/findings.md` for outside-scope tracking after review. Related new work remains a follow-up;
adding it to the proposal requires the same changed-preview approval as any other addition.
Tracking does not create product implementation authority or require a routing confirmation.

## 5. Complete and hand off

Complete only the exact reviewed candidate. Report the saved proposal, actual review
outcome and any unresolved product decision. Repository publication follows `workflows/publication.md`; private plans need no commit or PR.
