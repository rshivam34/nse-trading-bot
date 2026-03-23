"""
Backtester — Replay Historical Data Through Full Signal Pipeline.
=================================================================

Simulates the complete trading bot on historical 5-min candle data.
Reuses the exact same strategies, scorer, and filters as the live bot.

Usage:
    python backtest.py --start 2026-02-01 --end 2026-02-28
    python backtest.py --start 2026-02-01 --end 2026-02-28 --stocks RELIANCE,TCS,INFY

Data source: yfinance (free, no API key needed).
"""

import argparse
import logging
import sys
import time as time_module
from dataclasses import dataclass, field
from datetime import datetime, timedelta, time
from typing import Optional

import pandas as pd
import numpy as np

# Reuse existing bot components
from config import config
from strategies.vwap_strategy import VWAPBounceStrategy
from strategies.ema_strategy import EMACrossoverStrategy
from strategies.sr_breakout_strategy import SRBreakoutStrategy
from strategies.orb_strategy import ORBStrategy
from core.signal_scorer import SignalScorer
from utils.brokerage import calculate_charges
from utils.indicators import get_current_atr, get_current_choppiness, is_atr_expanding
from utils.macro_analysis import MacroAnalyzer
from utils.sector_analysis import SectorAnalyzer, STOCK_SECTOR_MAP

logging.basicConfig(level=logging.WARNING, format="%(message)s")
logger = logging.getLogger(__name__)

# Top 30 liquid NIFTY stocks
DEFAULT_STOCKS = [
    "RELIANCE", "TCS", "HDFCBANK", "INFY", "ICICIBANK",
    "HINDUNILVR", "SBIN", "BHARTIARTL", "ITC", "KOTAKBANK",
    "LT", "AXISBANK", "MARUTI", "TATAMOTORS", "SUNPHARMA",
    "TITAN", "BAJFINANCE", "WIPRO", "HCLTECH", "TATASTEEL",
    "NTPC", "POWERGRID", "ONGC", "JSWSTEEL", "TECHM",
    "ULTRACEMCO", "NESTLEIND", "M&M", "BPCL", "COALINDIA",
]


@dataclass
class BacktestPosition:
    """Simplified position for backtesting."""
    stock: str
    direction: str
    entry_price: float
    sl: float
    target: float
    quantity: int
    atr_value: float = 0.0
    entry_time: str = ""
    peak_price: float = 0.0
    trailing_active: bool = False
    trailing_sl: float = 0.0
    breakeven_moved: bool = False
    partial_exit_done: bool = False
    remaining_qty: int = 0
    realized_pnl: float = 0.0
    strategy_name: str = ""
    score: int = 0

    def __post_init__(self):
        self.remaining_qty = self.quantity
        self.peak_price = self.entry_price


@dataclass
class BacktestTrade:
    """Completed trade record."""
    date: str
    stock: str
    strategy: str
    direction: str
    entry_price: float
    exit_price: float
    quantity: int
    gross_pnl: float
    charges: float
    net_pnl: float
    r_multiple: float
    exit_reason: str
    score: int
    hold_candles: int
    stance: str = ""


