@echo off
rem Codex's agent-launch guard on Windows. Without Python it stays silent: launches must never fail on it.
setlocal DisableDelayedExpansion
pushd "%~dp0" || exit /b 1
call .\python.cmd
popd
if not defined OH_PY exit /b 0
"%OH_PY%" -I -X utf8 "%~dp0agent-launch.py" %*
exit /b
