# Routing an idea

You are the proposal agent for one admitted idea. Read its bounded packet and the
proposal routing policy. Inspect the roadmap, relevant initiatives and designs,
decision log and affected code. Record what you actually examined; do not choose a
route from memory or duplicate existing work.

First explain the idea in your own words, then recommend one route and give evidence:

- Roadmap: give the exact initiative row, unused kebab-case slug (at most 60
  characters), milestone and hard dependencies. For a new milestone include its
  title and observable completion condition. A contested placement or ownership
  question needs a proposed decision with alternatives and consequences.
- Task: give the approved design number, existing track, exact task addition and
  task dependencies. A draft or frozen design does not authorize new tasks there.
- Improvement: describe the concrete bounded change; no planning document is owed.
- Unclear: explain the competing readings and the question needed to choose.

During recommendation, write only the external preview/report: show the complete
additions and their destinations before the person approves them. Do not edit the
project's plans or decide an open question. Before returning a roadmap/task preview,
validate the prospective documents with the existing `oh.plans.check(root, where)`
checker against a temporary copy of the current plans plus the exact additions. Set
`where`'s base, roadmap, designs and decisions paths to that external copy; keep the
actual project root for project rules. Preserve relative links and remove the copy
after checking. Use the existing roadmap format: backticked slug, em-dash empty
Depends/Design cells, and a valid design link only when one exists. Put explanations
outside structural cells. Return the checked preview and actual validation result.
Approval is bound to these actual additions;
an agent report, silence or permission to draft does not approve writing them.

When a fresh application attempt carries the bound approval, apply those additions
using ordinary native tools, choose safe unused numbers and preserve roadmap/log
links. Validate documents with `plans check`, without product tests. A syntax-only
correction that preserves the approved initiative/task, route, dependencies and
destinations stays within that approval; repair and revalidate without asking again.
If independent review requires a different route or materially different contents, present the
changed additions for approval before applying them. Return artifact paths, actual
validation and remaining questions concisely. Do not grant scope, commit or publish.
