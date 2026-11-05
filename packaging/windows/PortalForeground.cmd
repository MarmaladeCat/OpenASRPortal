@echo off
setlocal
set "PYTHONUTF8=1"
set "PYTHONUNBUFFERED=1"
set "PYTHONDONTWRITEBYTECODE=1"
"%~dp0python\python.exe" -B -m openasrportal.entrypoints.service foreground --config "%LOCALAPPDATA%\OpenASRPortal\service.json"
if errorlevel 1 pause
