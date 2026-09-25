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

<h3>Ship code you trust, without watching every line.</h3>

<p>For developers who build alone with AI.</p>

</div>

<br>

AI writes code faster than you can review it.
So you babysit the chat, or you merge and hope.

**OH gives you a third option: a team that checks the work for you.**

<br>

## How it works

**1. Plan.** Tell your agent what you want to build.

**2. Approve once.** One message starts the whole batch.

**3. Walk away.** Every task gets a fresh agent, your tests, and an independent review before it's committed.

You come back to reviewed commits. You decide what ships.

<br>

## Install

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

Then open your project and type `/oh-propose` and your idea (Codex: `$oh-propose`).

<sub>macOS or Linux · Python 3.11+ · runs on your Claude or ChatGPT subscription, no API costs</sub>

<br>

---

[Guide](docs/usage.md) · [Install & updates](docs/installation.md) · [Settings](docs/configuration.md) · [Dashboard](docs/analytics.md) · [MIT License](LICENSE)

<sub>*O* is Portuguese for *the*. Say “oh”.</sub>
