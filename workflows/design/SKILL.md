---
name: design
description: Design one roadmap initiative with project requirements, ordered tasks and acceptance checks.
---
Read `workflows/runtime.md` once through the same OH resource entry and follow its shared execution protocol.

Without an initiative slug, ask which roadmap initiative to design and end the turn. `plans list`
can help when storage is configured, but is not required before asking. Do not select a slug
or start a waiting run on the person's behalf.

Use `plans path` and resolve an undecided storage preference once: repository or private plans.
Save their choice and show the actual path. Project documents contain project requirements,
ordered tasks, dependencies and acceptance checks; keep harness difficulty/model/effort out.

Introduce how a planning agent drafts the document and a fresh independent reviewer agent
challenges its approach, tasks and assumptions against the project. Call `run`. OH owns the
branch, numbering, links, document validation, review, repairs and commits. If another checkout
holds the required base branch, use the specific remedy returned by OH.

Repository designs are approved through human merge of their PR. Private designs are presented
for approval after review, bound to their exact contents. For `approval_checkpoint`, show the
plan path, task count and summary, then the returned question. Refine preserves the human's
instructions; editing an existing private design goes to review without rewriting their prose.
Approving a proposed decision document does not decide the underlying product question.

For completion, report the document, its summary and actual review result. An unresolved product
decision names what the person must decide. A completed private design needs no commit, PR or
extra Stop choice; give its path and Deliver command. Follow the shared protocol for publication
of repository plans and all other returned decisions.
