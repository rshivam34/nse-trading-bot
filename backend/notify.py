"""
Telegram notification hooks for systemd.
==========================================

Called by systemd in two situations:
  - notify.py started   -> sent right after the bot process launches
  - notify.py failed    -> sent if the service goes into 'failed' state
                           (after Restart=on-failure exhausts retries)

Standalone, dependency-light. Reads token + chat_id from backend/.env.
"""

import json
import os
import subprocess
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib import parse, request
from dotenv import load_dotenv

IST = timezone(timedelta(hours=5, minutes=30))


def send(msg: str) -> None:
    env = Path(__file__).parent / ".env"
    load_dotenv(env)
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat:
        print("Telegram creds missing - skipping notify", file=sys.stderr)
        return
    data = parse.urlencode({"chat_id": chat, "text": msg, "parse_mode": "HTML"}).encode()
    req = request.Request(f"https://api.telegram.org/bot{token}/sendMessage", data=data, method="POST")
    try:
        with request.urlopen(req, timeout=15) as r:
            json.loads(r.read().decode())
    except Exception as e:
        print(f"Telegram send failed: {e}", file=sys.stderr)


def get_log_tail(lines: int = 25, max_chars: int = 1500) -> str:
    try:
        out = subprocess.check_output(
            ["journalctl", "-u", "nse-bot.service", "-n", str(lines), "--no-pager"],
            stderr=subprocess.STDOUT,
            timeout=10,
        ).decode()
        return out[-max_chars:]
    except Exception as e:
        return f"(couldn't fetch journal: {e})"


def main():
    if len(sys.argv) < 2:
        print("Usage: notify.py {started|failed}", file=sys.stderr)
        sys.exit(1)

    action = sys.argv[1].lower()
    now = datetime.now(IST).strftime("%H:%M IST on %a %d %b")
    load_dotenv(Path(__file__).parent / ".env")  # so PAPER_TRADING is readable here

    if action == "started":
        paper = os.getenv("PAPER_TRADING", "False").strip().lower() == "true"
        mode_note = " <i>(F&amp;O PAPER test — no real orders)</i>" if paper else ""
        msg = (
            f"<b>NSE Bot started OK</b>{mode_note}\n"
            f"Process launched at {now}.\n"
            f"EOD report will land at 15:30 IST."
        )
    elif action == "failed":
        log_tail = get_log_tail()
        msg = (
            f"<b>NSE Bot CRASHED</b>\n"
            f"Service entered failed state at {now}.\n\n"
            f"<pre>{log_tail}</pre>"
        )
    else:
        print(f"Unknown action: {action}", file=sys.stderr)
        sys.exit(1)

    send(msg)


if __name__ == "__main__":
    main()
