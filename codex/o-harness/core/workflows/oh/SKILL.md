---
name: oh
description: Select the requested OH workflow or prepare one bounded quick fix.
---
Read `workflows/runtime.md` once through OH's resource entry and inspect `status --saved`
before asking what to do. If the intended work is missing, show relevant
unfinished work. Use Claude `AskUserQuestion` or Codex Default mode
`functions.request_user_input_async` when choosing among concrete work options.
For an open-ended request, ask what the person wants in chat. Wait for the answer. Do not start a run or infer
approval from this selector invocation alone.

Route an idea to `workflows/propose/SKILL.md`, a roadmap initiative to
`workflows/design/SKILL.md`, approved design tasks or a bounded quick fix to
`workflows/deliver/SKILL.md`, and requested inspection to `workflows/review/SKILL.md`.
Existing saved work uses the matching resume facts and always needs the one Resume
choice, even when its subject was supplied. Keep the person's actual request
and project approval rules; do not turn a request for feedback into implementation.
