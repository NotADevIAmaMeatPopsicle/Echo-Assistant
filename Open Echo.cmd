@echo off
setlocal
pushd "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Echo's local runtime is missing. See docs\SETUP.md before starting.
  pause
  popd
  exit /b 1
)
powershell.exe -NoProfile -File "%~dp0tools\run.ps1" start
if errorlevel 1 (
  echo Echo could not start. The error above explains what needs attention.
  pause
  popd
  exit /b 1
)
".venv\Scripts\python.exe" tools\open_ui.py --settings
if errorlevel 1 pause
popd
endlocal
