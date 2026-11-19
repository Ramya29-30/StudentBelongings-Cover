@echo off
REM Consistent SQLite backup. Also copy backend\data\uploads (evidence files) - see docs\DEPLOYMENT.md
setlocal
cd /d "%~dp0backend"
call .venv\Scripts\activate.bat
python -m app.cli backup %*
