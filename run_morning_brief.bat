@echo off
set PYTHONUTF8=1
cd /d C:\Users\sn100\Downloads\email-triage
python src\main.py >> logs\scheduler.log 2>&1
