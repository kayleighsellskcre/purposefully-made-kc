@echo off
REM Run this weekly (e.g. via Windows Task Scheduler) to auto-sync growth metrics
cd /d "%~dp0"
call venv\Scripts\activate.bat
flask sync_growth
pause
