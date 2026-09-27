---
name: propose
description: Explicit OH workflow through the shared external runner.
---
Use the absolute `<plugin>/scripts/oh` entry supplied by the invoking skill. Resolve the
selected Git checkout. Run `--root <checkout> config`; if unregistered, perform explicit
one-time `init --name <name>`, using the name in `join` when `config` reports one. If `config` then lists no checks, save appropriate ordinary
project checks with `config set checks '<JSON list>'` and tell the user which; never replace
existing checks here. No OH files, hooks or settings belong in the product.
Read existing product instructions and business documents. Generic OH does not require ADRs.

The literal human invocation binds this read-only workflow and its requested intent.
Run `--root <checkout> run` to verify the native human event and execute the shared runner.
Do not create implementation scope or run your own worker/review loop. Read the saved
artifact referenced by the checkpoint, summarize it briefly, and end at the decision
boundary. A later oh-deliver invocation must authorize the exact implementation plan.
