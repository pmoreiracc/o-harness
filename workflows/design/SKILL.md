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

When OH refuses, the command you were given stays valid until OH carries it out, so the person never types it
again. Fix what is yours to fix and run the same OH command again without mentioning it. When the fix is the
person's call, such as their own uncommitted changes, a merge conflict or another run still open, say what is in
the way in one sentence and ask only with a menu, never in plain chat: anything they type instead sets the command
aside. Do what they pick, with exactly the commands OH names for it, then run it again; run `cancel` only when
they pick dropping the command, and `stop` only when they pick ending the other run. Never commit, stash or
discard their changes unless they pick that, and never switch, pull or create branches for OH: it does that
itself. After opening a pull request, give its link; don't wait for or watch its checks.

Resolve the selected Git checkout; the typed command registers it with OH. If OH says the name is taken or
ambiguous, ask the user which name to use and run `init --name <name>`. Designing runs no project checks: OH
checks every plan file it writes against the plan rules itself. No OH files, hooks or settings belong in the product.

The argument is one roadmap slug, such as `/oh-design auth`. Without one, run `run` anyway: OH answers with
`waiting` and the roadmap rows that have no design yet (`initiatives`), or says new work starts with
`/oh-propose`. List those rows, ask `waiting.ask` in plain chat and end your turn; the person's next message
(a slug) is the argument, then run `run`. Never pick one yourself.

Run `plans path`. If it says to choose where plans live, ask the user once:
in the repository (recommended: the design is reviewed and approved through a pull request)
or private (OH's folder, nothing in the repository). Save the answer with
`config set plans.location repo` or `private`. Private plans default to `~/oh-plans/<project name>/`.
Show the exact folder from `plans path`; `plans.private_folder` changes its parent.

Run `run`. It verifies the native human invocation and starts the design
(repository plans use a new `design/<slug>` branch from `main`, which OH brings up to date and switches to
itself; private plans need no branch). OH reads the roadmap row, a fresh worker writes the prose, and OH numbers
the doc, links it from the row, checks its task list, has it reviewed independently. Repository plans are
committed; private plans wait for your approval. Never write or edit plan files yourself, and never run your own
worker or review loop. Repository plans need the checkout that has `main`: when OH says another worktree holds it, tell the
person to type the command there.

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
- `findings_checkpoint`: show every finding and exactly the returned menu. Concerns can be
  fixed or accepted; scope can be routed or dismissed, never implemented. A combined menu
  pairs those choices. Never treat prose or silence as a disposition.
After a recovery choice, call `run` again. For `paused`, wait for **resume** or **stop**;
for `pausing` or `stopping`, report the pending state. A stopped run offers no publication.

Only when `completed`, present the returned `plan`:
- a design: its path, task count and `summary`. Say that approving the design means merging
  its pull request for repository plans; private approval is bound to the file contents.
- a decision record: the question, the recommendation in `summary`, and that the design
  waits for a human decision in that record.

Show **pr** / **stop** only when repository files were committed. Private plans offer **stop**, without a PR. After the user types **pr**, push the branch and open one pull
request whose body ends with the output of `pr-summary`. Never merge it.
