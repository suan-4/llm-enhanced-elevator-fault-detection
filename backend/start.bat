@echo off
rem ---------------------------------------------------------------------------
rem Local dev only: start FastAPI on 127.0.0.1:8081.
rem web/vite.config.ts proxies /api to 127.0.0.1:8081, so the port must match.
rem The board runs under systemd and does not use this script.
rem ---------------------------------------------------------------------------
setlocal

rem Always run from backend/ so that "app.main" can be imported.
cd /d "%~dp0"

set "PYTHONUNBUFFERED=1"
if not defined ELEVATOR_PYTHON set "ELEVATOR_PYTHON=D:\miniconda3\envs\elevator_kg\python.exe"
if not exist "%ELEVATOR_PYTHON%" set "ELEVATOR_PYTHON=python"

rem Make sure the local Neo4j is up. Ignore failures: backend degrades gracefully.
sc query neo4j >nul 2>nul
if errorlevel 1 (
  if exist "D:\Program Files\neo4j-community-2026.05.0\bin\neo4j.bat" (
    start "" "D:\Program Files\neo4j-community-2026.05.0\bin\neo4j" start
  )
) else (
  net start neo4j >nul 2>nul
)

rem Windows reports WinError 10013 when this port is already taken by another backend.
powershell -NoProfile -Command "if (Get-NetTCPConnection -State Listen -LocalPort 8081 -ErrorAction SilentlyContinue) { exit 1 } else { exit 0 }" >nul 2>nul
if errorlevel 1 (
  echo [ERROR] Port 8081 is already in use. A backend is probably already running.
  echo         Stop it first: powershell -ExecutionPolicy Bypass -File tools\dev\stop-test-env.ps1
  pause
  exit /b 1
)

echo Backend: http://127.0.0.1:8081  (Ctrl+C to stop)
"%ELEVATOR_PYTHON%" -m uvicorn app.main:app --host 127.0.0.1 --port 8081 --reload
pause
