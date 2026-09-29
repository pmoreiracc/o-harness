---
name: design
description: Write the design doc for one roadmap initiative through the shared runner.
---
How to run OH commands, such as `config`, `init`, `deliver` or `run`: in Codex, call the o-harness tool of
that name (use `prepare_design` and `pr_summary` for the hyphenated ones) with the checkout's absolute path as
`root`; never run OH from Codex's shell, which cannot write OH's state. In Claude, run the absolute
`<plugin>/scripts/oh` entry supplied by the invoking skill as `<plugin>/scripts/oh --root <checkout> <command>`.
Changing settings (`config set`, `config unset`) is never a tool: run it with `<plugin>/scripts/oh` on either
host, so the person approves it. Stopping a long Codex tool call does not stop OH: call `status` to follow it and
`stop` to end it. When these instructions say to ask the person something that is not a `gate`, offer the choices
as a menu: in Claude, the question tool (AskUserQuestion); in Codex, the o-harness `confirm` tool, which waits for
the click (never Codex's own question tool, which closes when your turn ends).

Resolve the selected Git checkout. Run `config`; if unregistered, run `init` once: it
joins the project of the same repository, or names a new one after the repository (pass
`--name` only when the user asks for another name, or when `config` or `init` says the name is
taken or ambiguous; then ask the user which name to use). Existing project checks run when
configured; design can proceed without checks. No OH files, hooks or settings belong in the product.

The argument is one roadmap slug, such as `/oh-design auth`. Without one, read the roadmap
that `plans path` names and list the initiatives that have no design yet, or say new work
starts with `/oh-propose`; never pick one yourself.

Run `plans path`. If it says to choose where plans live, ask the user once:
in the repository (recommended: the design is reviewed and approved through a pull request)
or private (OH's folder, nothing in the repository). Save the answer with
`config set plans.location repo` or `private`. Private plans default to `~/oh-plans/<project name>/`.
Show the exact folder from `plans path`; `plans.private_folder` changes its parent.

Run `run`. It verifies the native human invocation and starts the design
(repository plans use a new `design/<slug>` branch from `main` or `master`; private plans need no branch). OH reads the roadmap row, a fresh worker writes the prose, and
OH numbers the doc, links it from the row, checks its task list, has it reviewed
independently. Repository plans are committed; private plans wait for your approval. Never write or edit plan files yourself, and
never run your own worker or review loop. If `run` refuses, relay its reason; it names the fix.

If the status is `approval_checkpoint`, show the private plan path, task count and summary,
then **approve** / **refine: <what to change>** / **reconsider**. Approval binds the reviewed
file contents; editing an approved design invalidates that approval. Run `run` after the
human choice. An edited existing private design goes directly to review, preserving the
person's text. A proposed decision remains undecided after approval of the document.
Only drafts and designs edited since approval can be reapproved; frozen and abandoned designs stay closed.
When OH's output has a `gate`, show its choices as a menu. In Claude, call the question tool (AskUserQuestion)
with exactly `gate.ask` and no `answers` field. In Codex, call the o-harness `choose` tool. Then run `run`,
which carries out the answer, unless `choose` says nothing is left to run. Never answer for the person. Typed
choices (`gate.choices`) stay valid everywhere, and are the fallback when no menu can be shown.
Handle the returned status before offering publication:
- `review_checkpoint`: explain the retained findings and offer **grant review** / **stop**.
- `needs_attention`: show the failure and its concrete recovery step, then **retry** / **stop**.
- `findings_checkpoint`: show every finding. Offer **fix concerns** for concerns, **fix scope**
  for scope, or **fix findings** for both. The disposition choices are **accept concerns**,
  **route scope**, or **accept concerns and route scope**, matching exactly the retained
  severities, plus **stop**. Never treat prose or silence as a disposition.
After a recovery choice, call `run` again. For `paused`, wait for **resume** or **stop**;
for `pausing` or `stopping`, report the pending state. A stopped run offers no publication.

Only when `completed`, present the returned `plan`:
- a design: its path, task count and `summary`. Say that approving the design means merging
  its pull request for repository plans; private approval is bound to the file contents.
- a decision record: the question, the recommendation in `summary`, and that the design
  waits for a human decision in that record.

Show **pr** / **stop** only when repository files were committed. Private plans offer **stop**, without a PR. After the user types **pr**, push the branch and open one pull
request whose body ends with the output of `pr-summary`. Never merge it.
