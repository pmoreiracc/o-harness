# Nonterminal progress

While working, send a concise update at a meaningful transition or after roughly
two to three minutes of substantive work. State the concrete subtask underway,
its purpose, and the next check or step. Use only observed work, not predicted results.
An example: “Updating retry handling so cancelled requests release their resources;
next I’ll check cancellation and timeout cases.” Avoid repeating unchanged updates.

Use the host's supported nonterminal coordinator/progress channel when available,
with the recipient supplied by the host or coordinator; otherwise ordinary commentary.
Do not guess a recipient, add tools, write progress files or create a reporting service.
Progress grants no approval and does not replace the final report. Never use Claude's
terminal `SubagentHandback` merely to report progress or restart a child to obtain an update.

Keep raw command output and full transcripts in your own context. If a long-running
command provides no detail, stay quiet or send a brief generic update. Do not invent
activity or explain internal visibility limitations. Check results and review readiness
are reported only after the actual checks finish. Stop when interrupted.
