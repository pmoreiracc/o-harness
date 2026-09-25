# Contributing

OH uses short-lived branches from `main`, independent review and human-merged pull
requests. Merged remote branches are deleted. There is no `develop` branch and no
mandatory ADR system. Discuss larger direction in issues; put useful explanations beside
the implementation or in the human docs. Ordinary fixes should stay ordinary.

1. For a bug, open an issue with the OH revision, host/OS, a minimal reproduction,
   expected/actual behavior, and relevant redacted errors. Never post credentials, raw
   conversations, or your complete local state. For a larger feature, discuss the problem
   and proposed scope in an issue before building it; small fixes can go straight to a PR.
2. Once the repository is public, fork it if you do not have write access. Clone your fork,
   add this repository as `upstream`, and create a branch from current `upstream/main`.
   Maintainers can branch directly from `origin/main`. Use a `codex/` prefix for Codex work;
   otherwise use a short descriptive name. Link the issue in the PR when one exists.
3. Read `config/invariants.json` and the affected code. Implement the smallest complete
   change. Add tests for concrete behavior or regressions, not prose or internal layout.
4. Run `./oh verify origin/main` after registering this checkout and its external checks.
   With a fork, use `upstream/main` as the comparison base. For focused work, `bash integrations/test.sh native`
   and `bash integrations/test.sh syntax` are the fast checks; affected core/adapter changes
   also need their selected compatibility suites. CI runs the full matrix without models.
5. Obtain a fresh independent invariant review with an immutable admission identifying the
   exact tree, parent, task, settings and prior dispositions. Apply every review lens from
   `prompts/invariant-reviewer.md`. Fix blockers and review changed behavior again within
   the authorized window. Retain findings; do not edit reviewer evidence to manufacture clean.
6. Open one PR targeting this repository’s `main`, describing the behavior, verification and remaining limits. A human merges.

Tests use temporary consumer repositories and synthetic model responses. Live subscription
conformance is separate and only appropriate when changing host execution boundaries;
it is not needed for every documentation edit. Never use the real product as a fixture.

New backlog work belongs in [GitHub Issues](https://github.com/pmoreiracc/o-harness/issues).
Do not revive the old embedded backlog file. Human documentation follows verified behavior;
keep claims as narrow as the evidence supports. Preserve receipts when cleaning a worktree.

## Local development

You need Python 3.11+, Git, Node.js, Bash and jq. Tests do not require an AI subscription
or API key. From the repository root, these commands work without OH registration:

```sh
bash integrations/test.sh native
bash integrations/test.sh syntax
```

Run `guards`, `adapters`, `delivery` or `review` through the same script when their
behavior changes. The legacy delivery suite is slower; do not rerun it for a stylesheet
or copy change. Check dashboard changes in a browser at desktop and narrow widths,
including navigation, filters, empty states, task details and chart labels. CI currently
runs the complete matrix for every PR.

Using OH to develop OH is optional. The installed propose/design/deliver skills work in
this checkout too; register it with `--kind harness` and configure OH checks in its external
profile. Keep the installed stable core separate from the source you are editing. A source
edit does not silently upgrade your running agent or dashboard.

A contributor can submit a PR without buying an AI subscription. Maintainers are responsible
for completing the required independent invariant review before publication/merge; retain
its immutable local admission and findings rather than committing receipts to the repo.
The PR should explain the problem, resulting behavior, relevant checks and remaining limits.
Respond to review comments on that branch. Only maintainers merge; no ADR is required.

## Releases and public readiness

A commit is an exact source revision, not an automatic release. Group reviewed changes into
an intentional release when they are useful to distribute. See [installation and versions](docs/installation.md).
There is no automatic release pipeline yet. Do not create a release for every small edit.

The repository is currently private and has no open-source license grant. Before inviting
public contributions, the owner must select a license, publish installation artifacts and
establish a private security-reporting channel. Until then, contact the maintainer privately
about security defects; do not disclose secrets or exploit details in ordinary issues.
