---
name: design
description: Write the design doc for one roadmap initiative through the shared runner.
---
Use the absolute `<plugin>/scripts/oh` entry supplied by the invoking skill. Resolve the
selected Git checkout. Run `--root <checkout> config`; if unregistered, run `init` once: it
joins the project of the same repository, or names a new one after the repository (pass
`--name` only when the user asks for another name, or when `config` or `init` says the name is
taken or ambiguous; then ask the user which name to use). If `config` then lists no checks, save appropriate ordinary
project checks with `config set checks '<JSON list>'` and tell the user which; never replace
existing checks here. No OH files, hooks or settings belong in the product.

The argument is one roadmap slug, such as `/oh-design auth`. Without one, read the roadmap
that `plans path` names and list the initiatives that have no design yet, or say new work
starts with `/oh-propose`; never pick one yourself.

Run `--root <checkout> plans path`. If it says to choose where plans live, ask the user once:
in the repository (recommended: the design is reviewed and approved through a pull request)
or private (OH's folder, nothing in the repository). Save the answer with
`config set plans.location repo` or `private`. `/oh-design` needs `repo` for now.

Run `--root <checkout> run`. It verifies the native human invocation and starts the design
(on a new `design/<slug>` branch; the checkout must start on `main` or `master`). OH reads the roadmap row, a fresh worker writes the prose, and
OH numbers the doc, links it from the row, checks its task list, has it reviewed
independently and commits the reviewed files. Never write or edit plan files yourself, and
never run your own worker or review loop. If `run` refuses, relay its reason; it names the fix.

At the end, present the returned `plan`:
- a design: its path, task count and `summary`. Say that approving the design means merging
  its pull request.
- a decision record: the question, the recommendation in `summary`, and that the design
  waits for a human decision in that record.

Show **pr** / **stop**. After the user types **pr**, push the branch and open one pull
request whose body ends with the output of `pr-summary`. Never merge it.
