@echo off
set PYTHONUTF8=1
cd /d %~dp0
python src\main.py >> logs\scheduler.log 2>&1
