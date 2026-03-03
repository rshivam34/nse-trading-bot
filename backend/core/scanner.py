"""
Pattern Scanner — Scans all stocks, runs all strategies.
========================================================
The scanner is the "brain" that coordinates pattern detection
across the watchlist using all active strategies.
"""

import logging
from typing import Optional

import pandas as pd

from strategies.base_strategy import Signal
from strategies.orb_strategy import ORBStrategy

logger = logging.getLogger(__name__)


class PatternScanner:
    """Scans watchlist stocks for trading patterns."""

    def __init__(self, trading_config, indicator_config):
        self.trading_config = trading_config
        self.indicator_config = indicator_config

        # Initialize strategies
        self.strategies = [
            ORBStrategy(trading_config),
            # Add more strategies here as we build them:
            # VWAPStrategy(trading_config, indicator_config),
            # EMACrossoverStrategy(trading_config, indicator_config),
        ]

        # Price data storage: stock_token → list of ticks
        self.tick_buffer: dict[str, list] = {}
        self.candle_data: dict[str, pd.DataFrame] = {}

        # ORB range tracking
        self.orb_highs: dict[str, float] = {}
        self.orb_lows: dict[str, float] = {}

        # Market context
        self.market_context = {"nifty_direction": "NEUTRAL"}

        # Track which stocks already got signals today (avoid duplicates)
        self.signals_today: set = set()

    def update_orb_range(self, tick: dict):
        """
        Called during 9:15-9:30 to track the opening range.
        Updates the high and low for each stock.
        """
        token = tick["token"]
        ltp = tick["ltp"]

        # Update running high/low
        if token not in self.orb_highs:
            self.orb_highs[token] = ltp
            self.orb_lows[token] = ltp
        else:
            self.orb_highs[token] = max(self.orb_highs[token], ltp)
            self.orb_lows[token] = min(self.orb_lows[token], ltp)

        # Push to ORB strategy
        for strat in self.strategies:
            if isinstance(strat, ORBStrategy):
                strat.set_orb_range(
                    stock=token,  # TODO: map token → stock symbol
                    high=self.orb_highs[token],
                    low=self.orb_lows[token],
                )

    def scan(self, tick: dict) -> list[Signal]:
        """
        Scan a single tick against all strategies.
        Returns list of signals (usually 0 or 1).
        """
        token = tick["token"]
        signals = []

        # Skip if this stock already generated a signal today
        if token in self.signals_today:
            return signals

        # Buffer ticks to build candles
        if token not in self.tick_buffer:
            self.tick_buffer[token] = []
        self.tick_buffer[token].append(tick)

        # Build candle data from ticks
        candles = self._build_candles(token)

        # Run each strategy
        for strategy in self.strategies:
            if not strategy.is_active:
                continue

            signal = strategy.check_signal(
                stock=token,  # TODO: map token → symbol
                token=token,
                candles=candles,
                current_tick=tick,
                market_context=self.market_context,
            )

            if signal:
                signals.append(signal)
                self.signals_today.add(token)
                logger.info(f"🎯 Signal: {signal}")

        return signals

    def _build_candles(self, token: str) -> pd.DataFrame:
        """
        Convert raw ticks into OHLCV candles.
        TODO: Implement proper candle aggregation (5-min candles).
        """
        ticks = self.tick_buffer.get(token, [])
        if not ticks:
            return pd.DataFrame()

        # Simplified: return last N ticks as pseudo-candles
        data = [{
            "Open": t["open"],
            "High": t["high"],
            "Low": t["low"],
            "Close": t["close"],
            "Volume": t["volume"],
        } for t in ticks[-100:]]  # Keep last 100

        return pd.DataFrame(data)

    def update_market_context(self, nifty_tick: dict):
        """
        Update NIFTY direction for market context filtering.
        Called with NIFTY 50 index ticks.
        """
        # Simple logic: compare current price to open
        if nifty_tick.get("ltp", 0) > nifty_tick.get("open", 0) * 1.002:
            self.market_context["nifty_direction"] = "BULLISH"
        elif nifty_tick.get("ltp", 0) < nifty_tick.get("open", 0) * 0.998:
            self.market_context["nifty_direction"] = "BEARISH"
        else:
            self.market_context["nifty_direction"] = "NEUTRAL"

    def reset_daily(self):
        """Reset for new trading day."""
        self.tick_buffer.clear()
        self.candle_data.clear()
        self.orb_highs.clear()
        self.orb_lows.clear()
        self.signals_today.clear()
