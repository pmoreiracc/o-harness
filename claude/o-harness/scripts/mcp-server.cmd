@echo off
rem Codex starts OH's tool server through this on Windows: .mcp.json names scripts/mcp-server, and Codex finds this
rem file next to it through PATHEXT. With no Python 3.12+ on the computer it fetches OH's own first, as setup does,
rem so OH's tools work from the first Codex session (OH_PYTHON_DOWNLOAD=0 turns that off). It reads nothing
rem and writes to stderr: stdin and stdout carry only the server's messages.
setlocal
call "%~dp0python.cmd"
if defined OH_PY goto run
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -ExecutionPolicy Bypass -InputFormat None -File "%~dp0get-python.ps1" <NUL 1>&2 || exit /b 2
call "%~dp0python.cmd"
if not defined OH_PY (
    >&2 echo OH downloaded Python but can't find it in %oh_data%\python. Start a new Codex session to try again.
    exit /b 2
)
:run
"%OH_PY%" -I -X utf8 "%~dp0mcp-server" %*
exit /b
