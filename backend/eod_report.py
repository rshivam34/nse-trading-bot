"""
End-of-Day Telegram Report.
============================

Pulls today's trades + portfolio summary from Firebase and pushes a
clean message to your Telegram bot.

Designed to be invoked by a systemd timer at 3:30 PM IST after the bot
has force-exited all positions.

Standalone script — does NOT touch the live trading bot's process.

Required env vars (in backend/.env):
    TELEGRAM_BOT_TOKEN       (from @BotFather)
    TELEGRAM_CHAT_ID         (auto-discovered first time if blank)
    FIREBASE_CREDENTIALS_PATH
    FIREBASE_DATABASE_URL

Usage:
    python eod_report.py             # send today's report
    python eod_report.py --discover  # discover and save your chat_id
    python eod_report.py --test      # send a test message only
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib import request, parse, error

import firebase_admin
from firebase_admin import credentials, db
from dotenv import load_dotenv, set_key

# IST = UTC+5:30
IST = timezone(timedelta(hours=5, minutes=30))


def log(msg: str):
    """Print with timestamp."""
    print(f"[{datetime.now(IST).strftime('%H:%M:%S')}] {msg}", flush=True)


def load_env():
    """Load .env from this script's folder."""
    env_path = Path(__file__).parent / ".env"
    if not env_path.exists():
        log(f"ERROR: .env not found at {env_path}")
        sys.exit(1)
    load_dotenv(env_path)
    return env_path


def telegram_post(token: str, method: str, payload: dict) -> dict:
    """POST to Telegram Bot API. Returns response JSON."""
    url = f"https://api.telegram.org/bot{token}/{method}"
    data = parse.urlencode(payload).encode()
    req = request.Request(url, data=data, method="POST")
    try:
        with request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode())
    except error.HTTPError as e:
        log(f"Telegram HTTP {e.code}: {e.read().decode()}")
        raise
    except Exception as e:
        log(f"Telegram error: {e}")
        raise


def discover_chat_id(token: str, env_path: Path) -> str:
    """
    Find user's chat_id from /getUpdates.
    User must have sent /start (or any message) to the bot first.
    """
    log("Discovering chat_id via getUpdates...")
    url = f"https://api.telegram.org/bot{token}/getUpdates"
    with request.urlopen(url, timeout=15) as resp:
        data = json.loads(resp.read().decode())

    if not data.get("ok"):
        log(f"Telegram API error: {data}")
        sys.exit(1)

    updates = data.get("result", [])
    if not updates:
        log("No messages received yet. Open Telegram, find your bot, and send /start.")
        log("Then re-run: python eod_report.py --discover")
        sys.exit(1)

    # Take chat_id from latest update
    chat_id = str(updates[-1]["message"]["chat"]["id"])
    name = updates[-1]["message"]["chat"].get("first_name", "")
    log(f"Found chat_id: {chat_id} (user: {name})")

    set_key(str(env_path), "TELEGRAM_CHAT_ID", chat_id)
    log(f"Saved to {env_path}")
    return chat_id


def init_firebase():
    """Initialize Firebase using credentials from .env."""
    cred_path = os.getenv("FIREBASE_CREDENTIALS_PATH", "firebase-credentials.json")
    db_url = os.getenv("FIREBASE_DATABASE_URL")

    if not Path(cred_path).is_absolute():
        cred_path = str(Path(__file__).parent / cred_path)

    if not Path(cred_path).exists():
        log(f"ERROR: Firebase credentials not found at {cred_path}")
        sys.exit(1)
    if not db_url:
        log("ERROR: FIREBASE_DATABASE_URL not set in .env")
        sys.exit(1)

    if not firebase_admin._apps:
        cred = credentials.Certificate(cred_path)
        firebase_admin.initialize_app(cred, {"databaseURL": db_url})
    log("Firebase connected")


def fetch_today_trades() -> list[dict]:
    """Pull /trades from Firebase, filter to today (IST)."""
    today = datetime.now(IST).strftime("%Y-%m-%d")
    trades_ref = db.reference("/trades")
    all_trades = trades_ref.get() or {}

    today_trades = []
    for trade_id, trade in all_trades.items():
        if not isinstance(trade, dict):
            continue
        # Try several common date field names
        date_fields = ["date", "exit_date", "trade_date", "entry_date"]
        trade_date = None
        for f in date_fields:
            v = trade.get(f, "")
            if v and isinstance(v, str) and v.startswith(today):
                trade_date = v
                break
        # Also accept trades where exit_time contains today
        if not trade_date:
            for f in ["exit_time", "entry_time", "timestamp"]:
                v = trade.get(f, "")
                if v and isinstance(v, str) and today in v:
                    trade_date = v
                    break
        if trade_date:
            today_trades.append(trade)
    return today_trades


def fetch_portfolio() -> dict:
    """Pull /portfolio from Firebase."""
    p = db.reference("/portfolio").get() or {}
    return p if isinstance(p, dict) else {}


def fetch_status() -> dict:
    """Pull /status + /market_context for context."""
    return {
        "status": db.reference("/status").get() or {},
        "market": db.reference("/market_context").get() or {},
        "premarket": db.reference("/premarket_status").get() or {},
    }