class Backtester:
    """Replay historical candle data through the full signal pipeline."""

    def __init__(self):
        self.trading_config = config.trading
        self.indicator_config = config.indicators

        # Override VWAP tick counter for candle-level simulation
        # 6 candles = 30 minutes (same intent as 60 ticks in live mode)
        self.indicator_config.vwap_trend_min_ticks = 6

        # Strategies — ORB only (proven gross-positive at +Rs.206 in Feb backtest)
        # VWAP disabled: -Rs.1,298 loss even with 2-candle bounce + sector + time filters
        # EMA/SR disabled: 0-1 trades in Feb, not enough signal
        self.strategies = [
            ORBStrategy(self.trading_config),
        ]
        self.scorer = SignalScorer()

        # Pre-market analysis
        self.macro_analyzer = MacroAnalyzer()
        self.sector_analyzer = SectorAnalyzer()

        # State
        self.positions: list[BacktestPosition] = []
        self.trades: list[BacktestTrade] = []
        self.capital = self.trading_config.initial_capital
        self.start_capital = self.capital

    def run(self, start_date: str, end_date: str, stocks: list[str] = None):
        """Main entry point. Fetch data and simulate day by day."""
        if stocks is None:
            stocks = DEFAULT_STOCKS

        print(f"\n{'='*70}")
        print(f"  BACKTESTER — {start_date} to {end_date}")
        print(f"  Capital: Rs.{self.capital:,.0f} | Stocks: {len(stocks)}")
        print(f"{'='*70}\n")

        # Step 1: Fetch macro data (NIFTY DMA + VIX for stance)
        print("Fetching macro data (NIFTY DMA)...")
        macro_data = self.macro_analyzer.analyze(vix=0)  # VIX per-day below
        print(f"  NIFTY trend: {macro_data.nifty_trend}")
        print(f"  50 DMA: {macro_data.nifty_50dma}, 200 DMA: {macro_data.nifty_200dma}\n")

        # Step 2: Fetch sector data
        print("Fetching sector data (9 indices)...")
        sector_data = self.sector_analyzer.analyze()
        for name, s in sorted(sector_data.items(), key=lambda x: x[1].relative_strength, reverse=True):
            print(f"  {name:<18} RS: {s.relative_strength:+.1f}%  Phase: {s.phase}")
        print()

        # Step 3: Fetch VIX daily data
        print("Fetching VIX daily data...")
        vix_daily = self._fetch_vix_daily(start_date, end_date)
        print(f"  VIX data: {len(vix_daily)} days\n")

        # Step 4: Fetch NIFTY 5-min candles
        print("Fetching NIFTY 5-min candles...")
        nifty_5m = self._fetch_5m_candles("^NSEI", start_date, end_date)
        print(f"  NIFTY candles: {len(nifty_5m)} rows\n")

        # Step 5: Fetch stock 5-min candles
        print(f"Fetching 5-min candles for {len(stocks)} stocks...")
        stock_data = {}
        for i, stock in enumerate(stocks):
            df = self._fetch_5m_candles(f"{stock}.NS", start_date, end_date)
            if df is not None and len(df) > 50:
                stock_data[stock] = df
                sys.stdout.write(f"\r  {i+1}/{len(stocks)} fetched ({stock})   ")
                sys.stdout.flush()
            time_module.sleep(0.3)  # Rate limit
        print(f"\n  Loaded: {len(stock_data)} stocks with data\n")

        # Step 6: Fetch daily OHLC for prev-day levels
        print("Fetching daily OHLC for S/R levels...")
        daily_data = self._fetch_daily_ohlc(list(stock_data.keys()), start_date, end_date)
        print(f"  Daily data: {len(daily_data)} stocks\n")

        # Step 7: Compute historical NIFTY DMA for each day (NOT current DMA)
        print("Computing historical NIFTY 50/200 DMA per day...")
        nifty_daily_hist = self._fetch_nifty_daily_history()
        nifty_dma_by_day = self._compute_historical_dma(nifty_daily_hist)
        print(f"  DMA data for {len(nifty_dma_by_day)} days\n")

        # Step 8: Get trading days
        trading_days = sorted(set(nifty_5m.index.date))
        start_dt = datetime.strptime(start_date, "%Y-%m-%d").date()
        end_dt = datetime.strptime(end_date, "%Y-%m-%d").date()
        trading_days = [d for d in trading_days if start_dt <= d <= end_dt]
        print(f"Trading days: {len(trading_days)}\n")

        # Step 8: Simulate each day
        print(f"{'Date':<12} {'Stance':<12} {'Trades':>6} {'Won':>4} {'Lost':>5} {'Gross':>10} {'Charges':>10} {'Net':>10}")
        print("-" * 80)

        for day in trading_days:
            self._simulate_day(
                day, stock_data, nifty_5m, daily_data,
                vix_daily, macro_data, sector_data, nifty_dma_by_day,
            )

        print("-" * 80)
        self._print_report()

    def _simulate_day(self, day, stock_data, nifty_5m, daily_data,
                      vix_daily, macro_data, sector_data, nifty_dma_by_day=None):
        """Simulate one full trading day."""
        day_str = day.strftime("%Y-%m-%d")

        # Get VIX for this day
        vix = vix_daily.get(day, 15.0)

        # Use historical DMA for this specific day (not current DMA)
        dma_info = (nifty_dma_by_day or {}).get(day, {})
        above_50 = dma_info.get("above_50", False)
        above_200 = dma_info.get("above_200", False)

        if above_50 and above_200:
            hist_trend = "BULLISH"
        elif not above_50 and not above_200:
            hist_trend = "BEARISH"
        else:
            hist_trend = "NEUTRAL"

        # Determine stance from historical DMA + daily VIX
        if vix > 25:
            stance = "CASH"
            max_trades = 0
            stance_size_pct = 0.0
        elif vix > 18:
            stance = "DEFENSIVE"
            max_trades = 2
            stance_size_pct = 50.0
        elif not above_200:
            stance = "DEFENSIVE"
            max_trades = 2
            stance_size_pct = 50.0
        elif not above_50:
            stance = "MODERATE"
            max_trades = 3
            stance_size_pct = 100.0
        elif vix < 18 and above_50 and above_200:
            stance = "AGGRESSIVE"
            max_trades = 5
            stance_size_pct = 100.0
        else:
            stance = "MODERATE"
            max_trades = 3
            stance_size_pct = 100.0

        # Override macro_data with historical trend for scoring
        from utils.macro_analysis import MacroData
        hist_macro = MacroData(
            nifty_trend=hist_trend,
            nifty_above_50dma=above_50,
            nifty_above_200dma=above_200,
            market_stance=stance,
        )

        # VIX zone
        if vix > self.trading_config.vix_caution_threshold:
            vix_zone = "DANGER"
        elif vix > self.trading_config.vix_normal_threshold:
            vix_zone = "CAUTION"
        else:
            vix_zone = "NORMAL"

        # ATR SL multiplier based on VIX zone
        if vix_zone == "CAUTION":
            atr_mult = self.trading_config.atr_sl_multiplier_caution
        else:
            atr_mult = self.trading_config.atr_sl_multiplier_normal

        # Get NIFTY candles for this day
        nifty_day = nifty_5m[nifty_5m.index.date == day]
        if len(nifty_day) < 10:
            return

        # NIFTY direction from first hour
        nifty_open = float(nifty_day["Close"].iloc[0])
        nifty_mid = float(nifty_day["Close"].iloc[min(6, len(nifty_day)-1)])
        nifty_change = (nifty_mid - nifty_open) / nifty_open * 100
        if nifty_change > 0.3:
            nifty_dir = "BULLISH"
        elif nifty_change < -0.3:
            nifty_dir = "BEARISH"
        else:
            nifty_dir = "NEUTRAL"

        # Reset strategies for new day
        for strat in self.strategies:
            if hasattr(strat, 'reset_daily'):
                strat.reset_daily()
            if hasattr(strat, '_broken_levels'):
                strat._broken_levels.clear()
            if hasattr(strat, '_level_cache'):
                strat._level_cache.clear()

        day_trades_count = 0
        day_losses = 0
        day_positions: list[BacktestPosition] = []
        day_trades: list[BacktestTrade] = []
        signals_today: set[str] = set()  # One signal per stock per day
        last_entry_candle_idx = -100

        for stock, candles_full in stock_data.items():
            # Get this stock's candles for this day
            stock_day = candles_full[candles_full.index.date == day].copy()
            if len(stock_day) < 22:  # Need enough for EMA
                continue

            # Get prev day OHLC for S/R levels
            prev_day_ohlc = self._get_prev_day(daily_data, stock, day)

            # Compute VWAP for the day
            tp = (stock_day["High"] + stock_day["Low"] + stock_day["Close"]) / 3
            cum_vol = stock_day["Volume"].cumsum()
            cum_tp_vol = (tp * stock_day["Volume"]).cumsum()
            stock_day["VWAP"] = cum_tp_vol / cum_vol.replace(0, np.nan)

            # ORB range (first 3 candles = 9:15-9:30)
            orb_candles = stock_day.iloc[:3]
            if len(orb_candles) >= 3:
                orb_high = float(orb_candles["High"].max())
                orb_low = float(orb_candles["Low"].min())
                if hasattr(self.strategies[0], 'set_orb_range'):
                    self.strategies[0].set_orb_range(stock, orb_high, orb_low)

            # Iterate through candles (skip first 3 = ORB period)
            for candle_idx in range(3, len(stock_day)):
                candle = stock_day.iloc[candle_idx]
                candle_time = stock_day.index[candle_idx]

                # Convert UTC to IST for time checks
                ist_time = (candle_time + timedelta(hours=5, minutes=30)).time()

                # No new trades after 14:30
                if ist_time >= time(14, 30):
                    break

                # Already signaled this stock today
                if stock in signals_today:
                    continue

                # Max trades for stance
                if day_trades_count >= max_trades:
                    break

                # Entry spacing (at least 2 candles = 10 min)
                if candle_idx - last_entry_candle_idx < 2:
                    continue

                # Build candle history
                history = stock_day.iloc[:candle_idx + 1].copy()
                if len(history) < 6:
                    continue

                # Build market context
                vwap = float(candle.get("VWAP", 0)) if pd.notna(candle.get("VWAP", 0)) else 0
                ltp = float(candle["Close"])

                # RSI
                closes = history["Close"]
                rsi = 50.0
                if len(closes) >= 15:
                    delta = closes.diff()
                    gain = delta.clip(lower=0).rolling(14).mean()
                    loss = (-delta.clip(upper=0)).rolling(14).mean()
                    rs = gain / loss.replace(0, np.nan)
                    rsi_series = 100 - (100 / (1 + rs))
                    rsi = float(rsi_series.iloc[-1]) if pd.notna(rsi_series.iloc[-1]) else 50.0

                # EMA alignment
                ema9 = closes.ewm(span=9, adjust=False).mean()
                ema21 = closes.ewm(span=21, adjust=False).mean()
                ema_aligned = float(ema9.iloc[-1]) > float(ema21.iloc[-1])

                # Volume ratio
                vol = history["Volume"]
                vol_ratio = 1.0
                if len(vol) > 5 and float(vol.iloc[-5:-1].mean()) > 0:
                    vol_ratio = float(vol.iloc[-1]) / float(vol.iloc[-5:-1].mean())

                # 15-min trend: resample 5-min candles to 15-min and check EMA 9/21
                trend_15m = "NEUTRAL"
                if len(history) >= 12:  # Need 4+ 15-min candles
                    try:
                        h15 = history.resample('15min').agg({
                            'Open': 'first', 'High': 'max', 'Low': 'min',
                            'Close': 'last', 'Volume': 'sum'
                        }).dropna()
                        if len(h15) >= 4:
                            ema9_15 = h15["Close"].ewm(span=3, adjust=False).mean()  # ~9 on 5-min scale
                            ema21_15 = h15["Close"].ewm(span=7, adjust=False).mean()  # ~21 on 5-min scale
                            if float(ema9_15.iloc[-1]) > float(ema21_15.iloc[-1]) * 1.001:
                                trend_15m = "BULLISH"
                            elif float(ema9_15.iloc[-1]) < float(ema21_15.iloc[-1]) * 0.999:
                                trend_15m = "BEARISH"
                    except Exception:
                        pass

                # Sector phase for this stock
                from utils.sector_analysis import STOCK_SECTOR_MAP
                stock_sector = STOCK_SECTOR_MAP.get(stock, "")
                sector_phase = ""
                if stock_sector and sector_data and stock_sector in sector_data:
                    sector_phase = sector_data[stock_sector].phase

                market_context = {
                    "nifty_direction": nifty_dir,
                    "vwap": vwap,
                    "is_above_vwap": ltp > vwap if vwap > 0 else True,
                    "volume_ratio": vol_ratio,
                    "rsi": rsi,
                    "ema_aligned": ema_aligned,
                    "prev_day": prev_day_ohlc,
                    "near_prev_levels": False,
                    "vix": vix,
                    "gap_pct": 0,
                    "spread_pct": 0.05,
                    "sector_phase": sector_phase,
                    "trend_15m": trend_15m,
                }

                current_tick = {
                    "ltp": ltp,
                    "open": float(candle["Open"]),
                    "high": float(candle["High"]),
                    "low": float(candle["Low"]),
                    "close": ltp,
                    "volume": float(candle["Volume"]),
                    "token": stock,
                }

                # Run strategies
                best_signal = None
                for strat in self.strategies:
                    try:
                        sig = strat.check_signal(stock, stock, history, current_tick, market_context)
                        if sig and (best_signal is None or sig.confidence > best_signal.confidence):
                            best_signal = sig
                    except Exception:
                        continue

                if not best_signal:
                    continue

                # Momentum filter: stock must have moved in signal direction recently
                # Prevents entering when stock is flat/ranging (biggest cause of stale trades)
                if len(history) >= 6:
                    recent_move = (float(history["Close"].iloc[-2]) - float(history["Close"].iloc[-6])) / float(history["Close"].iloc[-6]) * 100
                    if best_signal.direction == "LONG" and recent_move < 0.1:
                        continue  # No upward momentum in last 30 min
                    if best_signal.direction == "SHORT" and recent_move > -0.1:
                        continue  # No downward momentum in last 30 min

                # VIX DANGER gate
                if vix_zone == "DANGER":
                    continue

                # ATR and choppiness
                atr = get_current_atr(history, period=14)
                chop = get_current_choppiness(history, period=14)
                if chop > self.trading_config.chop_threshold:
                    continue

                # ATR compression hard reject for breakouts
                is_breakout = best_signal.strategy_name in ("ORB", "SR_BREAKOUT")
                if is_breakout and not is_atr_expanding(history, atr_period=14, lookback=5):
                    continue

                # Score the signal
                score, breakdown = self.scorer.score(
                    signal=best_signal,
                    market_context=market_context,
                    news_sentiment={},
                    macro_data=hist_macro,
                    sector_data=sector_data,
                )

                # VWAP VIX penalty
                if best_signal.strategy_name == "VWAP_BOUNCE" and vix > self.trading_config.vwap_bounce_vix_penalty_threshold:
                    score -= self.trading_config.vwap_bounce_vix_penalty

                # Score threshold
                if score < self.trading_config.min_score_to_trade:
                    continue

                # Compute SL and target
                if atr > 0:
                    sl_distance = atr * atr_mult
                    floor_d = ltp * (self.trading_config.atr_sl_floor_pct / 100)
                    ceil_d = ltp * (self.trading_config.atr_sl_ceiling_pct / 100)
                    sl_distance = max(sl_distance, floor_d)
                    sl_distance = min(sl_distance, ceil_d)
                else:
                    sl_distance = ltp * 0.015  # 1.5% fallback

                rr = self.trading_config.risk_reward_ratio
                if best_signal.direction == "LONG":
                    sl = round(ltp - sl_distance, 2)
                    target = round(ltp + sl_distance * rr, 2)
                else:
                    sl = round(ltp + sl_distance, 2)
                    target = round(ltp - sl_distance * rr, 2)

                # Position sizing
                risk_pct = self.trading_config.max_risk_per_trade_pct / 100
                if vix_zone == "CAUTION":
                    risk_pct *= 0.5
                risk_pct *= stance_size_pct / 100

                risk_amount = self.capital * risk_pct
                qty = int(risk_amount / sl_distance) if sl_distance > 0 else 0
                if qty <= 0:
                    continue

                # Check if trade value is affordable
                trade_value = ltp * qty
                if trade_value > self.capital * 4:  # 4x leverage
                    qty = int(self.capital * 4 / ltp)
                    if qty <= 0:
                        continue

                # Open position
                pos = BacktestPosition(
                    stock=stock,
                    direction=best_signal.direction,
                    entry_price=ltp,
                    sl=sl,
                    target=target,
                    quantity=qty,
                    atr_value=atr,
                    entry_time=ist_time.strftime("%H:%M"),
                    strategy_name=best_signal.strategy_name,
                    score=score,
                )
                day_positions.append(pos)
                signals_today.add(stock)
                day_trades_count += 1
                last_entry_candle_idx = candle_idx

        # Monitor positions through remaining candles
        for stock in list(set(p.stock for p in day_positions)):
            stock_day = stock_data.get(stock)
            if stock_day is None:
                continue
            stock_day_today = stock_day[stock_day.index.date == day]

            for pos in [p for p in day_positions if p.stock == stock and p.remaining_qty > 0]:
                entry_candle = 3  # Start monitoring after ORB
                for candle_idx in range(entry_candle, len(stock_day_today)):
                    candle = stock_day_today.iloc[candle_idx]
                    ist_time = (stock_day_today.index[candle_idx] + timedelta(hours=5, minutes=30)).time()
                    ltp = float(candle["Close"])
                    high = float(candle["High"])
                    low = float(candle["Low"])

                    if pos.remaining_qty <= 0:
                        break

                    # Update peak price
                    if pos.direction == "LONG":
                        pos.peak_price = max(pos.peak_price, high)
                    else:
                        pos.peak_price = min(pos.peak_price, low) if pos.peak_price > 0 else low

                    # Check SL
                    if pos.direction == "LONG" and low <= pos.sl:
                        self._close_position(pos, pos.sl, "STOP_LOSS", day_str, candle_idx - entry_candle, stance, day_trades)
                        continue
                    elif pos.direction == "SHORT" and high >= pos.sl:
                        self._close_position(pos, pos.sl, "STOP_LOSS", day_str, candle_idx - entry_candle, stance, day_trades)
                        continue

                    # Check trailing SL
                    if pos.trailing_active and pos.trailing_sl > 0:
                        if pos.direction == "LONG" and low <= pos.trailing_sl:
                            self._close_position(pos, pos.trailing_sl, "TRAILING_STOP", day_str, candle_idx - entry_candle, stance, day_trades)
                            continue
                        elif pos.direction == "SHORT" and high >= pos.trailing_sl:
                            self._close_position(pos, pos.trailing_sl, "TRAILING_STOP", day_str, candle_idx - entry_candle, stance, day_trades)
                            continue

                    # Check target
                    if pos.direction == "LONG" and high >= pos.target:
                        self._close_position(pos, pos.target, "TARGET", day_str, candle_idx - entry_candle, stance, day_trades)
                        continue
                    elif pos.direction == "SHORT" and low <= pos.target:
                        self._close_position(pos, pos.target, "TARGET", day_str, candle_idx - entry_candle, stance, day_trades)
                        continue

                    # Profit management
                    if pos.direction == "LONG":
                        profit_pct = (ltp - pos.entry_price) / pos.entry_price * 100
                        current_r = (ltp - pos.entry_price) / (pos.entry_price - pos.sl) if pos.entry_price > pos.sl else 0
                    else:
                        profit_pct = (pos.entry_price - ltp) / pos.entry_price * 100
                        current_r = (pos.entry_price - ltp) / (pos.sl - pos.entry_price) if pos.sl > pos.entry_price else 0

                    # Breakeven at 0.7%
                    if not pos.breakeven_moved and profit_pct >= self.trading_config.breakeven_profit_pct:
                        pos.sl = pos.entry_price
                        pos.breakeven_moved = True

                    # Partial exit at 1.0R
                    if not pos.partial_exit_done and current_r >= self.trading_config.partial_exit_rr:
                        half_qty = pos.remaining_qty // 2
                        if half_qty > 0:
                            if pos.direction == "LONG":
                                partial_pnl = (ltp - pos.entry_price) * half_qty
                            else:
                                partial_pnl = (pos.entry_price - ltp) * half_qty
                            charges = self._calc_charges(pos.entry_price, ltp, half_qty, pos.direction)
                            pos.realized_pnl += partial_pnl - charges
                            pos.remaining_qty -= half_qty
                            pos.partial_exit_done = True
                            pos.sl = pos.entry_price  # Breakeven on rest
                            pos.trailing_active = True
                            trail_amount = pos.atr_value * self.trading_config.trailing_sl_atr_multiplier if pos.atr_value > 0 else ltp * 0.01
                            if pos.direction == "LONG":
                                pos.trailing_sl = round(pos.peak_price - trail_amount, 2)
                            else:
                                pos.trailing_sl = round(pos.peak_price + trail_amount, 2)

                    # Update trailing SL
                    if pos.trailing_active and pos.atr_value > 0:
                        trail_amount = pos.atr_value * self.trading_config.trailing_sl_atr_multiplier
                        if pos.direction == "LONG":
                            new_trail = round(pos.peak_price - trail_amount, 2)
                            if new_trail > pos.trailing_sl:
                                pos.trailing_sl = new_trail
                        else:
                            new_trail = round(pos.peak_price + trail_amount, 2)
                            if new_trail < pos.trailing_sl or pos.trailing_sl == 0:
                                pos.trailing_sl = new_trail

                    # Time profit exit: after 2 PM, if in any profit, take it
                    # Don't wait for 3:15 force exit — afternoon reversals kill gains
                    if ist_time >= time(14, 0) and profit_pct > 0:
                        self._close_position(pos, ltp, "TIME_PROFIT", day_str, candle_idx - entry_candle, stance, day_trades)
                        break

                    # Force exit at 15:15
                    if ist_time >= time(15, 15):
                        self._close_position(pos, ltp, "FORCE_EXIT", day_str, candle_idx - entry_candle, stance, day_trades)
                        break

                # If still open at end of data, force close
                if pos.remaining_qty > 0:
                    last_price = float(stock_day_today["Close"].iloc[-1])
                    self._close_position(pos, last_price, "FORCE_EXIT", day_str, len(stock_day_today), stance, day_trades)

        # Day summary
        self.trades.extend(day_trades)
        day_won = sum(1 for t in day_trades if t.net_pnl > 0)
        day_lost = sum(1 for t in day_trades if t.net_pnl <= 0)
        day_gross = sum(t.gross_pnl for t in day_trades)
        day_charges = sum(t.charges for t in day_trades)
        day_net = sum(t.net_pnl for t in day_trades)
        self.capital += day_net

        print(f"{day_str:<12} {stance:<12} {len(day_trades):>6} {day_won:>4} {day_lost:>5} {day_gross:>+10.2f} {day_charges:>10.2f} {day_net:>+10.2f}")

    def _close_position(self, pos, exit_price, reason, day_str, hold_candles, stance, day_trades):
        """Close remaining position and record trade."""
        if pos.remaining_qty <= 0:
            return

        if pos.direction == "LONG":
            gross = (exit_price - pos.entry_price) * pos.remaining_qty
        else:
            gross = (pos.entry_price - exit_price) * pos.remaining_qty

        charges = self._calc_charges(pos.entry_price, exit_price, pos.remaining_qty, pos.direction)
        net = gross - charges + pos.realized_pnl
        initial_risk = abs(pos.entry_price - pos.sl) if pos.sl != pos.entry_price else pos.entry_price * 0.015
        r_mult = gross / (initial_risk * pos.quantity) if initial_risk > 0 and pos.quantity > 0 else 0

        day_trades.append(BacktestTrade(
            date=day_str, stock=pos.stock, strategy=pos.strategy_name,
            direction=pos.direction, entry_price=pos.entry_price,
            exit_price=exit_price, quantity=pos.quantity,
            gross_pnl=round(gross + pos.realized_pnl, 2),
            charges=round(charges, 2), net_pnl=round(net, 2),
            r_multiple=round(r_mult, 2), exit_reason=reason,
            score=pos.score, hold_candles=hold_candles, stance=stance,
        ))
        pos.remaining_qty = 0

    def _calc_charges(self, entry, exit_price, qty, direction):
        """Calculate NSE intraday charges."""
        buy_value = entry * qty
        sell_value = exit_price * qty
        turnover = buy_value + sell_value

        # Brokerage: min(Rs.20, 0.1% of value) per leg, min Rs.5
        brokerage_buy = max(5, min(20, buy_value * 0.001))
        brokerage_sell = max(5, min(20, sell_value * 0.001))
        brokerage = brokerage_buy + brokerage_sell

        stt = sell_value * (self.trading_config.stt_pct / 100)
        exchange = turnover * (self.trading_config.exchange_charges_pct / 100)
        gst = (brokerage + exchange) * (self.trading_config.gst_pct / 100)
        sebi = turnover * (self.trading_config.sebi_charges_pct / 100)
        stamp = buy_value * (self.trading_config.stamp_duty_pct / 100)

        return round(brokerage + stt + exchange + gst + sebi + stamp, 2)

    def _fetch_nifty_daily_history(self):
        """Fetch 1 year of NIFTY daily data for historical DMA computation."""
        try:
            import yfinance as yf
            df = yf.download("^NSEI", period="1y", interval="1d", progress=False, auto_adjust=True)
            if df is None or df.empty:
                return pd.DataFrame()
            if hasattr(df.columns, 'levels') and len(df.columns.levels) > 1:
                df.columns = df.columns.get_level_values(0)
            return df
        except Exception as e:
            logger.warning(f"NIFTY daily history fetch failed: {e}")
            return pd.DataFrame()

    def _compute_historical_dma(self, nifty_daily):
        """Compute 50/200 DMA for each historical day."""
        result = {}
        if nifty_daily.empty or "Close" not in nifty_daily.columns:
            return result

        close = nifty_daily["Close"]
        sma50 = close.rolling(50).mean()
        sma200 = close.rolling(200).mean()

        for i in range(len(nifty_daily)):
            day = nifty_daily.index[i].date()
            c = float(close.iloc[i])
            s50 = float(sma50.iloc[i]) if pd.notna(sma50.iloc[i]) else 0
            s200 = float(sma200.iloc[i]) if pd.notna(sma200.iloc[i]) else 0
            result[day] = {
                "close": c,
                "sma50": s50,
                "sma200": s200,
                "above_50": c > s50 if s50 > 0 else False,
                "above_200": c > s200 if s200 > 0 else False,
            }
        return result

    def _fetch_5m_candles(self, symbol, start, end):
        """Fetch 5-min candles via yfinance."""
        try:
            import yfinance as yf
            df = yf.download(symbol, start=start, end=end, interval="5m",
                             progress=False, auto_adjust=True)
            if df is None or df.empty:
                return None
            if hasattr(df.columns, 'levels') and len(df.columns.levels) > 1:
                df.columns = df.columns.get_level_values(0)
            # Ensure required columns
            for col in ["Open", "High", "Low", "Close", "Volume"]:
                if col not in df.columns:
                    return None
            return df
        except Exception as e:
            logger.debug(f"Failed to fetch {symbol}: {e}")
            return None

    def _fetch_daily_ohlc(self, stocks, start, end):
        """Fetch daily OHLC for prev-day S/R levels."""
        result = {}
        try:
            import yfinance as yf
            # Extend start by 5 days for prev-day lookback
            ext_start = (datetime.strptime(start, "%Y-%m-%d") - timedelta(days=10)).strftime("%Y-%m-%d")
            for stock in stocks:
                df = yf.download(f"{stock}.NS", start=ext_start, end=end,
                                 interval="1d", progress=False, auto_adjust=True)
                if df is not None and len(df) > 2:
                    if hasattr(df.columns, 'levels') and len(df.columns.levels) > 1:
                        df.columns = df.columns.get_level_values(0)
                    result[stock] = df
                time_module.sleep(0.2)
        except Exception as e:
            logger.warning(f"Daily OHLC fetch error: {e}")
        return result

    def _fetch_vix_daily(self, start, end):
        """Fetch daily VIX values."""
        try:
            import yfinance as yf
            ext_start = (datetime.strptime(start, "%Y-%m-%d") - timedelta(days=5)).strftime("%Y-%m-%d")
            df = yf.download("^INDIAVIX", start=ext_start, end=end,
                             interval="1d", progress=False, auto_adjust=True)
            if df is None or df.empty:
                return {}
            if hasattr(df.columns, 'levels') and len(df.columns.levels) > 1:
                df.columns = df.columns.get_level_values(0)
            return {d.date(): float(df.loc[d, "Close"]) for d in df.index}
        except Exception:
            return {}

    def _get_prev_day(self, daily_data, stock, current_day):
        """Get previous trading day's OHLC for S/R levels."""
        df = daily_data.get(stock)
        if df is None:
            return {"prev_high": 0, "prev_low": 0, "prev_close": 0}
        prev_days = df[df.index.date < current_day]
        if len(prev_days) == 0:
            return {"prev_high": 0, "prev_low": 0, "prev_close": 0}
        last = prev_days.iloc[-1]
        return {
            "prev_high": float(last["High"]),
            "prev_low": float(last["Low"]),
            "prev_close": float(last["Close"]),
        }

    def _print_report(self):
        """Print comprehensive backtest results."""
        print(f"\n{'='*70}")
        print(f"  BACKTEST RESULTS")
        print(f"{'='*70}\n")

        if not self.trades:
            print("  No trades executed during the backtest period.")
            print(f"  Capital preserved: Rs.{self.capital:,.2f}")
            return

        wins = [t for t in self.trades if t.net_pnl > 0]
        losses = [t for t in self.trades if t.net_pnl <= 0]
        total_gross = sum(t.gross_pnl for t in self.trades)
        total_charges = sum(t.charges for t in self.trades)
        total_net = sum(t.net_pnl for t in self.trades)
        avg_r = sum(t.r_multiple for t in self.trades) / len(self.trades) if self.trades else 0
        win_rate = len(wins) / len(self.trades) * 100 if self.trades else 0

        print(f"  Total trades:    {len(self.trades)}")
        print(f"  Wins:            {len(wins)} ({win_rate:.0f}%)")
        print(f"  Losses:          {len(losses)}")
        print(f"  Avg R-multiple:  {avg_r:+.2f}R")
        print()
        print(f"  Gross P&L:       Rs.{total_gross:+,.2f}")
        print(f"  Charges:         Rs.{total_charges:,.2f}")
        print(f"  Net P&L:         Rs.{total_net:+,.2f}")
        print()
        print(f"  Capital start:   Rs.{self.start_capital:,.2f}")
        print(f"  Capital end:     Rs.{self.capital:,.2f}")
        print(f"  Return:          {(self.capital - self.start_capital) / self.start_capital * 100:+.2f}%")
        print()

        if wins:
            print(f"  Best trade:      Rs.{max(t.net_pnl for t in wins):+,.2f} ({max(wins, key=lambda t: t.net_pnl).stock})")
            print(f"  Avg win:         Rs.{sum(t.net_pnl for t in wins)/len(wins):+,.2f}")
        if losses:
            print(f"  Worst trade:     Rs.{min(t.net_pnl for t in losses):+,.2f} ({min(losses, key=lambda t: t.net_pnl).stock})")
            print(f"  Avg loss:        Rs.{sum(t.net_pnl for t in losses)/len(losses):+,.2f}")

        # Exit reason breakdown
        print(f"\n  Exit reasons:")
        reasons = {}
        for t in self.trades:
            reasons[t.exit_reason] = reasons.get(t.exit_reason, 0) + 1
        for reason, count in sorted(reasons.items(), key=lambda x: -x[1]):
            print(f"    {reason:<20} {count}")

        # Strategy breakdown
        print(f"\n  Strategy breakdown:")
        strategies = {}
        for t in self.trades:
            if t.strategy not in strategies:
                strategies[t.strategy] = {"count": 0, "net": 0, "wins": 0}
            strategies[t.strategy]["count"] += 1
            strategies[t.strategy]["net"] += t.net_pnl
            if t.net_pnl > 0:
                strategies[t.strategy]["wins"] += 1
        for s, d in sorted(strategies.items(), key=lambda x: -x[1]["net"]):
            wr = d["wins"] / d["count"] * 100 if d["count"] > 0 else 0
            print(f"    {s:<18} {d['count']} trades, {wr:.0f}% win rate, net Rs.{d['net']:+,.2f}")

        # Trade log
        print(f"\n  {'#':<3} {'Date':<12} {'Stock':<12} {'Strat':<14} {'Dir':<6} {'Entry':>8} {'Exit':>8} {'Qty':>4} {'Net':>10} {'R':>6} {'Exit Reason':<15}")
        print("  " + "-" * 105)
        for i, t in enumerate(self.trades, 1):
            print(f"  {i:<3} {t.date:<12} {t.stock:<12} {t.strategy:<14} {t.direction:<6} {t.entry_price:>8.2f} {t.exit_price:>8.2f} {t.quantity:>4} {t.net_pnl:>+10.2f} {t.r_multiple:>+5.1f}R {t.exit_reason:<15}")


def main():
    parser = argparse.ArgumentParser(description="Backtest trading strategies on historical data")
    parser.add_argument("--start", default="2026-02-01", help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end", default="2026-02-28", help="End date (YYYY-MM-DD)")
    parser.add_argument("--stocks", default=None, help="Comma-separated stock list (default: top 30 NIFTY)")
    args = parser.parse_args()

    stocks = args.stocks.split(",") if args.stocks else None

    bt = Backtester()
    bt.run(args.start, args.end, stocks)


if __name__ == "__main__":
    main()
