"""
F&O-Only Backtest with VIX cutoff = 20 (vs default 18).
=========================================================

Reports day-by-day:
  - VIX value
  - NIFTY + BANKNIFTY ORB range %
  - Signal / no-signal (and reason)
  - Trade outcome + net P&L

Reuses the existing NiftyOptionsStrategy + Backtester data fetchers.

Usage:
    python backtest_fno_vix20.py
    python backtest_fno_vix20.py --vix 22         # try a different cutoff
    python backtest_fno_vix20.py --days 90        # try a different period
"""

import argparse
import sys
from collections import defaultdict
from datetime import datetime, timedelta, time as dtime

# Force UTF-8 output on Windows console (cp1252 default chokes on arrows/box-chars)
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

# ── STEP 1: Parse args BEFORE importing config-dependent modules ──────────
parser = argparse.ArgumentParser()
parser.add_argument("--vix", type=float, default=20.0, help="VIX cutoff (default 20)")
parser.add_argument("--days", type=int, default=62, help="Look-back days (default 62)")
args = parser.parse_args()

VIX_CUTOFF = args.vix
LOOKBACK_DAYS = args.days

# ── STEP 2: Override config BEFORE Backtester reads it ────────────────────
from config import config
ORIGINAL_THRESHOLD = config.trading.vix_caution_threshold
config.trading.vix_caution_threshold = VIX_CUTOFF  # patches the F&O gate

from backtest import Backtester
from strategies.options_strategy import NiftyOptionsStrategy

# ── STEP 3: Setup ─────────────────────────────────────────────────────────
print("=" * 100)
print(f"  F&O BACKTEST  |  VIX cutoff: {VIX_CUTOFF}  (was {ORIGINAL_THRESHOLD} in config)")
print("=" * 100)

bt = Backtester()
end = datetime.now().strftime("%Y-%m-%d")
start = (datetime.now() - timedelta(days=LOOKBACK_DAYS)).strftime("%Y-%m-%d")
print(f"  Period:        {start}  to  {end}  ({LOOKBACK_DAYS} calendar days)")
print(f"  Capital:       Rs.{bt.capital:,.0f}")
print(f"  NIFTY lot:     25  |  BANKNIFTY lot: 15")
print(f"  SL: 30% prem loss  |  Target: 50% prem gain  |  Time exit: 2 PM IST\n")

# ── STEP 4: Fetch data ────────────────────────────────────────────────────
print("Fetching data (yfinance - may take ~30 sec)...")
vix_daily = bt._fetch_vix_daily(start, end)
nifty_5m = bt._fetch_5m_candles("^NSEI", start, end)
banknifty_5m = bt._fetch_5m_candles("^NSEBANK", start, end)

if nifty_5m is None or len(nifty_5m) == 0:
    print("ERROR: No NIFTY data. Try a smaller --days value.")
    sys.exit(1)

print(f"  VIX daily:     {len(vix_daily)} days")
print(f"  NIFTY 5m:      {len(nifty_5m)} candles")
print(f"  BANKNIFTY 5m:  {len(banknifty_5m) if banknifty_5m is not None else 0} candles\n")

# Trading days from data
trading_days = sorted(set(nifty_5m.index.date))
start_dt = datetime.strptime(start, "%Y-%m-%d").date()
end_dt = datetime.strptime(end, "%Y-%m-%d").date()
trading_days = [d for d in trading_days if start_dt <= d <= end_dt]
print(f"Trading days available: {len(trading_days)}\n")


# ── STEP 5: Run F&O simulation per index per day, collect details ─────────
NIFTY_LOT = 25
BANKNIFTY_LOT = 15

# Per-day per-index records — for full transparency
records = []   # (day, index, vix, orb_range_pct, status, trade_dict_or_None)
all_trades = []

