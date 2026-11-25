# Architecture

OH is a set of host skills backed by a Python core of focused validation helpers. The host (Claude Code or Codex) runs every agent, tool call and question. OH decides what an agent may work on, records what happened, and checks the evidence before anything is committed or published. It has no agent runner, scheduler or permission broker of its own.

```text
 you ──► host chat ──► OH skill (coordinator)
                          │  launches one fresh native agent at a time
                          ▼
              assessment · implementation · review agents
                          │  call focused helpers (shell or MCP)
                          ▼
                 OH core (runtime/oh) ──► journals, evidence, settings
                                          outside the checkout
```

## Invariants

The rules in [`config/invariants.json`](../config/invariants.json) constrain every change to OH:

1. Only verified native host records of a person's decision grant task scope, publication or additional review allowance. Model output, silence, elapsed time, retries and restarts grant nothing.
2. A reviewer is independent of the author, starts with a fresh context and reviews its exact admitted subject. A detected change to the subject invalidates the review.
3. Durable workflow evidence is authoritative. Analytics and model prose are not.
4. Every attempt, including failed launches, is retained. Recovery is idempotent and never replenishes a grant.
5. Agents run only under first-party, subscription-authenticated host execution, with no API fallback.
6. Task contexts and coordinator handoffs stay bounded. Worker transcripts don't accumulate in the parent conversation.
7. Missing observations stay unknown, and estimates are labeled.
8. Telemetry makes no model calls and has no authority over delivery.
9. The shared core is host-neutral and writes no OH files or markers into a consumer checkout or its Git directory.
10. Tasks are implemented sequentially. Parallel implementation isn't enabled.

## Repository layout

| Path | Contents |
|---|---|
| `runtime/oh/` | Python core: scope, journals, native provenance, checks, review, completion, publication and analytics |
| `plugins/o-harness/` | Host plugin: skills, Claude agent definitions, hooks, launchers and the Codex MCP server entry |
| `workflows/` | Shared workflow instructions the skills load at run time |
| `prompts/` | Authoring and independent-review contracts for agents |
| `config/` | `defaults.json` and `invariants.json` |
| `dashboard/` | Static dashboard assets |
| `integrations/` | Packaging, test selection and development scripts |
| `.claude/`, `.codex/` | Configuration for developing OH itself |

## Packaging and install layout

`integrations/package.sh` builds one plugin per host. Each carries a copy of the shared core (`runtime`, `config`, `prompts`, `workflows`, `dashboard`, without tests) and a `revision.json` with its version. On first use, the launcher installs the core under `~/.local/share/o-harness/versions/<revision>/` and records the active runtime in `runtime/active.json`. Setup only moves to a higher version.

Both hosts share one data folder and one settings file. An update never rewrites historical evidence: original admissions, configuration snapshots, task grants and consumed allowances stay as recorded, and current helpers read them in place.

Host differences are applied at packaging time:

| | Claude Code | Codex |
|---|---|---|
| OH operations | Packaged launcher (`scripts/oh`), called through native shell tools | Plugin MCP server (`.mcp.json`) |
| Agent definitions | Named non-fork agents: `assessment`, `implementation`, `analysis`, `reviewer` | Native `default` agent role, no parent-history fork |
| Hooks on Windows | Run through `sh` (Git Bash) | `commandWindows` entries run through `cmd.exe` |

## Hooks

| Event | Purpose | Hosts |
|---|---|---|
| `UserPromptSubmit` | Records a native source locator for the person's message | Both |
| `PreToolUse` (`Agent`) | Agent launch guard: refuses a launch whose model, effort or fresh context differs from its admission | Both |
| `PreToolUse` | Blocks tools for revoked workers and reserves OH-owned shell commands | Both |
| `PostToolUse` | Records completed tool activity. On Claude, also records agent lifecycle evidence for `Agent`, `Task` and `SubagentHandback`. | Both |
| `PostToolUseFailure` | Records failed tool activity | Claude |
| `SubagentStart` | Tracks a started agent | Both |
| `SubagentStop` | Records finished OH agents | Claude |
| `Interrupt` | Records your request to stop work | Codex |

Hooks are trusted host integrations, not a security sandbox. No hook launches work, grants continuation, returns a permission approval or rewrites tool inputs. A hook is a wakeup: delayed evidence is retried through the same helpers, and a hook firing is never treated as proof that a child's execution has settled.

