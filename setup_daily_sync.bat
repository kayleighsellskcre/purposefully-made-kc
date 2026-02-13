@echo off
REM Windows Task Scheduler batch file for daily inventory sync

cd /d "%~dp0"
call venv\Scripts\activate
python daily_inventory_sync.py >> logs\daily_sync.log 2>&1