for index_name, index_data, lot_size, strike_interval, atm_delta in [
    ("NIFTY",     nifty_5m,     NIFTY_LOT,     50,  0.50),
    ("BANKNIFTY", banknifty_5m, BANKNIFTY_LOT, 100, 0.55),
]:
    if index_data is None or len(index_data) == 0:
        continue

    for day in trading_days:
        vix = vix_daily.get(day, 15.0)

        # Day-level VIX gate (this is the variable we're testing)
        if vix >= VIX_CUTOFF:
            records.append((day, index_name, vix, 0.0, f"VIX-SKIP ({vix:.1f} >= {VIX_CUTOFF})", None))
            continue

        # NIFTY: 0.2-1.5% ORB range  |  BANKNIFTY: 0.2-3.0% (more volatile)
        max_rng = 1.5 if index_name == "NIFTY" else 3.0
        opt_strategy = NiftyOptionsStrategy(bt.trading_config, min_range_pct=0.2, max_range_pct=max_rng)

        day_candles = index_data[index_data.index.date == day]
        if len(day_candles) < 10:
            records.append((day, index_name, vix, 0.0, "INSUFFICIENT-DATA", None))
            continue

        opt_strategy.reset_daily()

        # ORB range from first 3 candles (9:15-9:30 IST)
        orb_candles = day_candles.iloc[:3]
        orb_high = float(orb_candles["High"].max())
        orb_low = float(orb_candles["Low"].min())
        orb_range_pct = (orb_high - orb_low) / orb_low * 100
        opt_strategy.set_orb_range(orb_high, orb_low)

        # Range filter — same as live bot
        if orb_range_pct < 0.2:
            records.append((day, index_name, vix, orb_range_pct, "ORB-TOO-TIGHT (<0.2%)", None))
            continue
        if orb_range_pct > max_rng:
            records.append((day, index_name, vix, orb_range_pct, f"ORB-TOO-WIDE (>{max_rng}%)", None))
            continue

        # Walk through the day — look for breakout-retest signal, manage position
        option_pos = None
        trade_done = None

        for i in range(3, len(day_candles)):
            candle = day_candles.iloc[i]
            ist_time = (day_candles.index[i] + timedelta(hours=5, minutes=30)).time()
            ltp = float(candle["Close"])

            if option_pos is None:
                # Entry only allowed during ORB window (9:30-10:15)
                if ist_time > dtime(10, 15):
                    continue
                signal = opt_strategy.check_signal(day_candles.iloc[:i + 1], vix=vix)
                if signal:
                    # Premium estimate via Black-Scholes approximation (same as live backtester)
                    spot = ltp
                    sigma = max(vix, 12) / 100              # annualized vol from VIX
                    days_to_expiry = 3                       # weekly options avg
                    time_factor = (days_to_expiry / 365) ** 0.5
                    est_premium = round(spot * sigma * time_factor * 0.4, 1)
                    est_premium = max(30, min(est_premium, 500))   # clamp
                    option_pos = {
                        "type": signal.direction,
                        "entry_premium": est_premium,
                        "entry_index": ltp,
                        "sl_premium": est_premium * 0.7,
                        "target_premium": est_premium * 1.5,
                        "strike": signal.strike,
                        "entry_time": ist_time.strftime("%H:%M"),
                        "entry_idx_level": ltp,
                    }
            else:
                # Track premium via index-move × delta approximation
                index_move = ltp - option_pos["entry_index"]
                if option_pos["type"] == "PUT":
                    index_move = -index_move
                premium_change = index_move * atm_delta
                current_premium = option_pos["entry_premium"] + premium_change

                exit_reason = None
                exit_premium = None

                if current_premium <= option_pos["sl_premium"]:
                    exit_reason = "SL"
                    exit_premium = option_pos["sl_premium"]
                elif current_premium >= option_pos["target_premium"]:
                    exit_reason = "TARGET"
                    exit_premium = option_pos["target_premium"]
                elif ist_time >= dtime(14, 0):
                    exit_reason = "TIME_EXIT"
                    exit_premium = current_premium

                if exit_reason:
                    gross = (exit_premium - option_pos["entry_premium"]) * lot_size
                    charges = lot_size * option_pos["entry_premium"] * 0.001  # ~0.1% options charges
                    trade_done = {
                        "date": day,
                        "index": index_name,
                        "type": option_pos["type"],
                        "strike": option_pos["strike"],
                        "entry_premium": option_pos["entry_premium"],
                        "exit_premium": round(exit_premium, 1),
                        "lot_size": lot_size,
                        "gross": round(gross, 2),
                        "charges": round(charges, 2),
                        "net": round(gross - charges, 2),
                        "exit_reason": exit_reason,
                        "entry_time": option_pos["entry_time"],
                        "exit_time": ist_time.strftime("%H:%M"),
                        "index_entry": option_pos["entry_idx_level"],
                        "index_exit": ltp,
                    }
                    option_pos = None
                    break  # one trade per index per day

        # Force-close at end of day if still open
        if option_pos is not None:
            last_ltp = float(day_candles["Close"].iloc[-1])
            index_move = last_ltp - option_pos["entry_index"]
            if option_pos["type"] == "PUT":
                index_move = -index_move
            premium_change = index_move * atm_delta
            current_premium = option_pos["entry_premium"] + premium_change
            gross = (current_premium - option_pos["entry_premium"]) * lot_size
            charges = lot_size * option_pos["entry_premium"] * 0.001
            trade_done = {
                "date": day,
                "index": index_name,
                "type": option_pos["type"],
                "strike": option_pos["strike"],
                "entry_premium": option_pos["entry_premium"],
                "exit_premium": round(current_premium, 1),
                "lot_size": lot_size,
                "gross": round(gross, 2),
                "charges": round(charges, 2),
                "net": round(gross - charges, 2),
                "exit_reason": "FORCE_EXIT",
                "entry_time": option_pos["entry_time"],
                "exit_time": "15:30",
                "index_entry": option_pos["entry_idx_level"],
                "index_exit": last_ltp,
            }

        # Categorize the day's outcome
        if trade_done:
            all_trades.append(trade_done)
            status = (
                f"{trade_done['type']} {trade_done['strike']:.0f} -> "
                f"{trade_done['exit_reason']} (Rs.{trade_done['net']:+.0f})"
            )
            records.append((day, index_name, vix, orb_range_pct, status, trade_done))
        else:
            records.append((day, index_name, vix, orb_range_pct, "NO-BREAKOUT-RETEST", None))


