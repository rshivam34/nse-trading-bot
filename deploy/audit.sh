#!/usr/bin/env bash
LOG=/home/ubuntu/nse-trading-bot/backend/logs/trading_bot_2026-05-07.log
[ ! -f "$LOG" ] && { echo "No log for today yet"; exit 0; }
echo "Log lines: $(wc -l < $LOG)"
echo "EXECUTED:  $(grep -c EXECUTED $LOG)"
echo "QUALIFIED: $(grep -c QUALIFIED $LOG)"
echo "SKIPPED:   $(grep -c SKIPPED $LOG)"
echo "Real errors (excl yfinance): $(grep -E 'ERROR|CRITICAL' $LOG | grep -vE 'yfinance|CNXFINANCE' | wc -l)"
echo
echo "--- Last 8 INFO lines ---"
grep INFO $LOG | tail -8
