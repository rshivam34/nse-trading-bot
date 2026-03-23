"""
VWAP Mean Reversion Strategy — Fade Overextended Moves.
========================================================

The OPPOSITE of VWAP Bounce. Instead of buying bounces AT VWAP,
this strategy FADES moves that are too far FROM VWAP.

When a stock moves 1%+ away from VWAP, it's statistically likely
to revert back toward VWAP. Institutions use VWAP as fair value —
extreme deviations get corrected.

LONG Setup (mean reversion from below):
1. Stock has moved 1%+ BELOW VWAP (overextended selling)
2. A completed candle shows reversal (green candle, close > open)
3. Entry at candle close, SL 0.5% below the low
4. Target: VWAP (the mean it's reverting to)

SHORT Setup (mean reversion from above):
1. Stock has moved 1%+ ABOVE VWAP (overextended buying)
2. A completed candle shows reversal (red candle, close < open)
3. Entry at candle close, SL 0.5% above the high
4. Target: VWAP

Time: 10:00-13:00 only (need initial trend to form, then fade it)
"""

import logging
from typing import Optional

import pandas as pd

from strategies.base_strategy import BaseStrategy, Signal

logger = logging.getLogger(__name__)

MIN_CANDLES_NEEDED = 10  # Need 10+ candles (50 min of data for VWAP stability)
MIN_DEVIATION_PCT = 1.0  # Stock must be 1%+ away from VWAP
SL_BEYOND_EXTREME_PCT = 0.5  # SL 0.5% beyond the extreme


class VWAPReversionStrategy(BaseStrategy):
    """Fade overextended moves away from VWAP — mean reversion."""

    def __init__(self, trading_config, indicator_config):
        super().__init__(name="VWAP_REVERSION")
        self.config = trading_config
        self.indicator_config = indicator_config
        self.is_active = True
        self._last_candle_idx: dict[str, int] = {}

    def check_signal(
        self,
        stock: str,
        token: str,
        candles: pd.DataFrame,
        current_tick: dict,
        market_context: dict,
    ) -> Optional[Signal]:
        """Check for mean reversion setup away from VWAP."""

        if len(candles) < MIN_CANDLES_NEEDED:
            return None

        vwap = market_context.get("vwap", 0)
        if vwap <= 0:
            return None

        nifty_dir = market_context.get("nifty_direction", "NEUTRAL")

        # Need at least 3 candles for completed candle check
        if len(candles) < 3:
            return None

        # Prevent double-processing
        candle_idx = len(candles)
        if self._last_candle_idx.get(token, -1) == candle_idx:
            return None
        self._last_candle_idx[token] = candle_idx

        # Use COMPLETED candle (iloc[-2])
        completed = candles.iloc[-2]
        candle_close = float(completed["Close"])
        candle_open = float(completed["Open"])
        candle_low = float(completed["Low"])
        candle_high = float(completed["High"])
        candle_vol = float(completed["Volume"])

        # How far is the stock from VWAP?
        deviation_pct = ((candle_close - vwap) / vwap) * 100

        # Average volume
        vol_history = candles["Volume"].iloc[-12:-2] if len(candles) >= 12 else candles["Volume"].iloc[:-2]
        avg_vol = float(vol_history.mean()) if len(vol_history) > 0 else 0

        # ── LONG REVERSION: stock is 1%+ BELOW VWAP, showing reversal ──
        if (
            deviation_pct < -MIN_DEVIATION_PCT          # 1%+ below VWAP
            and candle_close > candle_open               # Green candle (reversal)
            and nifty_dir != "BEARISH"                   # Not in crashing market
            and (avg_vol <= 0 or candle_vol >= avg_vol)  # Volume not dead
        ):
            entry = round(candle_close, 2)
            sl = round(candle_low * (1 - SL_BEYOND_EXTREME_PCT / 100), 2)
            risk = entry - sl
            if risk <= 0:
                return None

            # Target: VWAP (the mean we're reverting to)
            target = round(vwap, 2)
            if target <= entry:
                return None  # Shouldn't happen since we're below VWAP

            return Signal(
                stock=stock, token=token, direction="LONG",
                entry_price=entry, stop_loss=sl, target=target,
                strategy_name=self.name,
                confidence=self._calc_confidence(abs(deviation_pct)),
                reason=(
                    f"VWAP Reversion LONG: {stock} ({entry:.2f}) is {deviation_pct:.1f}% below "
                    f"VWAP ({vwap:.2f}), green reversal candle. Target: VWAP."
                ),
            )

        # ── SHORT REVERSION: stock is 1%+ ABOVE VWAP, showing reversal ──
        if (
            deviation_pct > MIN_DEVIATION_PCT            # 1%+ above VWAP
            and candle_close < candle_open               # Red candle (reversal)
            and nifty_dir != "BULLISH"                   # Not in rallying market
            and (avg_vol <= 0 or candle_vol >= avg_vol)
        ):
            entry = round(candle_close, 2)
            sl = round(candle_high * (1 + SL_BEYOND_EXTREME_PCT / 100), 2)
            risk = sl - entry
            if risk <= 0:
                return None

            target = round(vwap, 2)
            if target >= entry:
                return None

            return Signal(
                stock=stock, token=token, direction="SHORT",
                entry_price=entry, stop_loss=sl, target=target,
                strategy_name=self.name,
                confidence=self._calc_confidence(abs(deviation_pct)),
                reason=(
                    f"VWAP Reversion SHORT: {stock} ({entry:.2f}) is +{deviation_pct:.1f}% above "
                    f"VWAP ({vwap:.2f}), red reversal candle. Target: VWAP."
                ),
            )

        return None

    def _calc_confidence(self, deviation_pct: float) -> float:
        """Higher deviation = higher confidence in reversion."""
        if deviation_pct >= 2.0:
            return 0.9
        elif deviation_pct >= 1.5:
            return 0.7
        else:
            return 0.5

    def reset_daily(self):
        self._last_candle_idx.clear()
