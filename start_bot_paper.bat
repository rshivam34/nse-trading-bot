@echo off
REM ====================================================================
REM NSE Intraday Trading Bot — Paper Mode Launcher
REM
REM Auto-launched daily at 8:55 AM IST by Windows Task Scheduler.
REM Bot self-handles weekends + NSE holidays (returns early).
REM Logs go to backend\logs\trading_bot_YYYY-MM-DD.log
REM
REM To run manually: just double-click this file.
REM To stop: close the terminal window OR press Ctrl+C.
REM ====================================================================

cd /d "C:\Users\rshiv\nse-trading-bot\backend"

REM Activate venv if it exists, otherwise use system Python
if exist "..\venv\Scripts\activate.bat" (
    call "..\venv\Scripts\activate.bat"
)

echo.
echo =====================================================================
echo  NSE Intraday Trading Bot — Paper Mode
echo  Started: %date% %time%
echo =====================================================================
echo.

python main.py --paper

echo.
echo =====================================================================
echo  Bot exited: %date% %time%
echo =====================================================================

REM Keep window open for 30 seconds so you can read final output
timeout /t 30 /nobreak > nul
