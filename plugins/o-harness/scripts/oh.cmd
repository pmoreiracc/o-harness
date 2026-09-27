@echo off
rem Starts OH from PowerShell or cmd with a Python 3.11+ already on this computer, or the official
rem Python that "oh.cmd setup" fetches into OH's folder when there is none.
setlocal
set "script=%~dp0oh"
set "data=%OH_DATA_HOME%"
if "%data%"=="" set "data=%USERPROFILE%\.local\share\o-harness"
set "check=import sys; sys.exit(sys.version_info < (3, 11))"
python3 -c "%check%" >nul 2>&1 && goto python3
python -c "%check%" >nul 2>&1 && goto python
py -3 -c "%check%" >nul 2>&1 && goto py
"%data%\python\python.exe" -c "%check%" >nul 2>&1 && goto own
if /i "%~1"=="setup" goto fetch
if /i "%~3"=="setup" goto fetch
>&2 echo OH needs Python 3.11 or newer. Run "%~f0" setup: it downloads the official Python from python.org into OH's folder, without admin rights or PATH changes.
exit /b 2
:fetch
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0get-python.ps1" || exit /b 2
goto own
:python3
python3 -I -X utf8 "%script%" %*
exit /b
:python
python -I -X utf8 "%script%" %*
exit /b
:py
py -3 -I -X utf8 "%script%" %*
exit /b
:own
"%data%\python\python.exe" -I -X utf8 "%script%" %*
exit /b
