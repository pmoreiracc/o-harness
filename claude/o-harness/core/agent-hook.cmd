@echo off
rem Codex's agent-launch guard on Windows. Without Python it stays silent: launches must never fail on it.
setlocal
call "%~dp0python.cmd"
if not defined OH_PY exit /b 0
"%OH_PY%" -I -X utf8 "%~dp0agent-launch.py" %*
exit /b
