@echo off
REM StudentBelongings Cover - Windows launcher (backend + pre-built React UI). Node.js is NOT needed to run this.
REM Demo logins: riya / student123 (student), admin / admin123, assessor / assessor123
setlocal
cd /d "%~dp0"
if not exist "frontend\dist\index.html" (
  echo ERROR: frontend\dist\index.html not found. This package should contain the built UI.
  echo If you are building from source, run build-frontend.bat first ^(needs Node.js 20 or newer^).
  exit /b 1
)
set "PY=python"
where python >nul 2>nul || set "PY=py -3"
cd backend
if not exist .venv\Scripts\python.exe (
  echo Creating virtual environment...
  %PY% -m venv .venv || goto :fail
)
call .venv\Scripts\activate.bat
echo Installing/validating Python dependencies...
python -m pip install --quiet -r requirements.lock.txt || goto :fail
if not exist "..\.env" if not exist ".env" (
  copy "..\.env.example" "..\.env" >nul
  echo Created .env from .env.example ^(development settings: demo accounts, demo data, AI_VERIFY_MODE=dev_simulation^).
)
echo.
echo StudentBelongings Cover is starting. Open http://localhost:8000   ^(API docs, development only: http://localhost:8000/docs^)
echo Press Ctrl+C to stop. Database migrations run automatically at startup ^(a backup is taken first^).
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
goto :eof
:fail
echo.
echo Setup failed. Check that Python 3.11 or newer is installed and on PATH ^(https://www.python.org/downloads/^).
exit /b 1
