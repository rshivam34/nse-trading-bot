"""
12-Month Intraday Backtester — uses cached Angel One 5-min data
=================================================================
Reads pickled DataFrames produced by fetch_angel_historical.py.
Runs three modes side-by-side:
  1. F&O-only (NIFTY/BANKNIFTY ORB-retest)
  2. Equity-only (4 strategies on stocks)
  3. Combined (both)

Outputs Month-over-Month (MoM) breakdown for each mode.

Requires the cache to exist (run fetch_angel_historical.py first).

Usage:
  cd C:\\Users\\rshiv\\nse-trading-bot\\backend
  python backtest_12m.py
  python backtest_12m.py --capital 100000   # override capital
"""

import argparse
import logging
import sys
import warnings
from collections import defaultdict
from datetime import datetime, timedelta, time as dt_time
from pathlib import Path

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
logging.basicConfig(level=logging.WARNING, format="%(message)s")

sys.path.insert(0, str(Path(__file__).parent))
from config import config
from utils.brokerage import calculate_charges
from utils.indicators import get_current_atr, get_current_choppiness, is_atr_expanding
from core.signal_scorer import SignalScorer
from strategies.orb_strategy import ORBStrategy
from strategies.options_strategy import NiftyOptionsStrategy

# ===================== Settings =====================
CACHE_DIR = Path("logs/historical_5min")
DEFAULT_CAPITAL = config.trading.initial_capital  # 50000

NIFTY_LOT = config.trading.nifty_lot_size
BANKNIFTY_LOT = config.trading.banknifty_lot_size
ATM_DELTA = 0.50
BANKNIFTY_DELTA = 0.55

VIX_DANGER = config.trading.vix_caution_threshold  # 18.0


# ===================== Data Classes =====================
class Trade:
    def __init__(self, date, kind, symbol, direction, entry, exit, qty, gross, charges, exit_reason):
        self.date = date
        self.kind = kind  # "EQUITY" or "OPTION"
        self.symbol = symbol
        self.direction = direction
        self.entry_price = entry
        self.exit_price = exit
        self.qty = qty
        self.gross_pnl = gross
        self.charges = charges
        self.net_pnl = gross - charges
        self.exit_reason = exit_reason
        self.month = date.strftime("%Y-%m") if hasattr(date, "strftime") else str(date)[:7]


# ===================== Helpers =====================
def load_cached_data() -> dict[str, pd.DataFrame]:
    """Load all cached pickles into a dict."""
    if not CACHE_DIR.exists():
        print(f"ERROR: cache dir not found: {CACHE_DIR.absolute()}")
        print("Run: python fetch_angel_historical.py first")
        sys.exit(1)

    data = {}
    for pkl in CACHE_DIR.glob("*_5min.pkl"):
        symbol = pkl.stem.replace("_5min", "")
        try:
            df = pd.read_pickle(pkl)
            if df.empty or len(df) < 100:
                continue
            data[symbol] = df
        except Exception as e:
            print(f"  Failed to load {symbol}: {e}")

    return data


def daily_to_5min_groups(df: pd.DataFrame) -> dict:
    """Group 5-min bars by trading date. Returns {date: DataFrame}."""
    df = df.copy()
    df["date"] = df.index.date
    grouped = {}
    for date, group in df.groupby("date"):
        if len(group) < 10:  # Need at least 10 bars (50 min) for any trading
            continue
        grouped[date] = group.sort_index()
    return grouped


def fetch_vix_daily() -> dict:
    """Fetch daily VIX from Yahoo Finance for the same period."""
    try:
        import yfinance as yf
        # Get a year of daily VIX
        df = yf.download("^INDIAVIX", period="2y", interval="1d",
                         progress=False, auto_adjust=True)
        if hasattr(df.columns, "levels") and len(df.columns.levels) > 1:
            df.columns = df.columns.get_level_values(0)
        return {d.date(): float(df.loc[d, "Close"]) for d in df.index}
    except Exception as e:
        print(f"  VIX fetch failed: {e}")
        return {}