def format_report(trades: list[dict], portfolio: dict, ctx: dict) -> str:
    """Build the Telegram message. Uses HTML parse mode."""
    today = datetime.now(IST).strftime("%a, %d %b %Y")

    lines = []
    lines.append(f"<b>NSE Bot - {today}</b>")
    lines.append("")

    # Mode — be explicit that F&O is a SIMULATED paper test (no real money), so the
    # report is never misread as live trading at the Rs.1.5L paper-bucket size.
    paper = os.getenv("PAPER_TRADING", "False").lower() == "true"
    if paper:
        bucket = os.getenv("OPTIONS_CAPITAL", "").strip()
        try:
            bucket_str = f" — Rs.{float(bucket):,.0f} simulated" if bucket else ""
        except ValueError:
            bucket_str = ""
        lines.append(
            f"Mode: <b>🟡 PAPER TEST</b>{bucket_str} (no real money; "
            f"real Rs.70K F&amp;O paused, verdict ~1 Jul)"
        )
    else:
        lines.append("Mode: <b>🟢 LIVE</b> (real money)")

    # Market context
    market = ctx.get("market", {}) or {}
    if market:
        nifty_dir = market.get("nifty_direction", "?")
        vix = market.get("vix", "?")
        regime = market.get("vix_regime", "")
        lines.append(f"Market: NIFTY {nifty_dir} | VIX {vix} {regime}".rstrip())

    lines.append("")

    if not trades:
        lines.append("No trades today.")
    else:
        wins = [t for t in trades if (t.get("net_pnl") or t.get("net") or 0) > 0]
        losses = [t for t in trades if (t.get("net_pnl") or t.get("net") or 0) <= 0]

        net_total = sum((t.get("net_pnl") or t.get("net") or 0) for t in trades)
        gross_total = sum((t.get("gross_pnl") or t.get("gross") or 0) for t in trades)
        charges_total = sum((t.get("charges") or 0) for t in trades)

        lines.append(f"Trades: <b>{len(trades)}</b> ({len(wins)}W / {len(losses)}L)")
        lines.append(f"Gross: Rs.{gross_total:+,.2f}")
        lines.append(f"Charges: Rs.{charges_total:,.2f}")
        lines.append(f"<b>Net P&amp;L: Rs.{net_total:+,.2f}</b>")
        lines.append("")
        lines.append("<b>Trade detail:</b>")
        for t in trades:
            sym = t.get("stock") or t.get("symbol") or t.get("index") or "?"
            direction = t.get("direction") or t.get("type") or ""
            entry = t.get("entry_price") or t.get("entry_premium") or 0
            exit_p = t.get("exit_price") or t.get("exit_premium") or 0
            net = t.get("net_pnl") or t.get("net") or 0
            reason = t.get("exit_reason") or ""
            lines.append(f"  {sym} {direction} @ {entry:.1f} -> {exit_p:.1f} | <b>Rs.{net:+,.0f}</b> ({reason})")

    # Portfolio
    if portfolio:
        lines.append("")
        cap = portfolio.get("current_capital", 0)
        day_pnl = portfolio.get("day_pnl", 0)
        starting = portfolio.get("starting_capital") or portfolio.get("initial_capital", 0)
        lines.append(f"Capital: <b>Rs.{cap:,.2f}</b>")
        if starting:
            ret_pct = (cap - starting) / starting * 100
            lines.append(f"Total return: {ret_pct:+.2f}% (from Rs.{starting:,.0f})")

    # Bot status
    bot_status = ctx.get("status", {}) or {}
    if bot_status:
        running = bot_status.get("running", False)
        lines.append("")
        lines.append(f"Bot: {'RUNNING' if running else 'STOPPED'}")

    lines.append("")
    lines.append(f"<i>Report sent at {datetime.now(IST).strftime('%H:%M IST')}</i>")
    return "\n".join(lines)


def send_message(token: str, chat_id: str, text: str):
    """Send message via Telegram."""
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
    resp = telegram_post(token, "sendMessage", payload)
    if resp.get("ok"):
        log("Telegram message sent OK")
    else:
        log(f"Telegram send failed: {resp}")
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--discover", action="store_true", help="Discover and save your chat_id")
    parser.add_argument("--test", action="store_true", help="Send a test message")
    args = parser.parse_args()

    env_path = load_env()
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        log("ERROR: TELEGRAM_BOT_TOKEN not set in .env")
        sys.exit(1)

    if args.discover:
        discover_chat_id(token, env_path)
        return

    chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    if not chat_id:
        chat_id = discover_chat_id(token, env_path)

    if args.test:
        msg = f"<b>Test message</b>\nNSE bot reporter is wired up.\n{datetime.now(IST).strftime('%Y-%m-%d %H:%M IST')}"
        send_message(token, chat_id, msg)
        return

    init_firebase()
    trades = fetch_today_trades()
    portfolio = fetch_portfolio()
    ctx = fetch_status()
    text = format_report(trades, portfolio, ctx)
    log(f"Report ({len(text)} chars):\n{text}")
    send_message(token, chat_id, text)


if __name__ == "__main__":
    main()
