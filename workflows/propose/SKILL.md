---
name: propose
description: Route one human idea to a project plan addition or bounded improvement with native approval and review.
---
Read `workflows/runtime.md` once through OH's resource entry. Apply its saved-work
entry and communication protocol before new work. For a matching unfinished run,
follow `workflows/recovery.md`; resume its saved phase instead of restarting these steps.
If the subject is missing, discover relevant saved work before asking for it.

## 1. Prepare the idea

Read `plans path`, resolve an undecided repo/private location once and show its actual
folder. Respect project policy; planning alone does not authorize product implementation.

Prepare one bounded routing task with `scope prepare <manifest.json> --workflow propose
--human <native-locator.json>` (Codex `scope_prepare`). That request authorizes analysis;
there is no extra approval merely to obtain a recommendation.

## 2. Recommend a route

Admit a fresh proposal agent (`analysis`) with the configured profile, bounded packet,
`prompts/propose.md` and `prompts/proposal-routing.md`. It examines actual plans and code,
then writes its preview/report externally, without modifying project planning documents.
Retain its original native result and show the understanding, recommended route, evidence,
complete additions and exact destinations. An improvement or unclear route can end here
with the actual recommendation/question; no unnecessary document or review is required.

## 3. Approve the actual additions

Before additions are written, prepare `decision-request approve-proposal --attempt ID`
for the retained analysis, then present its approve/refine/cancel question using
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
within existing authority and remaining review allowance.

Read `workflows/findings.md` for outside-scope tracking after review. Related new work remains a follow-up;
adding it to the proposal requires the same changed-preview approval as any other addition.
Tracking does not create product implementation authority or require a routing confirmation.

## 5. Complete and hand off

Complete only the exact reviewed candidate. Report the saved proposal, actual review
outcome and any unresolved product decision. Repository publication follows `workflows/publication.md`; private plans need no commit or PR.