# ── STEP 6: Print day-by-day report ───────────────────────────────────────
print("=" * 100)
print("  DAY-BY-DAY  (each day shows NIFTY then BANKNIFTY)")
print("=" * 100)
print(f"  {'Date':<14} {'Index':<10} {'VIX':>5} {'ORB%':>6}  {'Outcome'}")
print("  " + "-" * 95)

# group by date for readability
by_date = defaultdict(list)
for rec in records:
    by_date[rec[0]].append(rec)

for day in trading_days:
    rows = sorted(by_date[day], key=lambda r: r[1])  # NIFTY before BANKNIFTY alphabetically
    for (d, idx, vix, orb, status, _) in rows:
        date_str = d.strftime("%Y-%m-%d %a")
        orb_str = f"{orb:.2f}" if orb > 0 else "  -  "
        print(f"  {date_str:<14} {idx:<10} {vix:>5.1f} {orb_str:>6}  {status}")

# ── STEP 7: Trades-only table ─────────────────────────────────────────────
print("\n" + "=" * 110)
print("  TRADES TAKEN")
print("=" * 110)
if all_trades:
    print(f"  {'#':<3} {'Date':<14} {'Index':<10} {'Type':<5} {'Strike':>7} "
          f"{'EntPrm':>7} {'ExtPrm':>7} {'Lot':>4} {'Gross':>10} "
          f"{'Charges':>9} {'Net':>10} {'In/Out':<12} {'Reason':<10}")
    print("  " + "-" * 125)
    running = 0.0
    for i, t in enumerate(all_trades, 1):
        running += t["net"]
        print(
            f"  {i:<3} {t['date'].strftime('%Y-%m-%d %a'):<14} {t['index']:<10} "
            f"{t['type']:<5} {t['strike']:>7.0f} {t['entry_premium']:>7.1f} "
            f"{t['exit_premium']:>7.1f} {t['lot_size']:>4} "
            f"{t['gross']:>+10.2f} {t['charges']:>9.2f} {t['net']:>+10.2f} "
            f"{t['entry_time']+'->'+t['exit_time']:<12} {t['exit_reason']:<10}"
        )
    print("  " + "-" * 125)
