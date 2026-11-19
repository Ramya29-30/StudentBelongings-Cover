@echo off
REM Builds the React UI into frontend\dist. Needs Node.js 20+ ONLY for this step.
setlocal
cd /d "%~dp0frontend-react"
where node >nul 2>nul || (echo Node.js 20 or newer is required to build the UI. Download it from https://nodejs.org/ & exit /b 1)
call npm ci || exit /b 1
call npm run build || exit /b 1
echo.
echo Built: %~dp0frontend\dist
