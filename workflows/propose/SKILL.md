---
name: propose
description: Route one human idea to the appropriate project plan or bounded improvement.
---
Read `workflows/runtime.md` once through the same OH resource entry and follow its shared execution protocol.

Without an idea, ask what the person would like to propose and end the turn before calling
`run` or choosing plan storage. The next reply supplies the idea; never invent it.

Use `plans path`. If storage is undecided, obtain the person's choice of repository plans
(approval through PRs) or private plans, then save that setting. Show the actual configured
folder; private plans default to `~/oh-plans/<project name>/`. Respect project-owned policies;
OH does not impose ADRs or run product tests while planning.

Introduce how a proposal agent finds where the idea belongs and shows exactly what would be
written. Saving and independent review follow human approval when documents are needed.
Call `run`; OH owns routing, previews, writing, document validation, review and commits.
Never write plan files or recreate those steps yourself.

For the returned approval preview, explain the understanding, recommended route and evidence.
The review copy contains exact additions, destinations and any proposed decision. Follow its
Approve / Refine / Cancel question. After approval call `run`. If review changes the proposed
route or contents, OH presents the changed proposal for approval. An improvement or unclear
idea can finish without writing a document or requiring review; report that actual result.

Use the shared protocol for progress, finding decisions and publication of repository plans.
