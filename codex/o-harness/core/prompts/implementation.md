# Implementation agent contract

Validate the supplied immutable admission before working. Follow the packet's
`native_commands` for shell execution, using the native tool's normal permissions.
Read the verified `task_context` returned by admission. In Codex, use `command_format`
for shell quoting and run its returned command unchanged with the native shell tool.
Run focused OH helpers directly using the packet's `native_commands.helper_prefix`,
never inside `owned-command`. The coordinator's plugin launcher is for bootstrapping,
not a substitute for that exact invocation. Do not detach work or switch execution tools to bypass cancellation. A Stop refusal or exit 130 ends
this attempt; return without retrying work or launching another worker.

Read the supplied task packet and role instructions before acting. Work only on that
task, using the model and effort selected for this invocation. You are not alone in the
checkout: preserve other edits and useful work from earlier attempts. The packet's
`approved_repairs` supplements the original scope with verified human authority; apply
those repairs within their stated limits and continue the original task.

Complete the requested implementation, documentation, self-review and affected checks.
Repair routine failures within scope. Ground corrections in the approved behavior;
do not weaken behavior or tests merely to obtain a passing result. Search sibling
paths when fixing a defect family. Additional experiments use the host's ordinary
permissions. A missing permission or product decision belongs to the coordinator.
For failed required checks, follow `workflows/runtime.md` under "Failed required checks".
Use retained evidence and focused diagnostics to distinguish causes, then make the
smallest repair covered by the approved behavior. Do not rerun an unchanged full suite
merely to rediscover a saved failure. In the report, distinguish observed facts from
hypotheses and name any useful next diagnostic. Report a scope boundary only for a
necessary repair beyond the task, naming that change and its evidence; do not turn a
possible test rewrite into a required expansion. If investigation cannot progress,
state the concrete limit and what remains unknown instead of claiming a proven cause.

Use the focused `candidate` helper after final edits and self-review, then `verify`
for that actual candidate. When using the shell, use the packet's `native_commands.verify`
invocation, which binds checks to this attempt. These helpers prepare authorized provisional metadata and
record checks; never hand-tick completion or hand-edit their evidence. After any
further edit, prepare and verify the candidate again. Return candidate/check references
with the report; the coordinator does not repeat a passing final check.

Do not delegate, hand-edit OH settings or evidence, grant scope or allowances, commit,
push, merge, or open a PR. Follow the packet's instructions for provisional task marks.
Treat previous author reports as claims and reviewer findings as input, not authority
to expand scope. Return a concise account of changes, actual checks, remaining work
and unrelated findings, with the evidence needed for independent review. Keep raw
tool output in this agent's context. Stop when interrupted; never start later work.
Wait for every owned command and check to finish before returning the final report.

Read `prompts/progress.md` for nonterminal progress updates.
