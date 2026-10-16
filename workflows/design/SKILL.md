---
name: design
description: Draft and independently review one roadmap initiative's project plan and acceptance checks.
---
Read `workflows/runtime.md` once through OH's resource entry and apply its saved-work
entry before preparing scope or asking for an initiative. Resume a matching saved
draft or decision. With no subject, show unfinished Design work and ask once; only
when none exists ask which initiative to design. `plans list` may help.
Read `plans path`, resolve an undecided repo/private location once and show its actual
folder. Respect project policy; OH adds no mandatory ADR process.

Prepare one bounded planning task for the requested initiative with `scope prepare
<manifest.json> --workflow design --human <native-locator.json>` (Codex `scope_prepare`).
Include `design: "<initiative-slug>"` in the manifest so the saved scope identifies
its initiative. The native request authorizes drafting directly; do not add a scope-approval question.
Keep project requirements, ordered tasks, dependencies and acceptance checks in the
plan; keep difficulty/model/effort in external execution evidence.

Admit a fresh analysis agent with the configured model and effort, the bounded packet
and `prompts/design.md`. It reads the initiative's contracts, writes the actual draft
and required roadmap/log links, then validates documents with `plans check` and the
candidate's `verify`. It does not run product tests or decide open product questions.
Preserve direct human refinements when revising an existing plan; do not regenerate
someone's edited prose merely to fit an author report schema.

Retain the original result and independently review the actual candidate with a fresh
reviewer. Repair blocking families and concerns together when blockers exist; native
human choices handle concern-only outcomes and outside scope. A consequential product
question names the decision required and its effect instead of silently choosing.

Repository designs need human merge of the reviewed design PR to become approved.
Private designs need native acceptance of their reviewed contents: show the complete
artifact, ask approve/refine/cancel and bind the answer with `decision approve-private`.
Refinement returns to scoped authoring, document checks and a fresh review. Accepting
a proposed decision document does not decide its underlying product question.

Use `complete` only for the exact reviewed candidate and retained approval required
by its location. Private completion needs no commit, PR or extra Stop question. Give
the artifact path, actual review result and Deliver command. Repository publication
uses the shared human publication decision and existing-PR reconciliation.
