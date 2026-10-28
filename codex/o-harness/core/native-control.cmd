@echo off
rem Native interruption and tool guard; use the installed Python without changing host permissions.
setlocal DisableDelayedExpansion
pushd "%~dp0" || exit /b 1
call .\python.cmd
popd
if not defined OH_PY exit /b 0
"%OH_PY%" -I -X utf8 "%~dp0native-control.py" %*
exit /b