else:
    print("  No trades fired in this period.")


# ── STEP 8: Summary ───────────────────────────────────────────────────────
print("\n" + "=" * 100)
print("  SUMMARY")
print("=" * 100)

total_gross = sum(t["gross"] for t in all_trades)
total_charges = sum(t["charges"] for t in all_trades)
total_net = sum(t["net"] for t in all_trades)
wins = sum(1 for t in all_trades if t["net"] > 0)
losses = len(all_trades) - wins

# Day-level metrics: each day has 2 rows (NIFTY+BANKNIFTY) — count distinct days
total_days = len(trading_days)
vix_skipped_days = sum(1 for d in trading_days if vix_daily.get(d, 15.0) >= VIX_CUTOFF)
tradeable_days = total_days - vix_skipped_days

print(f"  Period:                 {start} to {end}")
print(f"  VIX cutoff used:        {VIX_CUTOFF}  (config default: 18.0)")
print(f"  Total trading days:     {total_days}")
print(f"  Days with VIX >= {VIX_CUTOFF:<4}: {vix_skipped_days}  (auto-skipped)")
print(f"  Tradeable days:         {tradeable_days}")
print()
print(f"  Total trades:           {len(all_trades)}")
if all_trades:
    print(f"  Wins:                   {wins}  ({wins * 100 // len(all_trades)}%)")
    print(f"  Losses:                 {losses}")
    print(f"  Avg net per trade:      Rs.{total_net / len(all_trades):+,.2f}")
print(f"  Gross P&L:              Rs.{total_gross:+,.2f}")
print(f"  Charges:                Rs.{total_charges:,.2f}")
print(f"  NET P&L:                Rs.{total_net:+,.2f}")
print(f"  Return on Rs.30K cap:   {total_net / 30000 * 100:+.2f}%")

if all_trades:
    by_index = defaultdict(lambda: {"trades": 0, "net": 0.0, "wins": 0})
    for t in all_trades:
        by_index[t["index"]]["trades"] += 1
        by_index[t["index"]]["net"] += t["net"]
        if t["net"] > 0:
            by_index[t["index"]]["wins"] += 1
    print(f"\n  Breakdown by index:")
    for idx, d in sorted(by_index.items()):
        wr = d["wins"] * 100 // max(d["trades"], 1)
        print(f"    {idx:<12} {d['trades']:>3} trades, {wr:>3}% win, net Rs.{d['net']:+,.2f}")

    by_exit = defaultdict(int)
    by_exit_pnl = defaultdict(float)
    for t in all_trades:
        by_exit[t["exit_reason"]] += 1
        by_exit_pnl[t["exit_reason"]] += t["net"]
    print(f"\n  Exit-reason breakdown:")
    for reason in sorted(by_exit.keys()):
        print(f"    {reason:<12} {by_exit[reason]:>3}   net Rs.{by_exit_pnl[reason]:+,.2f}")

# Compare against the VIX 18 default
print(f"\n  ----------------------------------------------------------------")
print(f"  Note: the live bot currently uses VIX cutoff 18.0.")
print(f"  This run lifted the gate to {VIX_CUTOFF} - meaning {vix_skipped_days} fewer days were auto-skipped.")
print(f"  ----------------------------------------------------------------\n")
