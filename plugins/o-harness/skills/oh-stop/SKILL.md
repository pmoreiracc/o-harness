---
name: oh-stop
description: Cancel and end the current OH run, preserving its work and evidence.
disable-model-invocation: true
---
Load `workflows/runtime.md` through OH's resource entry. Stop the current run through
the host's native cancellation tools for its known active agents and commands, then
record the direct human stop decision. Start no later check, review or completion.
Retain completed results, attempts and edits. Report stopped only after native work is
confirmed cancelled; otherwise name the remaining work and the native action needed.
Never substitute an OH process supervisor or claim that interrupting the parent alone
establishes child cancellation. A saved stopped status alone is not cancellation
proof: if a known check is still live, report Stop requested; cancellation pending,
use native cancellation, and launch no later phase.
After retaining terminal cancellation/results, record `decision stop
<native-locator.json>` (Codex `decision`, kind `stop`) from the person's actual request.

A later matching work command discovers the saved work in a new native conversation.
Continue only after its actual human Resume answer. This control is optional, never a prerequisite for that continuation;
discovery alone does not lift it.

Resolve the absolute plugin launcher two levels above this skill: `scripts/oh`
(`scripts\oh.cmd` on native Windows). Keep OH configuration and evidence outside
consumer repositories. Discovery alone does not authorize setup or execution.

In Codex first call `mcp__o_harness__resource` with the checkout's absolute `root`
and `path: "workflows/runtime.md"`. In code mode, call
`text(await tools.mcp__o_harness__resource({root: "<checkout>", path: "workflows/runtime.md"}))`
inside `functions.exec`. In Claude use
`<plugin>/scripts/oh --root <checkout> resource workflows/runtime.md`.

OH's `resource` is a tool. MCP resource/template listings do not discover OH tools
or establish connection health. If tool lookup is needed, match `mcp__o_harness__`
in the available tool inventory. A failed text search is not a connection failure.
Retry a failed read once using the actual tool. For an uncertain state-changing call,
inspect its saved outcome before retrying with the same inputs. Preserve the current
request and approvals through recovery. Diagnose a connection failure from the actual
OH tool error; report an unavoidable host action only after supported recovery fails.
