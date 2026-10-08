# Proposal routing policy

Apply the same classification to a proposed idea and to its independent review:

- **roadmap**: new work that needs several pull requests, has more than one defensible
  approach, or adds a new area of the product (new tables, a new bounded context).
- **task**: new behaviour inside an initiative whose design doc is `approved`.
  A `draft` design is not approved: route the idea as `unclear` and explain why.
- **improvement**: a change to behaviour that already exists, or obvious work that owes
  no document. OH writes no planning document for this route.
- **unclear**: the route cannot be chosen confidently, or the idea has two readings.
  Explain the readings and the question; never choose merely to keep moving.

A `frozen` design has shipped. New work there becomes a roadmap row when it needs several
pull requests or has more than one approach; otherwise it is an improvement.

Choose a milestone by what the work unblocks, not by when it is wanted. A shipped milestone
(✅) takes no new rows. Dependencies are only hard edges that genuinely have to come first.
Check for duplicate initiatives, tasks and capabilities before adding one.

If where the idea belongs is genuinely contested (placement, ownership, one area or two),
propose a decision record with the question, alternatives and consequences. Never decide
an open question from the project's decision log or silently pick a contested placement.
