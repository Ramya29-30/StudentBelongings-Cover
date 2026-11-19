@echo off
REM Runs the backend tests (pytest) and, if Node.js is installed, the frontend tests (vitest). Does not touch your real database.
setlocal
cd /d "%~dp0backend"
if not exist .venv\Scripts\python.exe ( python -m venv .venv || exit /b 1 )
call .venv\Scripts\activate.bat
python -m pip install --quiet -r requirements-dev.txt -r requirements.lock.txt || exit /b 1
python -m pytest -q || exit /b 1
where node >nul 2>nul || (echo Node.js not found: skipping the frontend tests. & exit /b 0)
cd /d "%~dp0frontend-react"
call npm ci || exit /b 1
call npm test
