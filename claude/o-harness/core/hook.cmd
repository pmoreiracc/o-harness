@echo off
rem Codex's prompt hook on Windows. Without Python it stays silent: ordinary prompts must never fail.
setlocal
call "%~dp0python.cmd"
if not defined OH_PY exit /b 0
"%OH_PY%" -I -X utf8 "%~dp0human-event.py" %*
exit /b
