@echo off
rem cment setup: creates .venv and installs the Python packages. Safe to run again.
cd /d "%~dp0"

set PY=
where py >nul 2>nul && set PY=py -3
if not defined PY where python >nul 2>nul && set PY=python
if not defined PY (
  echo Python 3.11 or newer is not installed.
  echo Install it from https://www.python.org/downloads/ and tick "Add python.exe to PATH".
  pause & exit /b 1
)
%PY% -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)" || (
  echo Python 3.11 or newer is needed. Install it from https://www.python.org/downloads/
  pause & exit /b 1
)

if not exist .venv\Scripts\python.exe (
  echo Creating the Python environment...
  %PY% -m venv .venv || (pause & exit /b 1)
)
echo Installing packages (needs internet the first time)...
.venv\Scripts\python.exe -m pip install --disable-pip-version-check -q -r requirements.txt || (pause & exit /b 1)
if not exist config.toml copy config.example.toml config.toml >nul
echo.
echo Setup complete.
echo   Demo with the simulator:   demo.bat
echo   Real PLC: edit config.toml (PLC IP address), add a user, then run.bat
echo     .venv\Scripts\python -m scada adduser NAME --role operator
