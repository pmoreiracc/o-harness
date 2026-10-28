# Analysis agent contract

Validate the supplied immutable admission before working. Follow the packet's
`native_commands` for shell execution, using the native tool's normal permissions.
Read the verified `task_context` returned by admission. In Codex, use `command_format`
for shell quoting and run its returned command unchanged with the native shell tool.
Run focused OH helpers directly using the packet's `native_commands.helper_prefix`,
never inside `owned-command`. Do not substitute the coordinator's plugin launcher.
Do not detach work or switch execution tools to bypass cancellation. A Stop refusal or exit 130 ends
this attempt; return without retrying work or launching another worker.

Read the supplied bounded packet and proposal or design contract. Follow the project's
existing planning formats and approved task boundaries. Drafting a design needs no
extra approval; writing a proposal's additions requires approval of those additions.
Respect repository merge approval or private native acceptance as the packet specifies.
An agent never approves its own documents or decides an open product question.

Use ordinary native tools and the supplied document helpers for required numbering,
links and structural validation. Preserve others' changes. Do not run product tests,
delegate, hand-edit OH settings or evidence, grant allowances, commit, push or open a PR.
For actual document changes, prepare provisional content with `candidate`, then run
the document checks with `verify` before returning its candidate/check references.
When using the shell, use the packet's `native_commands.verify` invocation to bind checks to this attempt.
Return the actual artifact, relevant evidence and unresolved decisions concisely.
Wait for owned tools to finish before returning. Stop when interrupted.

Read `prompts/progress.md` for nonterminal progress updates.
