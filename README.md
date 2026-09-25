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

OH gives an independent developer the support of a careful engineering team: AI agents do
the work, independent reviews check it, and you decide what ships.

*O* means *the* in Portuguese: **O harness**, the harness. Say “oh”.

> **Early preview.** Tested on macOS with Claude Code and Codex. Expect rough edges.

## How it works

1. You agree on a batch of tasks with your agent.
2. You approve that exact batch by typing the trigger OH gives you.
3. For each task, OH starts a fresh worker, runs your project's checks, gets an independent
   review, fixes blockers and commits the reviewed result.
4. At the end of the batch you choose **continue**, **PR** or **stop**. You merge.

OH runs on your Claude or ChatGPT subscription through the official CLIs. It never falls
back to paid API calls. Nothing is added to your product repository; OH keeps its state in
`~/.local/share/o-harness`.

## Quick start

You need macOS or Linux, Python 3.11+, Git, and Claude Code or Codex signed in with a
subscription.

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

Then follow [first use in a project](docs/installation.md#first-use-in-a-project): trust
your host CLI once, and start a new session in your project with `/oh-propose <idea>`
(Codex: `$oh-propose`).

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
