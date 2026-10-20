@echo off
rem Native interruption and tool guard; use the installed Python without changing host permissions.
setlocal
call "%~dp0python.cmd"
if not defined OH_PY exit /b 0
"%OH_PY%" -I -X utf8 "%~dp0native-control.py" %*
exit /b