# ===================== F&O Backtester =====================
def backtest_options(nifty_data: dict, banknifty_data: dict, vix_daily: dict,
                     capital_for_options: float) -> list[Trade]:
    """ORB-retest options backtest on NIFTY + BANKNIFTY. Multi-lot scaled by capital."""
    trades = []

    for index_name, day_data, lot_size, strike_interval, atm_delta in [
        ("NIFTY", nifty_data, NIFTY_LOT, 50, ATM_DELTA),
        ("BANKNIFTY", banknifty_data, BANKNIFTY_LOT, 100, BANKNIFTY_DELTA),
    ]:
        for date, day_candles in sorted(day_data.items()):
            # Get VIX for this day; skip if too high
            vix = vix_daily.get(date, 15.0)
            if vix >= VIX_DANGER:
                continue

            if len(day_candles) < 12:
                continue

            # ORB range from first 3 candles (9:15-9:30 IST)
            orb_candles = day_candles.iloc[:3]
            orb_high = float(orb_candles["High"].max())
            orb_low = float(orb_candles["Low"].min())
            orb_range = orb_high - orb_low
            if orb_range <= 0:
                continue

            # Range size filter
            mid = (orb_high + orb_low) / 2
            range_pct = (orb_range / mid) * 100
            min_range = 0.2
            max_range = 1.5 if index_name == "NIFTY" else 3.0
            if range_pct < min_range or range_pct > max_range:
                continue

            # State machine: detect breakout + retest
            opt_strategy = NiftyOptionsStrategy(
                config.trading,
                min_range_pct=min_range, max_range_pct=max_range,
            )
            opt_strategy.set_orb_range(orb_high, orb_low)

            position = None  # {type, entry_idx, entry_premium, entry_index, sl, target, lot_size, strike}

            for i in range(3, len(day_candles)):
                row = day_candles.iloc[i]
                bar_time = day_candles.index[i].time()
                ltp = float(row["Close"])

                # Only check for new signal if no position open
                if position is None:
                    # Only during 9:30-10:15
                    if bar_time > dt_time(10, 15):
                        continue

                    signal = opt_strategy.check_signal(day_candles.iloc[:i+1], vix=vix)
                    if signal:
                        # Premium estimate via Black-Scholes-lite (sigma from VIX)
                        spot = ltp
                        sigma = max(vix, 12) / 100
                        days_to_expiry = 3
                        time_factor = (days_to_expiry / 365) ** 0.5
                        est_premium = max(30, min(spot * sigma * time_factor * 0.4, 700))
                        est_premium = round(est_premium, 1)
                        strike = round(ltp / strike_interval) * strike_interval

                        # MULTI-LOT SCALING (FIX): scale lots based on capital
                        # 25% of capital per position; floor 1 lot
                        capital_per_pos = capital_for_options * 0.25
                        lot_cost = est_premium * lot_size
                        num_lots = max(1, int(capital_per_pos / lot_cost)) if lot_cost > 0 else 1
                        # Cap at reasonable max (don't go crazy on small premium)
                        num_lots = min(num_lots, 10)
                        quantity = lot_size * num_lots

                        position = {
                            "type": signal.direction,
                            "entry_premium": est_premium,
                            "entry_index": ltp,
                            "sl": est_premium * 0.7,
                            "target": est_premium * 1.5,
                            "lot": quantity,  # was lot_size; now lot_size × num_lots
                            "lots": num_lots,
                            "strike": strike,
                        }
                else:
                    # Monitor position
                    index_move = ltp - position["entry_index"]
                    if position["type"] == "PUT":
                        index_move = -index_move
                    premium_change = index_move * atm_delta
                    current_premium = position["entry_premium"] + premium_change

                    exit_reason = None
                    exit_premium = current_premium

                    # SL hit (premium dropped 30%)
                    if current_premium <= position["sl"]:
                        exit_premium = position["sl"]
                        exit_reason = "SL"
                    # Target hit (50% gain)
                    elif current_premium >= position["target"]:
                        exit_premium = position["target"]
                        exit_reason = "TARGET"
                    # Time exit at 14:00
                    elif bar_time >= dt_time(14, 0):
                        exit_reason = "TIME_EXIT"
                    # Force close at end of day
                    elif i == len(day_candles) - 1:
                        exit_reason = "FORCE_EXIT"

                    if exit_reason:
                        gross = (exit_premium - position["entry_premium"]) * position["lot"]
                        charges = position["lot"] * position["entry_premium"] * 0.001  # ~0.1%
                        trades.append(Trade(
                            date=date, kind="OPTION",
                            symbol=f"{index_name} {position['strike']:.0f}{position['type'][0]}E",
                            direction=position["type"],
                            entry=position["entry_premium"], exit=exit_premium,
                            qty=position["lot"],
                            gross=gross, charges=charges,
                            exit_reason=exit_reason,
                        ))
                        position = None
                        if exit_reason in ("TIME_EXIT", "FORCE_EXIT"):
                            break

    return trades


