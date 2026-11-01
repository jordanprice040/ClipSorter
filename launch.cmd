@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Run powershell -ExecutionPolicy Bypass -File setup.ps1 first.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" sorter_gui.py
if errorlevel 1 pause
