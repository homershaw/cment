@echo off
rem cment: run against the real PLC set in config.toml.
cd /d "%~dp0"
.venv\Scripts\python.exe -c "" >nul 2>nul || call "%~dp0setup.bat" || exit /b 1
if not exist config.toml copy config.example.toml config.toml >nul
start "" http://localhost:8080
.venv\Scripts\python.exe -m scada --config config.toml %*
