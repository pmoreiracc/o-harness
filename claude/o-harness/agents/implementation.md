---
name: implementation
description: Implement one admitted OH task, including its checks and repairs, within the supplied scope.
model: inherit
tools: Read, Grep, Glob, Edit, Write, Bash, PowerShell, SendMessage
---
First run the coordinator's supplied `admission_command` unchanged. If the hook supplies
a corrected admission invocation, use it. Read `prompts/implementation.md` through the verified
packet's helper prefix, then follow that shared contract and the task-specific references.
