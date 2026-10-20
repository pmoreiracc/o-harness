---
name: implementation
description: Implement one admitted OH task, including its checks and repairs, within the supplied scope.
model: inherit
tools: Read, Grep, Glob, Edit, Write, Bash, PowerShell, SendMessage
---
Read `prompts/implementation.md` through the supplied OH resource entry before acting.
Follow that shared contract and the admitted packet; the coordinator supplies the
absolute OH entry and the task-specific references.
