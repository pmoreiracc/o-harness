@echo off
rem Starts OH from PowerShell or cmd. Pass JSON values from a file (config set checks @checks.json): cmd
rem re-reads the characters & | < > ^ in arguments.
setlocal
call "%~dp0python.cmd"
if not defined OH_PY (
    for %%A in (%1 %2 %3) do if /i "%%~A"=="setup" goto fetch
    >&2 echo OH needs Python 3.12 or newer. Run "%~f0" setup: it downloads the official Python from python.org into OH's folder, without admin rights or PATH changes.
    exit /b 2
)
goto run
:fetch
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -ExecutionPolicy Bypass -File "%~dp0get-python.ps1" || exit /b 2
call "%~dp0python.cmd"
if not defined OH_PY (
    >&2 echo OH downloaded Python but can't find it in %oh_data%\python. Run setup again.
    exit /b 2
)
:run
"%OH_PY%" -I -X utf8 "%~dp0oh" %*
exit /b
