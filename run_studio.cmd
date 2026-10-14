@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo Run install_windows.cmd first, or follow docs\windows-v02.md.
    pause
    exit /b 1
)
".venv\Scripts\python.exe" -m xps_studio
if errorlevel 1 (
    echo Startup failed. Copy the error above for diagnosis.
    pause
    exit /b 1
)
