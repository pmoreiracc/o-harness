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

OH is built around a simple ambition: give independent developers the support of a thoughtful engineering team, with AI agents doing the work and human judgment setting the direction.

Make room for bigger ideas. Keep care and craft in the work. Build software you can stand behind.

---

**Why OH?** In Portuguese, *o* means *the*. **O harness. The harness.** A small Brazilian signature. Call it **“oh.”**

**Early implementation.** OH runs sequential task batches through Codex or Claude Code subscriptions, with independent reviews and a local analytics dashboard. Public installation and parallel task execution are still planned.

## How it works

Agree on a batch in one conversation. Your coordinator prepares its scope and settings;
you authorize that prepared request. OH then selects a model for each task, starts a fresh
worker, verifies the result, runs an independent review, and commits completed work.
Full worker transcripts stay outside the conversation. At the batch boundary, choose
**continue**, **PR**, or **stop**. You remain the person who merges.

The default batch contains five tasks, with three review rounds per task. Both are
configurable. Restarting does not reset those limits. Codex is the primary host; both
subscription adapters have been exercised locally. Unsupported host/model combinations
fail visibly; OH never falls back to paid API calls.

## Start here

- [Use OH](docs/usage.md): setup, task batches, choices, and recovery.
- [Configuration](docs/configuration.md): shared settings, local overrides, and models.
- [Dashboard and data](docs/analytics.md): metrics, comparisons, suggestions, and privacy.
- [Architecture](docs/architecture.md): repository boundaries and extension points.
- [Contributing](CONTRIBUTING.md): flexible development without mandatory ADRs.

The dashboard is available at **http://localhost:4318** after local service installation.
Opening it does not call a model. Its data starts with observed OH runs; historical logs
are not presented as a trustworthy baseline.

Track upcoming work in [GitHub Issues](https://github.com/pmoreiracc/o-harness/issues).
Parallel implementation, a public installer, scheduled recommendations, and additional
host adapters are deferred. This repository currently remains private; no public release
or license grant is implied.