# ===================== Equity Backtester (simplified ORB) =====================
def backtest_equity_orb(stocks_data: dict[str, dict], nifty_data: dict, vix_daily: dict,
                       capital_start: float) -> list[Trade]:
    """
    Equity ORB backtest with LIVE-BOT FILTERS (mirrors score-80 gate effect):
      - 9:15-9:30 ORB range, 0.5%-2% size required
      - 9:30-10:15 entry window (was 13:00 — too late, mostly failures)
      - VIX < 18 gate
      - NIFTY direction alignment (LONG only if NIFTY bullish/neutral, SHORT only if bearish/neutral)
      - ATR expansion check (hard reject ORB if ATR compressing — live bot rule)
      - Volume >= 1.5x avg (was 1.2x — too permissive)
      - Candle close confirmation: prev candle closed >= 0.3% past breakout
      - Per-stock 15-min cooldown after exit
      - Max 3 trades/day TOTAL (was 5 — sniper mode)
      - 1.5R target, ATR-based SL (1.0%-1.5% bounds)
      - 1.5% risk per trade
    """
    trades = []
    capital = capital_start
    config_t = config.trading

    orb_strat = ORBStrategy(config_t)

    all_dates = set()
    for stock, day_data in stocks_data.items():
        all_dates.update(day_data.keys())
    all_dates = sorted(all_dates)

    cooldown = {}  # stock -> earliest re-entry datetime

    for date in all_dates:
        vix = vix_daily.get(date, 15.0)
        if vix >= VIX_DANGER:
            continue

        day_trade_count = 0
        max_trades = 3  # SNIPER: was 5, tightened to mimic live bot's effective rate

        # NIFTY direction for the day (from open vs noon close)
        nifty_dir = "NEUTRAL"
        if date in nifty_data:
            nday = nifty_data[date]
            if len(nday) >= 6:
                n_open = float(nday.iloc[0]["Open"])
                # Use 6th bar (~10:00) to determine intraday direction
                n_mid = float(nday.iloc[min(5, len(nday)-1)]["Close"])
                change_pct = (n_mid - n_open) / n_open * 100
                if change_pct > 0.2:
                    nifty_dir = "BULLISH"
                elif change_pct < -0.2:
                    nifty_dir = "BEARISH"

        # Reset ORB strategy daily
        orb_strat.orb_ranges.clear()
        if hasattr(orb_strat, "_breakout_state"):
            orb_strat._breakout_state.clear()

        # Set ORB range from first 3 candles per stock
        for stock, day_data in stocks_data.items():
            if date not in day_data:
                continue
            day_candles = day_data[date]
            if len(day_candles) < 3:
                continue
            orb_high = float(day_candles.iloc[:3]["High"].max())
            orb_low = float(day_candles.iloc[:3]["Low"].min())
            orb_strat.set_orb_range(stock, orb_high, orb_low)

        # Iterate through bars (9:30 onwards)
        # For simplicity, scan each candle starting bar_idx=3
        # Check for ORB signal on each completed candle
        positions = {}  # stock -> {entry_price, sl, target, qty, entry_bar_idx, entry_time}

        # Build a unified bar timeline (use NIFTY's bar index as reference)
        # Each stock's day candles are aligned by time
        # Simpler: iterate bar_idx 3 to 75 (5-min bars in trading day = ~75)
        max_bars = 75

        for bar_idx in range(3, max_bars):
            for stock, day_data in stocks_data.items():
                if date not in day_data:
                    continue
                day_candles = day_data[date]
                if bar_idx >= len(day_candles):
                    continue
                row = day_candles.iloc[bar_idx]
                bar_time = day_candles.index[bar_idx].time()
                ltp = float(row["Close"])

                # Update existing position if any
                if stock in positions:
                    pos = positions[stock]
                    high = float(row["High"])
                    low = float(row["Low"])

                    # SL hit
                    exit_reason = None
                    exit_price = ltp
                    if pos["direction"] == "LONG":
                        if low <= pos["sl"]:
                            exit_reason = "STOP_LOSS"; exit_price = pos["sl"]
                        elif high >= pos["target"]:
                            exit_reason = "TARGET"; exit_price = pos["target"]
                    else:  # SHORT
                        if high >= pos["sl"]:
                            exit_reason = "STOP_LOSS"; exit_price = pos["sl"]
                        elif low <= pos["target"]:
                            exit_reason = "TARGET"; exit_price = pos["target"]

                    # Force exit at 3:15 PM (bar 72)
                    if not exit_reason and bar_time >= dt_time(15, 15):
                        exit_reason = "FORCE_EXIT"

                    if exit_reason:
                        if pos["direction"] == "LONG":
                            gross = (exit_price - pos["entry"]) * pos["qty"]
                        else:
                            gross = (pos["entry"] - exit_price) * pos["qty"]
                        charges_dict = calculate_charges(
                            pos["entry"], exit_price, pos["qty"], pos["direction"]
                        )
                        trades.append(Trade(
                            date=date, kind="EQUITY", symbol=stock,
                            direction=pos["direction"],
                            entry=pos["entry"], exit=exit_price,
                            qty=pos["qty"], gross=gross,
                            charges=charges_dict["total_charges"],
                            exit_reason=exit_reason,
                        ))
                        del positions[stock]
                        # Set 15-min cooldown
                        cooldown[stock] = day_candles.index[bar_idx] + timedelta(minutes=15)

                # Check for new entry signal (only if no current position + room)
                if stock not in positions and day_trade_count < max_trades:
                    # SNIPER: only enter 9:30-10:15 (ORB strategy time window)
                    if bar_time > dt_time(10, 15):
                        continue
                    # Per-stock cooldown
                    cd_until = cooldown.get(stock)
                    if cd_until and day_candles.index[bar_idx] < cd_until:
                        continue
                    # Need ORB range
                    if stock not in orb_strat.orb_ranges:
                        continue
                    orb = orb_strat.orb_ranges[stock]
                    range_pct = orb["range_pct"]
                    if range_pct < config_t.orb_min_range_pct or range_pct > config_t.orb_max_range_pct:
                        continue

                    # Need previous candle to confirm
                    if bar_idx < 2:
                        continue
                    prev_close = float(day_candles.iloc[bar_idx - 1]["Close"])
                    prev_open = float(day_candles.iloc[bar_idx - 1]["Open"])
                    prev_vol = float(day_candles.iloc[bar_idx - 1]["Volume"])
                    avg_vol = float(day_candles.iloc[max(0, bar_idx-11):bar_idx-1]["Volume"].mean())

                    # SNIPER: candle close confirmation (0.3% past breakout, was 0.15%)
                    # SNIPER: volume 1.5x avg (was 1.2x)
                    direction = None
                    entry_price = ltp
                    if prev_close > orb["high"] * 1.003 and prev_close > prev_open:
                        if avg_vol == 0 or prev_vol >= avg_vol * 1.5:
                            direction = "LONG"
                    elif prev_close < orb["low"] * 0.997 and prev_close < prev_open:
                        if avg_vol == 0 or prev_vol >= avg_vol * 1.5:
                            direction = "SHORT"

                    if not direction:
                        continue

                    # SNIPER: NIFTY direction alignment
                    if direction == "LONG" and nifty_dir == "BEARISH":
                        continue
                    if direction == "SHORT" and nifty_dir == "BULLISH":
                        continue

                    # SNIPER: ATR expansion check (live bot HARD-rejects ORB on compressing ATR)
                    history = day_candles.iloc[:bar_idx + 1]
                    if len(history) >= 20:
                        try:
                            if not is_atr_expanding(history, atr_period=14, lookback=5):
                                continue  # ATR compressing - skip breakout
                        except Exception:
                            pass

                    # SNIPER: Choppiness check on stock
                    if len(history) >= 20:
                        try:
                            chop = get_current_choppiness(history, period=14)
                            if chop > 70:
                                continue  # market choppy - mean reversion mode, not breakout
                        except Exception:
                            pass

                    # ATR-based SL (compute on bars seen so far)
                    history = day_candles.iloc[:bar_idx + 1]
                    atr = get_current_atr(history, period=14) if len(history) >= 14 else 0
                    if atr <= 0:
                        atr = entry_price * 0.005  # 0.5% fallback

                    sl_distance = atr * config_t.atr_sl_multiplier_normal
                    floor_d = entry_price * (config_t.atr_sl_floor_pct / 100)
                    ceil_d = entry_price * (config_t.atr_sl_ceiling_pct / 100)
                    sl_distance = max(floor_d, min(sl_distance, ceil_d))

                    if direction == "LONG":
                        sl = round(entry_price - sl_distance, 2)
                        target = round(entry_price + sl_distance * config_t.risk_reward_ratio, 2)
                    else:
                        sl = round(entry_price + sl_distance, 2)
                        target = round(entry_price - sl_distance * config_t.risk_reward_ratio, 2)

                    # Position sizing
                    risk_amt = capital * (config_t.max_risk_per_trade_pct / 100)
                    qty = int(risk_amt / sl_distance) if sl_distance > 0 else 0
                    if qty <= 0:
                        continue

                    # Check capital (with 4x leverage cap)
                    if entry_price * qty > capital * 4:
                        qty = int(capital * 4 / entry_price)
                        if qty <= 0:
                            continue

                    positions[stock] = {
                        "direction": direction,
                        "entry": entry_price,
                        "sl": sl,
                        "target": target,
                        "qty": qty,
                    }
                    day_trade_count += 1

        # Force-close all open positions at end of day
        for stock, pos in list(positions.items()):
            day_data = stocks_data.get(stock, {})
            if date not in day_data:
                continue
            day_candles = day_data[date]
            exit_price = float(day_candles.iloc[-1]["Close"])
            if pos["direction"] == "LONG":
                gross = (exit_price - pos["entry"]) * pos["qty"]
            else:
                gross = (pos["entry"] - exit_price) * pos["qty"]
            charges_dict = calculate_charges(
                pos["entry"], exit_price, pos["qty"], pos["direction"]
            )
            trades.append(Trade(
                date=date, kind="EQUITY", symbol=stock,
                direction=pos["direction"],
                entry=pos["entry"], exit=exit_price,
                qty=pos["qty"], gross=gross,
                charges=charges_dict["total_charges"],
                exit_reason="EOD_CLOSE",
            ))

        # Update capital based on day's net P&L
        day_net = sum(t.net_pnl for t in trades if t.date == date)
        capital += day_net

    return trades


