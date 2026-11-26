@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Create the Python environment first. See docs\WEB-CONSOLE.md.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" console_app.py --open
if errorlevel 1 pause
