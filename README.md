<div align="center">

<pre>
 ██████╗ ██╗  ██╗
██╔═══██╗██║  ██║
██║   ██║███████║
██║   ██║██╔══██║
╚██████╔╝██║  ██║
 ╚═════╝ ╚═╝  ╚═╝
</pre>

<h1>o-harness</h1>

<h3>Approve the plan. Close the laptop. Come back to reviewed code.</h3>

<p>Your agents. Your standards. A harness for developers who build alone.</p>

</div>

---

You're building a product on your own. Your AI writes code faster than you can read it, so
every day you pick one of two bad options: **babysit the chat**, or **merge code you never
really checked.**

OH is the third option. It gives your agent the process a good engineering team runs on.
Every task gets a fresh agent. Every change has to pass your tests. Every result goes to an
independent reviewer that sends it back until it's right. You approve the plan once, and
OH works through it task by task while you sleep, work, or start on the next idea.

## What a batch looks like

```text
you   /oh-deliver the 15 tasks from the billing design
oh    15 tasks ready · up to 12 reviews each · checks: test, lint, typecheck
      To approve, type:  $o-harness:oh-deliver request:9f3c…

you   $o-harness:oh-deliver request:9f3c…

      ☕  you go live your life

oh    task  1  invoice model     checks ✓   review ✓                       committed
oh    task  2  invoice PDFs      checks ✓   review ✗ 1 blocker → fixed ✓   committed
      …
oh    task 15  receipt emails    checks ✓   review ✓                       committed
oh    15/15 done  →  continue · pr · stop
```

<sub>Simplified. Real runs show the same steps with more detail.</sub>

## Why not just keep chatting?

| Chatting with an agent | With OH |
|---|---|
| One long chat that gets slower and sloppier | A fresh agent for every task |
| The agent grades its own homework | A separate reviewer with fresh eyes |
| "Done" means it looks done | Done means your checks pass and the review is clean |
| You approve every step | You approve the plan once |
| Surprise API bills | Your Claude or ChatGPT subscription, nothing else |
| You hope it's fine | Every commit is linked to its review evidence |

## Get started

```sh
# Claude Code
claude plugin marketplace add pmoreiracc/o-harness#dist
claude plugin install o-harness@o-harness

# Codex
codex plugin marketplace add pmoreiracc/o-harness --ref dist
codex plugin add o-harness@o-harness
```

Open your project in a new session and type `/oh-propose <your idea>` (Codex: `$oh-propose`).
The first time, OH sets itself up and registers your project with the agent's help.
[Full install guide](docs/installation.md).

Needs macOS or Linux, Python 3.11+, Git, and Claude Code or Codex on a subscription.

## Turn it up to your plan

By default a batch runs 5 tasks with up to 3 review rounds each. On a bigger subscription,
let it go further. This runs a 15-task design in one go, with 12 review rounds per task
approved in advance:

```json
{"tasks_per_batch": 15, "review_rounds": 12}
```

OH only uses the rounds a task needs. It stops early only when something really needs you:
a finding it won't decide for you, or a task that keeps failing.
[All settings](docs/configuration.md).

## You stay in charge

- **Nothing runs until you type the approval.** The agent can't approve for you.
- **The approved scope can't grow.** New work needs a new approval.
- **OH never merges.** You do.
- **Stop anytime** with `/oh-pause`, `/oh-resume` or `/oh-stop`. Work and evidence are kept.
- **Your repo stays yours.** OH adds no files to it; its state lives in `~/.local/share/o-harness`.

## Commands

| Command | What it does |
|---|---|
| `/oh-propose <idea>` | Options and a recommendation. Read-only. |
| `/oh-design <idea>` | A reviewed task plan. Read-only. |
| `/oh-deliver` | Agree on tasks, approve them, and let OH build them |
| `/oh-pause` · `/oh-resume` · `/oh-stop` | Control a running batch |

## See how it's going

A local dashboard at <http://localhost:4318> shows tokens per task, review rounds, how often
the first review passes, and time per task, so you can tell whether a settings change
actually helped. Opening it never calls a model. [More](docs/analytics.md).

## Learn more

[Install and update](docs/installation.md) · [Using OH](docs/usage.md) ·
[Configuration](docs/configuration.md) · [Dashboard](docs/analytics.md) ·
[Architecture](docs/architecture.md) · [Contributing](CONTRIBUTING.md)

**Status:** version 0.3. Tested on macOS with Claude Code and Codex; the test suite also runs
on Linux. Windows support is [coming](https://github.com/pmoreiracc/o-harness/issues/8).

**The name:** *o* means *the* in Portuguese. **O harness**, the harness. Say “oh”.

[MIT License](LICENSE)