# ===================== Reporting =====================
def mom_table(trades: list[Trade], capital: float, label: str):
    """Print month-over-month breakdown."""
    print(f"\n{'='*80}")
    print(f"  {label}")
    print(f"{'='*80}")

    if not trades:
        print(f"  No trades in this mode.")
        return

    by_month = defaultdict(list)
    for t in trades:
        by_month[t.month].append(t)

    print(f"  {'Month':<12} {'Trades':>7} {'Wins':>5} {'Losses':>7} {'Gross':>11} {'Charges':>10} {'Net':>11} {'Return':>9} {'Capital':>12}")
    print(f"  {'-'*12} {'-'*7} {'-'*5} {'-'*7} {'-'*11} {'-'*10} {'-'*11} {'-'*9} {'-'*12}")

    cum_capital = capital
    total_gross = 0
    total_charges = 0
    total_net = 0
    total_trades = 0
    total_wins = 0

    for month in sorted(by_month.keys()):
        ts = by_month[month]
        gross = sum(t.gross_pnl for t in ts)
        charges = sum(t.charges for t in ts)
        net = sum(t.net_pnl for t in ts)
        wins = sum(1 for t in ts if t.net_pnl > 0)
        losses = sum(1 for t in ts if t.net_pnl <= 0)
        ret_pct = (net / cum_capital) * 100 if cum_capital > 0 else 0
        cum_capital += net
        total_gross += gross
        total_charges += charges
        total_net += net
        total_trades += len(ts)
        total_wins += wins
        print(f"  {month:<12} {len(ts):>7} {wins:>5} {losses:>7} {gross:>+11,.2f} {charges:>10,.2f} {net:>+11,.2f} {ret_pct:>+8.2f}% {cum_capital:>12,.2f}")

    print(f"  {'-'*12} {'-'*7} {'-'*5} {'-'*7} {'-'*11} {'-'*10} {'-'*11} {'-'*9} {'-'*12}")
    overall_ret = (total_net / capital) * 100 if capital > 0 else 0
    win_rate = (total_wins / total_trades * 100) if total_trades > 0 else 0
    print(f"  {'TOTAL':<12} {total_trades:>7} {total_wins:>5} {total_trades-total_wins:>7} {total_gross:>+11,.2f} {total_charges:>10,.2f} {total_net:>+11,.2f} {overall_ret:>+8.2f}% {cum_capital:>12,.2f}")
    print(f"  Win rate: {win_rate:.1f}% | Profit factor: {sum(t.net_pnl for t in trades if t.net_pnl>0)/abs(sum(t.net_pnl for t in trades if t.net_pnl<=0) or 1):.2f}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--capital", type=float, default=DEFAULT_CAPITAL)
    parser.add_argument("--mode", choices=["all", "fno", "equity"], default="all")
    args = parser.parse_args()

    capital = args.capital
    print(f"\n{'='*80}")
    print(f"  12-MONTH INTRADAY BACKTEST — Rs.{capital:,.0f} capital")
    print(f"  Data source: Angel One historical 5-min (cached)")
    print(f"{'='*80}\n")

    print("Loading cached data...")
    data = load_cached_data()
    print(f"  Loaded {len(data)} symbols")

    if not data:
        return

    print("\nFetching daily VIX from Yahoo Finance...")
    vix_daily = fetch_vix_daily()
    print(f"  Got VIX for {len(vix_daily)} days")

    # Split into indices and stocks
    nifty_data = daily_to_5min_groups(data["NIFTY"]) if "NIFTY" in data else {}
    banknifty_data = daily_to_5min_groups(data["BANKNIFTY"]) if "BANKNIFTY" in data else {}
    stocks_data = {
        s: daily_to_5min_groups(df)
        for s, df in data.items()
        if s not in ("NIFTY", "BANKNIFTY")
    }
    print(f"  Indices: NIFTY={len(nifty_data)} days, BANKNIFTY={len(banknifty_data)} days")
    print(f"  Stocks: {len(stocks_data)} symbols")

    # F&O backtest
    if args.mode in ("all", "fno"):
        print("\nRunning F&O ORB-retest backtest (multi-lot scaling)...")
        fno_trades = backtest_options(nifty_data, banknifty_data, vix_daily, capital)
        mom_table(fno_trades, capital, f"F&O-ONLY MoM at Rs.{capital:,.0f}")

    # Equity backtest
    if args.mode in ("all", "equity"):
        print("\nRunning equity ORB backtest (with sniper filters)...")
        eq_trades = backtest_equity_orb(stocks_data, nifty_data, vix_daily, capital)
        mom_table(eq_trades, capital, f"EQUITY-ONLY MoM at Rs.{capital:,.0f}")

    # Combined
    if args.mode == "all":
        all_trades = fno_trades + eq_trades
        mom_table(all_trades, capital, f"COMBINED (F&O + Equity) MoM at Rs.{capital:,.0f}")


if __name__ == "__main__":
    main()