## Execution

The coordinating skill selects work and launches one fresh native agent at a time, with an explicit model and reasoning effort. Agent roles are `assessment`, `implementation`, `analysis` (planning) and `review`.

Before admitting the first attempt of a session, OH confirms the host's subscription sign-in: Codex must report `Logged in using ChatGPT`, and Claude must report a `claude.ai` first-party login. OH's own host CLI calls (version probes, the Codex model catalog and updates) run with API-key and base-URL variables removed from the environment.

For each delivery task:

1. An `assessment` agent rates the task `simple`, `standard` or `complex`. The rating is stored in OH's records, never in the design document, and is reused for repairs and resume.
2. An `implementation` agent builds the task with the selected profile, updates required documentation, runs the configured checks and prepares provisional task and lifecycle changes in the candidate.
3. A `review` agent examines that exact candidate against the immutable original scope, project contracts and prior findings.
4. `complete` validates the passing checks, the clean review and the current candidate, then records the task and commits the reviewed tree. Provisional checkboxes in the candidate are content, not completion authority.

A blocking finding family that repeats in two independent reviewer receipts moves the repair to the `complex` profile. A spent review allowance needs a verified human grant; retries and host switches don't renew it. The last task's review covers the accumulated branch.

`handoff.py` keeps each agent packet bounded, with references to immutable scope and evidence and a complete finding index. Original reports are retained without a mandatory prose schema. Author repair claims and independent reviewer closure stay distinguishable. Reviewer decisions are small structured records (verdict, finding severities, claims and stable family identifiers); the full receipt is retained but never interpreted as control data.

Claude child reports can arrive through a forwarded native handback or the completed `Agent` call's structured report. OH matches the report to the child's acknowledged terminal handback, keeps its full text, and recovers an omitted spawn-call ID only from a unique native launch result, checked against the admission.

## Authority and decisions

Skills ask questions through native host tools (Claude `AskUserQuestion`, Codex Default mode `functions.request_user_input_async`), or in ordinary chat when those aren't available. OH binds each consequential answer to what was shown:

- `decision-request` records the exact presented effect and current subject before the question.
- `decision` verifies the person's actual answer against that record, including an exact additional review count. It doesn't classify arbitrary prose as a grant.
- `scope prepare` and `scope approve` do the same for delivery scope. Claude quick fixes bind the plan viewer's **Accept**; Codex Plan mode binds **Implement**.

At a completed-batch checkpoint, the complete single-select menu and the chosen action bind to the prepared work boundary. Changed work, allowances or destination invalidate the decision; incomplete menus and a bare "Yes" grant nothing.

Repository designs are approved by a human merge. Private designs are approved by binding the reviewed contents.

Out-of-scope findings become durable follow-ups in retained reviews and the run index. They never extend approved tasks, and changing a reviewed document requires checks and a fresh review.

Native records are trusted under normal host permissions. Custom host software could imitate such records; this is an accepted limitation recorded in `config/invariants.json`.

## Checkout identity

Registration binds Git's canonical worktree root, private admin directory and common repository directory to an existing commit. Lookups resolve that commit; they don't pin `HEAD`, the remote URL, or filesystem device and inode numbers. A same-path restore with the saved commit is the same logical workspace; unrelated history can't reuse a registration. An empty repository gets its first commit at explicit workflow enrollment, before scope approval.

Legacy filesystem registrations upgrade in place under the registry lock, with an immutable backup under `registry/upgrades`. IDs, journals and spent allowances are unchanged, and migration grants no work. Unverifiable bindings keep their legacy settings until the checkout or its history is restored. `oh init --replace` is the only path to fresh authority at an old path.

## Git subjects

Candidate trees are built with a temporary index; status never refreshes the user's index. Git reads keep the user's configuration, including line endings, while dropping inherited selectors for another repository or index. Tracked files, non-ignored children, file/folder replacements, gitlinks and conflicts all remain part of the reviewed subject.

`workspace.py` parks work losslessly in one checkout: staged, unstaged and untracked changes go to a retained Git stash labelled `OH workspace` plus an external byte backup, with no unfinished commit. Branch switches refuse to overwrite ignored files. OH never pops or drops stashes, and it doesn't create worktrees, clones or repository copies for a task.

