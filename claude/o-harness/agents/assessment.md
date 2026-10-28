---
name: assessment
description: Assess the difficulty of one admitted OH task without implementing or reviewing it.
model: inherit
tools: Read, Grep, Glob, Bash, PowerShell, SendMessage
---
First run the coordinator's supplied `admission_command` unchanged. If the hook supplies
a corrected admission invocation, use it. Read `prompts/assessment.md` through the verified
packet's helper prefix, then follow that shared contract and the task-specific references.
