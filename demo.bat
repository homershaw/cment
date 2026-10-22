@echo off
rem cment demo: starts the simulated PLC and the SCADA, then opens the browser.
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe call setup.bat || exit /b 1

.venv\Scripts\python.exe -m scada --config config.demo.toml adduser demo --role operator --password demo123 >nul
start "cment simulator - close to stop" .venv\Scripts\python.exe -m sim --port 1102 --auto 30 --faults
timeout /t 2 /nobreak >nul
start "" http://localhost:8080
echo.
echo cment demo: http://localhost:8080   (log in as demo / demo123 for batch control)
echo Other PCs on the network: http://%COMPUTERNAME%:8080
echo Close this window and the simulator window to stop.
echo.
.venv\Scripts\python.exe -m scada --config config.demo.toml
