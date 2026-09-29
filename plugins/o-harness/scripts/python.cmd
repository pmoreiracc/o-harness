@rem Sets OH_PY to the official Python that OH fetched into its folder, or else to a Python 3.12+ already on this
@rem computer. OH's own comes first: it is a file check, where each other candidate costs a process start. It looks from
@rem this plugin's own folder with the current-folder search off, so a python3.cmd or python.exe planted in a project
@rem folder is never found.
@set "NoDefaultCurrentDirectoryInExePath=1"
@set "OH_PY="
@set "oh_data=%OH_DATA_HOME%"
@if "%oh_data%"=="" set "oh_data=%USERPROFILE%\.local\share\o-harness"
@pushd "%~dp0"
@set "oh_version="
@if exist "%oh_data%\python\current" set /p oh_version=<"%oh_data%\python\current"
@if defined oh_version if exist "%oh_data%\python\%oh_version%\python.exe" set "OH_PY=%oh_data%\python\%oh_version%\python.exe"
@for %%P in (python3 python) do @if not defined OH_PY for /f "usebackq delims=" %%E in (`%%P -I -c "import sys; sys.version_info >= (3, 12) and print(sys.executable)" 2^>nul`) do @set "OH_PY=%%E"
@if not defined OH_PY for /f "usebackq delims=" %%E in (`py -3 -I -c "import sys; sys.version_info >= (3, 12) and print(sys.executable)" 2^>nul`) do @set "OH_PY=%%E"
@popd
