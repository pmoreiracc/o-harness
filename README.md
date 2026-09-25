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

<p><strong>Your agents. Your standards.</strong></p>

<p>An agentic development harness for independent developers.</p>

</div>

You're one developer with a product to build and an AI subscription. Asking the chat to
"build X" gets you code fast, but not code you'd stand behind. OH adds the structure a good
team would bring: every task gets a fresh agent, has to pass your checks, and is reviewed by
an independent reviewer until it's right. Only then is it committed.

**Plan once, then walk away.** Agree on a plan, approve it once, and OH works through the
whole batch in order while you do something else. You come back to reviewed commits, ready
for a pull request, not a chat to babysit.

**Match it to your subscription.** On a bigger plan, raise the limits so a 15-task design
runs in one go, with up to 12 review rounds per task approved in advance. OH uses only the
rounds a task needs, and stops to ask you only when something actually needs you.

```json
{"tasks_per_batch": 15, "review_rounds": 12}
```

**Stay in charge.** Nothing starts without your typed approval, the approved scope can't
grow, and you do the merging. OH runs on your Claude or ChatGPT subscription through the
official CLIs, never on paid API calls, and adds no OH files to your repository.

*O* means *the* in Portuguese: **O harness**, the harness. Say “oh”.

## How it works

1. Optionally plan with `/oh-propose` or `/oh-design`. Then run `/oh-deliver` and agree on
   the tasks with your agent.
2. Approve that exact batch by typing the trigger OH gives you.
3. For each task, OH starts a fresh worker, runs your project's checks, gets an independent
   review, fixes blockers and commits the reviewed result. Other findings wait for you.
4. When a batch ends, choose **continue** (if tasks remain), **pr** or **stop**. You merge.

Version 0.3. Tested on macOS with Claude Code and Codex; the test suite also runs on Linux.
Windows isn't supported yet.

## Quick start

You need macOS or Linux, Python 3.11+, Git, and Claude Code or Codex signed in with a
subscription. To change the limits, see [configuration](docs/configuration.md).

**Claude Code**

```sh
claude plugin marketplace add pmoreiracc/o-harness#dist
claude plugin install o-harness@o-harness
```

**Codex**

```sh
codex plugin marketplace add pmoreiracc/o-harness --ref dist
codex plugin add o-harness@o-harness
```

Then start a new session in your project, run `/oh-propose <idea>` (Codex: `$oh-propose`)
and follow [first use in a project](docs/installation.md#first-use-in-a-project).

## Commands

| Command | What it does |
|---|---|
| `/oh-propose <idea>` | Read-only proposal: options and a recommendation |
| `/oh-design <idea>` | Read-only, reviewed task plan |
| `/oh-deliver` | Prepare and run an agreed batch of tasks |
| `/oh-pause`, `/oh-resume`, `/oh-stop` | Control a running batch |

If another plugin uses the same short name, use the full name, such as `/o-harness:oh-design`.

## Docs

- [Installation and updates](docs/installation.md)
- [Using OH](docs/usage.md)
- [Configuration](docs/configuration.md)
- [Dashboard and data](docs/analytics.md)
- [Architecture](docs/architecture.md)
- [Contributing](CONTRIBUTING.md)

Planned work is tracked in [GitHub Issues](https://github.com/pmoreiracc/o-harness/issues).
OH is released under the [MIT License](LICENSE).
