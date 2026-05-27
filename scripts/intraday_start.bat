@echo off
REM ============================================
REM NSE Intraday Trading Bot - Daily Auto-Start
REM Runs at 8:45 AM on market days (Mon-Fri)
REM Bot runs continuously until 3:30 PM then auto-shuts down
REM ============================================

cd /d C:\Users\rshiv\shivam-future-plans\trading\nse-trading-bot\backend

REM Skip weekends
for /f %%a in ('powershell -command "(Get-Date).DayOfWeek"') do set DOW=%%a
if "%DOW%"=="Saturday" goto :skip
if "%DOW%"=="Sunday" goto :skip

REM Skip NSE holidays 2026
set TODAY=%date:~10,4%-%date:~4,2%-%date:~7,2%
echo %TODAY% | findstr /i "2026-01-26 2026-02-17 2026-03-03 2026-03-10 2026-03-30 2026-04-02 2026-04-03 2026-04-14 2026-04-18 2026-05-01 2026-05-25 2026-06-26 2026-07-07 2026-08-15 2026-08-19 2026-09-04 2026-10-02 2026-10-20 2026-10-21 2026-11-09 2026-11-10 2026-11-27 2026-12-25" > nul
if %errorlevel%==0 goto :skip

echo.
echo ============================================
echo  NSE INTRADAY BOT - Starting at %time%
echo  Mode: LIVE (from .env)
echo  Bot will run until 3:30 PM then auto-stop
echo ============================================
echo.

echo [%date% %time%] Intraday bot starting... >> ..\logs\scheduler.log

REM Run the bot (it runs continuously until market close)
REM Uses --live flag to ensure live trading mode
C:\Users\rshiv\AppData\Local\Programs\Python\Python313\python.exe main.py --live

echo [%date% %time%] Intraday bot stopped. >> ..\logs\scheduler.log
goto :end

:skip
echo [%date% %time%] Intraday bot skipped (weekend or holiday) >> ..\logs\scheduler.log

:end
