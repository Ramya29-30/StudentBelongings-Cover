@echo off
REM Stops the StudentBelongings Cover server listening on port 8000.
setlocal
set FOUND=0
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8000" ^| findstr "LISTENING"') do (
  taskkill /PID %%a /F >nul 2>nul && set FOUND=1
)
if "%FOUND%"=="1" (echo Server stopped.) else (echo No server was listening on port 8000.)
