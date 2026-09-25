# Contributing

OH uses short-lived branches from `main`, independent review and human-merged pull
requests. Merged remote branches are deleted. There is no `develop` branch and no
mandatory ADR system. Discuss larger direction in issues; put useful explanations beside
the implementation or in the human docs. Ordinary fixes should stay ordinary.

1. Agree on the scope and create a `codex/` branch (or the host's requested branch name).
2. Read `config/invariants.json` and the affected code. Implement the smallest complete
   change. Add tests for concrete behavior or regressions, not prose or internal layout.
3. Run `./oh verify origin/main`. For focused work, `bash integrations/test.sh native`
   and `bash integrations/test.sh syntax` are the fast checks; affected core/adapter changes
   also need their selected compatibility suites. CI runs the full matrix without models.
4. Obtain a fresh independent invariant review with an immutable admission identifying the
   exact tree, parent, task, settings and prior dispositions. Apply every review lens from
   `prompts/invariant-reviewer.md`. Fix blockers and review changed behavior again within
   the authorized window. Retain findings; do not edit reviewer evidence to manufacture clean.
5. Open one PR describing the behavior, verification and remaining limits. A human merges.

Tests use temporary consumer repositories and synthetic model responses. Live subscription
conformance is separate and only appropriate when changing host execution boundaries;
it is not needed for every documentation edit. Never use the real product as a fixture.

New backlog work belongs in [GitHub Issues](https://github.com/pmoreiracc/o-harness/issues).
Do not revive the old embedded backlog file. Human documentation follows verified behavior;
keep claims as narrow as the evidence supports. Preserve receipts when cleaning a worktree.
