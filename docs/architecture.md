# Architecture

OH separates execution authority, host integration and derived observations.

| Directory | Responsibility |
|---|---|
| `runtime/oh/` | Python state machine, host adapters, verification, collection and HTTP service |
| `core/` | Extracted review/lifecycle mechanisms and their compatibility tests |
| `plugins/o-harness/` | Explicit host skills and narrow prompt translation; per-host packages share one core |
| `adapters/` | Retained compatibility fixtures and translation resources |
| `workflows/` | Neutral workflow instructions |
| `prompts/` | Shared independent review contract |
| `config/` | Defaults, invariants and extraction provenance |
| `dashboard/` | Local static interface; no build-time frontend dependency |
| `integrations/` | Test entrypoints and historical compatibility resources |
| `.codex/`, `.claude/`, `.agents/` | OH development host configuration only |

The coordinator prepares immutable scope. A native user transcript event authorizes it.
The runner persists a hash-chained journal, selects a bounded worker profile, verifies
inputs, admits an independent reviewer, and commits only the reviewed final tree.
Native commits seal their task review history, findings and resolutions with an
`OH-Evidence` digest. The PR summary is checked against every actual commit, parent and
tree; editing the summary or adding an unreviewed commit invalidates it.
Durable attempts retain failures. A restart recovers recorded transitions and never
creates a new grant. The optional design adapter renders its final lifecycle tree before
review and verifies that completion commits that exact result.

Subscription child execution removes API credential fallbacks and uses explicitly
trusted native host binaries. Workers cannot write OH state or Git administration paths;
the parent owns commits. Review/analysis hosts are read-only. Provider sandbox support
is a requirement, not a permission bypass.

Product repositories keep their business invariants, documents and normal tests. OH's
external registry binds canonical checkout/Git identities, configuration and verification
commands without creating consumer files or Git markers. Immutable installed revisions
own active runs. Plugin discovery is separate from explicit setup and workflow activation.

Pause/stop and finalization share a lock. Pause drains one step; stop cancels only the
runner's process group, retaining evidence before reporting completion. Resume validates
the retained tree and allowance. Propose/design artifacts use the same attempt/review
engine as implementation; the numbered-design adapter only parses and renders documents.

SQLite is rebuildable derived data, never approval authority. The collector uses durable
spooling, event identity deduplication and incremental transcript boundaries. Backup and
restore take an exclusive snapshot lock; active writers and readers hold shared locks.
The dashboard reads indexed tables and does not control runs.

One task executes at a time. Future parallelism needs ownership isolation, merge/review
coordination, resource limits and evidence attribution before enabling concurrent work.
See [issue 1](https://github.com/pmoreiracc/o-harness/issues/1). Additional hosts implement
explicit capability and subscription conformance contracts; they are not supported merely
because they can read a skill file ([issue 4](https://github.com/pmoreiracc/o-harness/issues/4)).
