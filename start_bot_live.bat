@echo off
REM ====================================================================
REM NSE Intraday Trading Bot — LIVE MODE (REAL MONEY)
REM
REM ⚠️  THIS PLACES REAL F&O OPTION ORDERS WITH REAL MONEY  ⚠️
REM
REM Capital: Rs.50,000 (set in .env: INITIAL_CAPITAL=50000)
REM Mode: F&O-ONLY (equity_enabled=False in config.py)
REM Auto-scaling lots: enabled (multi-lot per trade based on capital)
REM
REM Auto-launched daily at 8:55 AM IST by Windows Task Scheduler.
REM Bot self-handles weekends + NSE holidays (returns early).
REM Logs go to backend\logs\trading_bot_YYYY-MM-DD.log
REM
REM EMERGENCY STOP:
REM   1. Click the dashboard's "Kill Switch" button (Firebase /kill_switch)
REM   2. OR close this terminal window (Ctrl+C)
REM   3. OR run: powershell.exe Stop-ScheduledTask -TaskName "NSE-IntradayBot-Live"
REM
REM To revert to paper mode:
REM   1. Edit .env: PAPER_TRADING=True
REM   2. Edit this file: change --live to --paper
REM ====================================================================

cd /d "C:\Users\rshiv\nse-trading-bot\backend"

if exist "..\venv\Scripts\activate.bat" (
    call "..\venv\Scripts\activate.bat"
)

echo.
echo =====================================================================
echo  NSE Intraday Trading Bot — LIVE MODE (REAL MONEY)
echo  Capital: Rs.30,000 (F^&O only)
echo  Started: %date% %time%
echo =====================================================================
echo.
echo  Pre-flight:
echo    - WireGuard VPN must be ACTIVE (IP should be 80.225.252.67)
echo    - Check https://whatismyipaddress.com to verify before continuing
echo.
echo  WARNING: This places REAL orders with REAL money.
echo  Maximum daily loss: ~3%% of capital (Rs.900) per risk manager.
echo  Maximum 4 F^&O trades per day, 30%% premium SL per trade.
echo.

python main.py --live

echo.
echo =====================================================================
echo  Bot exited: %date% %time%
echo =====================================================================

timeout /t 30 /nobreak > nul
