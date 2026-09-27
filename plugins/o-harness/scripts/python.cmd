@rem Sets OH_PY to a Python 3.11+ already on this computer, or to the official Python that setup fetched into
@rem OH's folder. It looks from this plugin's own folder with the current-folder search off, so a python3.cmd or
@rem python.exe planted in a project folder is never found.
@set "NoDefaultCurrentDirectoryInExePath=1"
@set "OH_PY="
@set "oh_data=%OH_DATA_HOME%"
@if "%oh_data%"=="" set "oh_data=%USERPROFILE%\.local\share\o-harness"
@pushd "%~dp0"
@for %%P in (python3 python) do @if not defined OH_PY for /f "usebackq delims=" %%E in (`%%P -I -c "import sys; sys.version_info >= (3, 11) and print(sys.executable)" 2^>nul`) do @set "OH_PY=%%E"
@if not defined OH_PY for /f "usebackq delims=" %%E in (`py -3 -I -c "import sys; sys.version_info >= (3, 11) and print(sys.executable)" 2^>nul`) do @set "OH_PY=%%E"
@if not defined OH_PY if exist "%oh_data%\python\current" (
    set /p oh_version=<"%oh_data%\python\current"
)
@if not defined OH_PY if defined oh_version if exist "%oh_data%\python\%oh_version%\python.exe" set "OH_PY=%oh_data%\python\%oh_version%\python.exe"
@popd
