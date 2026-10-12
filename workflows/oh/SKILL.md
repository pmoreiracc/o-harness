---
name: oh
description: Explicit OH execution and bounded task preparation through the external runner.
---
Read `workflows/runtime.md` once through the same OH resource entry and follow its shared execution protocol.

For already prepared scope, use `start` to verify the native invocation and execute its batch.
For a new quick fix, call `run` once to bind the request and refresh its base before inspecting
work. It returns preparation without launching implementation. Prepare only the agreed scope:
`id`, `title`, `instructions`, and optional dependency IDs in `needs`, ordered by dependency.
Do not assign models or effort; OH assesses each new task at runtime.

In Codex pass the tasks to `prepare`. In Claude save the manifest in external OH project storage
and use `prepare <absolute-path>`. Present the returned scope preview and limits through its
Approve / Refine / Cancel question. A prepared identifier remains a typed fallback, never
something the assistant can send as human approval. For a consumer-v1 project, `prepare-design`
binds the consumer's approved design without changing its approval policy.

Follow the shared protocol for execution, progress, returned decisions and publication.
