@echo off
setlocal
set "ETF_DIRECT=1"

cd /d "%~dp0"
if errorlevel 1 (
    echo [ERROR] Cannot enter the project directory.
    pause
    exit /b 1
)

set "PYTHON_EXE=D:\Anaconda3\envs\QuaTra\python.exe"
if not exist "%PYTHON_EXE%" (
    echo [ERROR] QuaTra Python was not found:
    echo %PYTHON_EXE%
    pause
    exit /b 1
)

powershell -NoProfile -Command "if (Get-NetTCPConnection -LocalAddress 127.0.0.1 -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue) { exit 0 } else { exit 1 }" >nul 2>&1
if not errorlevel 1 goto :port_busy

echo Starting ETF Market Dashboard with QuaTra...
start "" "http://127.0.0.1:8000/web/"
"%PYTHON_EXE%" -m uvicorn server:app --host 127.0.0.1 --port 8000

echo.
echo Server stopped.
pause
exit /b

:port_busy
powershell -NoProfile -Command "try { $r = Invoke-RestMethod 'http://127.0.0.1:8000/api/health' -TimeoutSec 3; if ($null -ne $r.snapshot_id) { exit 0 } else { exit 1 } } catch { exit 1 }" >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Port 8000 is used by another program.
    echo Close that program or run Uvicorn on a different port.
    pause
    exit /b 1
)
echo ETF Market Dashboard is already running on port 8000.
start "" "http://127.0.0.1:8000/web/"
exit /b 0
