@echo off
echo Stopping any process on port 8765...
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8765 " 2^>nul') do (
    taskkill /PID %%a /F >nul 2>&1
)
timeout /t 1 /nobreak >nul
python ../server.py