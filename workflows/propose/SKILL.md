---
name: propose
description: Explicit OH workflow through the shared external runner.
---
Use the absolute `<plugin>/scripts/oh` entry supplied by the invoking skill. Resolve the
selected Git checkout. Run `--root <checkout> config`; if unregistered, perform explicit
one-time `init --name <name>` and save appropriate ordinary project checks in the returned
external profile directory. No OH files, hooks or settings belong in the product.
Read existing product instructions and business documents. Generic OH does not require ADRs.

The literal human invocation binds this read-only workflow and its requested intent.
Run `--root <checkout> run` to verify the native human event and execute the shared runner.
Do not create implementation scope or run your own worker/review loop. Read the saved
artifact referenced by the checkpoint, summarize it briefly, and end at the decision
boundary. A later deliver invocation must authorize the exact implementation plan.