Delivery entry refreshes the base and checks ancestry before selecting pending tasks. The delivery recovery gate binds the current Git contents, affected paths, base commit and chosen effect (`resume`, `restart` or `stop`).

## Stop, cancellation and resume

Transport cancellation alone isn't a workflow Stop. `cancellation.py` records attributed native interruptions outside the checkout. Codex delivers them through its `Interrupt` hook; Claude Desktop's interruption record and spawn-linked `stoppedByUser` metadata establish interruption when nothing later supersedes them. Both hosts can recover from saved interruption records.

After a Stop, `PreToolUse` blocks the revoked worker. Every native shell command an OH agent runs is reserved by `PreToolUse` and executes through a literal `owned-command` invocation in the same shell tool and sandbox. Owned commands and configured checks run in process groups on POSIX and in a named job object on Windows (started suspended, terminated when its last handle closes), and execution waits until the kernel process identity is saved. Unknown or reused identities never authorize a signal.

Resume verifies the human answer, waits for owned command and check cleanup, then transfers ownership under the tool-admission lock. Old attempts stay revoked. Late reports remain attached to their original attempt and can't turn a cancelled outcome into success. A cleanup receipt doesn't claim the native model was terminated; that is host behavior (see [Known limits](known-limits.md)).

Ordinary native tools aren't mirrored in OH's execution ledger. The worker outcome and OH-owned commands and checks gate handoff. OH doesn't certify the lifetime of arbitrary external-service jobs. A killed wrapper or missing process evidence leaves cleanup unverified; OH records that uncertainty and refuses overlapping work.

## Publication

Publication permission binds the reviewed head and the destination. Reconciliation reuses an existing PR and never treats a failed lookup as permission to create a duplicate. `oh pr-summary` validates retained commit evidence and renders a factual starting point for the PR body: task summaries, verification, final review evidence and verdict, finding dispositions and the stop boundary. Full receipts stay in OH's external history. A compact publication identifier lets reconciliation recognize a description update; it grants nothing.

`oh ci-wait` follows the published head's checks to a result. A successful push isn't CI success, and a person merges.

## Analytics

`telemetry.py` indexes saved observations into a SQLite database. The index is derived data: it never grants work, makes no model calls, keeps missing measurements unknown and doesn't double-count subset counters. `oh rebuild` recreates it from saved events. The dashboard server (`server.py`) binds `127.0.0.1`, accepts only `localhost` and `127.0.0.1` hosts and same-origin requests, and serves read-only data. See [Dashboard and data](analytics.md).

## Module reference

| Module | Responsibility |
|---|---|
| `native.py` | Scope, attempt admission and binding, retention, candidate, checks, decisions, completion and standalone feedback helpers |
| `decisions.py` | Binds a native answer to a presented effect |
| `authority.py` | Native human and child provenance |
| `prepared.py` | Immutable bounded scope, prepared without granting it |
| `recovery.py` | Human-selected delivery recovery |
| `cancellation.py` | Native interruption records and owned command cleanup |
| `processes.py` | Bounded configured-check subprocesses |
| `verification.py`, `checks.py` | Project checks, reuse fingerprints and logs |
| `handoff.py` | Bounded evidence packets |
| `review.py`, `review_report.py` | Standalone review subjects and small review decisions |
| `retention.py` | Immutable report selection, shared by completion and recovery |
| `workflow.py` | Durable workflow facts and the historical journal reader |
| `registry.py` | Project profiles and checkout identities |
| `workspace.py` | Lossless branch parking in one checkout |
| `branches.py` | Base branch selection and history |
| `plans.py`, `design_parse.py` | Roadmaps, design docs and decision records |
| `publication.py`, `delivery_verify.py` | PR summaries and pre-publication verification |
| `config.py`, `profiles.py` | Settings, validation, migrations and portable profiles |
| `hosts.py`, `capabilities.py` | Host executables, subscription sign-in, model catalog |
| `installation.py`, `updater.py` | Packaging, shared-core install and `oh-update` |
| `mcp_server.py` | Codex MCP tools; it launches no model subprocesses and shows no questions |
| `telemetry.py`, `server.py`, `service.py` | Analytics index, dashboard server and auto-start service |
| `system.py`, `storage.py` | OS differences, paths, locks and state files |
