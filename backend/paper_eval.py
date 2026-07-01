"""
F&O paper-month evaluator (read-only, REPORTS ONLY - never flips anything live).
==============================================================================

Reads logs/paper_options_trades.csv (written by options_manager in paper mode),
scores the month against fixed criteria, and sends a PASS/FAIL verdict to the
Telegram bot. It does NOT change PAPER_TRADING, does NOT place orders, does NOT
touch capital. A human (Shivam) decides whether to go live afterward.

CRITERIA (all must hold for PASS):
  (a) n >= MIN_TRADES                          -> enough sample
  (b) net P&L AFTER a slippage haircut > 0     -> survives real-world friction
  (c) annualised net return > CASH_BENCHMARK%  -> beats LIQUIDBEES (~6.5%)
  (d) NOT one-trade-dependent: remove the single best trade, still net > 0
  (e) max peak-to-trough drawdown <= MAX_DD_PCT of bucket

WHY a slippage haircut: paper fills at the live premium with no bid-ask spread
or slippage, which flatters an option BUYER most. We subtract a fixed rupees-per-
unit-per-leg haircut so the verdict is conservative.

USAGE
  python paper_eval.py            # evaluate + send Telegram verdict
  python paper_eval.py --dry      # print verdict, DO NOT send Telegram
  python paper_eval.py --csv PATH # evaluate a specific CSV (for testing)
"""

import argparse
import csv
import os
import sys
from datetime import datetime

# Load .env FIRST, anchored to THIS file's directory, so the script works no
# matter how it's invoked (manual SSH, systemd timer, any cwd). Without this,
# a manual run found no TELEGRAM_BOT_TOKEN and silently skipped the send - the
# exact silent-failure mode this reminder exists to avoid. (2026-06-01 fix)
try:
    from dotenv import load_dotenv
    _ENV = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    load_dotenv(_ENV)
except Exception:  # dotenv missing -> fall back to whatever's already in env
    pass

# --- tunable criteria (kept here so they're auditable in one place) ----------
MIN_TRADES = 15
SLIPPAGE_PER_UNIT_PER_LEG = 4.0   # Rs/unit/leg; entry+exit = 2 legs
CASH_BENCHMARK_PCT = 6.5          # LIQUIDBEES-ish annualised
MAX_DD_PCT = 25.0                 # max tolerable peak-to-trough, % of bucket
# Resolved AFTER load_dotenv so OPTIONS_CAPITAL from .env is picked up.
BUCKET = float(os.getenv("OPTIONS_CAPITAL", "150000"))
WINDOW_DAYS = 30                  # approx paper window for annualisation


def load_trades(path):
    if not os.path.exists(path):
        return []
    rows = []
    with open(path, newline="", encoding="ascii", errors="replace") as fh:
        for r in csv.DictReader(fh):
            try:
                r["net_pnl"] = float(r.get("net_pnl", 0) or 0)
                r["quantity"] = float(r.get("quantity", 0) or 0)
                rows.append(r)
            except (ValueError, TypeError):
                continue  # skip malformed row, keep going
    return rows


def haircut_net(row):
    """Net P&L after subtracting a conservative slippage haircut (2 legs)."""
    legs_cost = SLIPPAGE_PER_UNIT_PER_LEG * row["quantity"] * 2
    return row["net_pnl"] - legs_cost


def max_drawdown(equity):
    """Largest peak-to-trough drop along the cumulative-P&L curve (rupees)."""
    peak = 0.0
    worst = 0.0
    for v in equity:
        peak = max(peak, v)
        worst = min(worst, v - peak)
    return -worst  # positive number = size of the drawdown


