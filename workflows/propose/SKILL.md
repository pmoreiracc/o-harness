---
name: propose
description: Route one idea to a roadmap row, a task in an approved design, or an improvement, through the shared runner.
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
ambiguous, ask the user which name to use and run `init --name <name>`. Proposing runs no project checks: OH
checks every plan file it writes against the plan rules itself. No OH files, hooks or settings belong in the product.

The argument is the idea in the user's words. Without one, run `run` anyway: OH answers with `waiting`. Ask
`waiting.ask` in plain chat and end your turn; the person's next message is the idea (OH reads it through its
prompt hook, so it is their own words), then run `run`. This is the one question asked in plain chat instead of a
menu. Never propose something on their behalf.

Run `plans path`. If it says to choose where plans live, ask the user once:
in the repository (recommended: plans are reviewed and approved through pull requests) or
private (OH's folder, nothing in the repository). Save the answer with
`config set plans.location repo` or `private`. Private plans default to `~/oh-plans/<project name>/`; show `plans path` and allow `plans.private_folder` to choose another parent.

Run `run`. It verifies the native human invocation; a fresh worker reads the
roadmap, designs, decisions and code and routes the idea; OH works out exactly what it would write, writes
nothing yet, and stops for the person's answer. After **approve**, OH writes it (for repository plans, on a new
`propose/<topic>` branch from `main`, which OH brings up to date and switches to itself; private plans need no
branch), checks the plan rules and has the written change reviewed independently, then commits repository
plans. If the review changes where the idea goes or what is written, OH asks the person again with the new
lines. An improvement or an unclear idea writes nothing and has no review. Never write or edit plan files
yourself, and never run your own worker or review loop. Repository plans need the checkout that has `main`: when OH says another worktree holds it, tell the
person to type the command there.

When the returned status is `approval_checkpoint`, present `proposal` in this order:
1. what OH understood the idea to be (`understanding`);
2. the route and its one-line `reason`, with the `evidence`;
3. exactly what OH will write: `lines`, into the files in `intent`, and `writes`, what those lines don't say (the
   milestone a row joins, a new milestone's "Done when", a task's track, a proposed decision record's full text
   and recommendation); for an improvement or an unclear idea, the `text` instead;
4. the choices, as the menu in `gate` (see below) or typed: **approve** (OH writes exactly these lines, has them
   reviewed and commits repository plans), **refine: <what to change>** (in their own words; OH asks the worker
   again), or **reconsider** (nothing is written; OH asks what they meant: ask `waiting.ask` in plain chat, and
   their next message is the new idea). Never choose for them, and never treat silence as approval.

When OH's output has a `gate`, show its choices as a menu. In Claude, call the question tool (AskUserQuestion)
with exactly `gate.ask` and no `answers` field. In Codex, call the o-harness `choose` tool. Then run `run`,
which carries out the answer, unless `choose` says nothing is left to run. Never answer for the person. Typed
choices (`gate.choices`) stay valid everywhere, and are the fallback when no menu can be shown.

After **approve**, run `run` again. If it stops at `approval_checkpoint` again, the review moved the idea: present
it the same way. Then show **pr** / **stop** when something was committed;
after **pr**, push the branch and open one pull request whose body ends with the output of
`pr-summary`, saying plainly what was added and where. Never merge it. For an approved
improvement, say it can be delivered directly; nothing was written.
