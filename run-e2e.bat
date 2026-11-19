@echo off
REM Runs the Playwright browser suite against a throw-away database. Needs Node.js 20+ and the built UI (frontend\dist).
setlocal
cd /d "%~dp0e2e"
if not exist ..\frontend\dist\index.html ( echo Build the UI first: build-frontend.bat & exit /b 1 )
if not exist ..\backend\.venv\Scripts\python.exe ( echo Run start.bat or run-tests.bat once first to create backend\.venv & exit /b 1 )
call npm ci || exit /b 1
call npx playwright install chromium || exit /b 1
call npx playwright test
echo.
echo HTML report: %~dp0e2e\playwright-report\index.html
