@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    py -3.12 -m venv .venv
    if errorlevel 1 goto failure
)
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto failure
".venv\Scripts\python.exe" -m pip install --no-deps -e .
if errorlevel 1 goto failure
echo Setup complete. Run run_studio.cmd to start XPS Analysis Studio.
pause
exit /b 0
:failure
echo Setup failed. Check the error above. Python 3.12 x64 and Internet access are required.
pause
exit /b 1