def evaluate(rows):
    n = len(rows)
    hc = [haircut_net(r) for r in rows]
    net = sum(hc)
    cum, run = [], 0.0
    for x in hc:
        run += x
        cum.append(run)
    dd = max_drawdown(cum)
    best = max(hc) if hc else 0.0
    net_ex_best = net - best
    ann_pct = (net / BUCKET) * (365.0 / WINDOW_DAYS) * 100 if BUCKET else 0.0

    checks = {
        "a_sample":       (n >= MIN_TRADES,              f"{n} trades (need >= {MIN_TRADES})"),
        "b_net_positive": (net > 0,                      f"net after slippage Rs.{net:+,.0f}"),
        "c_beats_cash":   (ann_pct > CASH_BENCHMARK_PCT, f"annualised {ann_pct:+.1f}% (need > {CASH_BENCHMARK_PCT}%)"),
        "d_not_one_trade":(net_ex_best > 0,              f"net ex-best-trade Rs.{net_ex_best:+,.0f}"),
        "e_drawdown_ok":  (dd <= BUCKET * MAX_DD_PCT/100, f"max DD Rs.{dd:,.0f} (cap Rs.{BUCKET*MAX_DD_PCT/100:,.0f})"),
    }
    verdict = all(ok for ok, _ in checks.values())
    return verdict, checks, dict(n=n, net=net, dd=dd, best=best,
                                 net_ex_best=net_ex_best, ann_pct=ann_pct)


def format_message(verdict, checks, stats):
    head = "PASS" if verdict else "FAIL"
    lines = [
        f"F&O PAPER-MONTH VERDICT: {head}",
        f"SIMULATED bucket Rs.{BUCKET:,.0f} - no real money (F&O is NOT funded in Angel).",
        f"({stats['n']} trades, ~{WINDOW_DAYS}d paper window)",
        "",
    ]
    mark = {True: "OK ", False: "XX "}
    for ok, desc in checks.values():
        lines.append(f"  {mark[ok]}{desc}")
    lines += [
        "",
        "This is a REPORT ONLY. Nothing was changed. Bot is still in PAPER mode.",
        "Come discuss with Claude before going live." if verdict
        else "Criteria not met -> stay paper / revert to Rs.70K. Discuss with Claude.",
    ]
    return "\n".join(lines)


def send_telegram(text):
    """Send to the trading bot. Imports requests lazily; never raises upward."""
    token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    chat = os.getenv("TELEGRAM_CHAT_ID", "")
    if not token or not chat:
        print("WARN: no TELEGRAM_BOT_TOKEN/CHAT_ID; printing instead.")
        print(text)
        return
    try:
        import requests
        resp = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat, "text": text}, timeout=20,
        )
        print("Telegram sent." if resp.ok else f"Telegram failed: {resp.text[:200]}")
    except Exception as e:  # noqa: BLE001
        print(f"Telegram error: {e}\n--- message ---\n{text}")


def format_summary(rows, stats):
    """Lighter weekly progress note (no PASS/FAIL - just where things stand)."""
    wins = sum(1 for r in rows if haircut_net(r) > 0)
    n = stats["n"]
    wr = (100.0 * wins / n) if n else 0.0
    last3 = rows[-3:]
    lines = [
        "F&O PAPER WEEKLY PROGRESS",
        f"SIMULATED bucket Rs.{BUCKET:,.0f} - paper only, no real money.",
        "",
        f"  trades so far : {n}",
        f"  net (after slippage): Rs.{stats['net']:+,.0f}",
        f"  win rate      : {wr:.0f}% ({wins}/{n})",
        f"  best trade    : Rs.{stats['best']:+,.0f}",
        f"  max drawdown  : Rs.{stats['dd']:,.0f}",
        "",
        "  recent:",
    ]
    for r in last3:
        lines.append(f"   {r.get('index','?')} {r.get('type','?')} "
                     f"Rs.{haircut_net(r):+,.0f} ({r.get('exit_reason','?')})")
    lines += ["", "Progress only - nothing changed, still PAPER. "
                  "Final verdict on ~1 Jul. Reply to Claude to discuss early."]
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default="logs/paper_options_trades.csv")
    ap.add_argument("--dry", action="store_true", help="print, do NOT send Telegram")
    ap.add_argument("--summary", action="store_true",
                    help="lighter weekly progress note instead of the PASS/FAIL verdict")
    args = ap.parse_args()

    rows = load_trades(args.csv)
    if not rows:
        what = "WEEKLY PROGRESS" if args.summary else "VERDICT"
        msg = (f"F&O PAPER {what}: NO DATA YET\n"
               f"No closed paper trades in {args.csv} so far. "
               f"Either no signals have closed, or check with Claude.")
        print(msg)
        if not args.dry:
            send_telegram(msg)
        return

    verdict, checks, stats = evaluate(rows)
    msg = format_summary(rows, stats) if args.summary else format_message(verdict, checks, stats)
    print(msg)
    if not args.dry:
        send_telegram(msg)


if __name__ == "__main__":
    main()
