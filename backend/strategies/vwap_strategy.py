"""
VWAP Bounce Strategy — Completed Candle Confirmation Version.
=============================================================

The old VWAP bounce entered on LTP touching VWAP → caught noise, not bounces.
The new version requires a COMPLETED 5-min candle bounce:

LONG Setup:
1. Stock has been above VWAP for 6+ candles (30 min institutional support)
2. Price pulls back to VWAP (candle Low touches VWAP zone)
3. The COMPLETED candle closes ABOVE VWAP (bounce confirmed, not just a wick)
4. The bounce candle is GREEN (close > open = buyers stepping in)
5. Volume on bounce candle is above average (institutional defense)
6. NIFTY direction is not BEARISH

SHORT Setup: Mirror of LONG (below VWAP, red candle, etc.)

Why completed candle matters: A tick touching VWAP is meaningless — it could
be a wick that immediately reverses. A completed candle that touches VWAP
and closes AWAY from it means the full 5-minute period confirmed the bounce.
"""

import logging
from typing import Optional

import numpy as np
import pandas as pd

from strategies.base_strategy import BaseStrategy, Signal
from utils.indicators import calculate_rsi

logger = logging.getLogger(__name__)

MIN_CANDLES_NEEDED = 8   # Need 8+ candles (40 min of data for VWAP stability)
VWAP_ZONE_PCT = 0.3      # Price must touch within 0.3% of VWAP to count as "at VWAP"
SL_BEYOND_VWAP_PCT = 0.4 # SL placed 0.4% beyond VWAP (structural level)
MIN_CANDLES_ABOVE = 6    # Must be above/below VWAP for 6+ candles (~30 min)


class VWAPBounceStrategy(BaseStrategy):
    """VWAP bounce with completed candle confirmation."""

    def __init__(self, trading_config, indicator_config):
        super().__init__(name="VWAP_BOUNCE")
        self.config = trading_config
        self.indicator_config = indicator_config
        self.is_active = True

        # Track consecutive candles above/below VWAP per stock
        self._candles_above_vwap: dict[str, int] = {}
        self._candles_below_vwap: dict[str, int] = {}
        # Track last candle index processed per stock (prevent double-counting)
        self._last_candle_idx: dict[str, int] = {}

    def check_signal(
        self,
        stock: str,
        token: str,
        candles: pd.DataFrame,
        current_tick: dict,
        market_context: dict,
    ) -> Optional[Signal]:
        """Check for VWAP bounce with completed candle confirmation."""

        if len(candles) < MIN_CANDLES_NEEDED:
            return None

        vwap = market_context.get("vwap", 0)
        if vwap <= 0:
            vwap = self._calculate_vwap(candles)
        if vwap <= 0:
            return None

        nifty_dir = market_context.get("nifty_direction", "NEUTRAL")
        sector_phase = market_context.get("sector_phase", "")
        trend_15m = market_context.get("trend_15m", "NEUTRAL")

        # Sector filter: only bounce in LEADING/IMPROVING sectors
        if sector_phase in ("LAGGING", "WEAKENING"):
            return None

        # Time limit: VWAP bounces only 9:30-11:30 (afternoon bounces fail)
        from datetime import timedelta, time as dt_time
        if len(candles) > 0 and hasattr(candles.index[-1], 'hour'):
            candle_time = candles.index[-1]
            if hasattr(candle_time, 'hour') and candle_time.hour < 4:
                candle_time = candle_time + timedelta(hours=5, minutes=30)
            ist_t = candle_time.time() if hasattr(candle_time, 'time') else dt_time(12, 0)
            if ist_t > dt_time(11, 30):
                return None  # After 11:30 = no new VWAP bounces

        # Need 2 COMPLETED candles for 2-candle bounce confirmation
        if len(candles) < 4:
            return None

        # 2-candle bounce: both candles must confirm the bounce direction
        completed = candles.iloc[-2]   # Latest completed candle
        prev_completed = candles.iloc[-3]  # Previous completed candle (first bounce)
        candle_close = float(completed["Close"])
        candle_open = float(completed["Open"])
        candle_low = float(completed["Low"])
        candle_high = float(completed["High"])
        candle_vol = float(completed["Volume"])
        prev_close = float(prev_completed["Close"])
        prev_open = float(prev_completed["Open"])
        prev_low = float(prev_completed["Low"])
        prev_high = float(prev_completed["High"])

        # Prevent processing same candle twice
        candle_idx = len(candles)
        if self._last_candle_idx.get(token, -1) == candle_idx:
            return None
        self._last_candle_idx[token] = candle_idx

        # Update candle-based VWAP position tracking
        # (uses completed candle close, not tick LTP)
        self._update_vwap_position(token, candle_close, vwap)

        # Average volume for comparison (last 10 completed candles, excluding current)
        vol_history = candles["Volume"].iloc[-12:-2] if len(candles) >= 12 else candles["Volume"].iloc[:-2]
        avg_vol = float(vol_history.mean()) if len(vol_history) > 0 else 0

        # Distance from VWAP
        distance_pct = abs(candle_close - vwap) / vwap * 100

        # ── LONG SETUP (2-candle bounce confirmation) ──────────────────
        # Both candles must: touch VWAP zone + close above VWAP + be green
        prev_is_long_bounce = (
            prev_low <= vwap * (1 + VWAP_ZONE_PCT / 100)  # First candle touched VWAP
            and prev_close > vwap                           # Closed above VWAP
            and prev_close > prev_open                      # Green candle
        )
        curr_is_long_confirm = (
            candle_close > vwap                              # Second candle also above VWAP
            and candle_close > candle_open                   # Also green (momentum continues)
        )
        if (
            nifty_dir != "BEARISH"
            and (trend_15m != "BEARISH")                      # 15-min trend not against us
            and self._candles_above_vwap.get(token, 0) >= MIN_CANDLES_ABOVE
            and prev_is_long_bounce and curr_is_long_confirm  # 2-candle bounce confirmed
            and (avg_vol <= 0 or candle_vol >= avg_vol * 1.5)
            and self._rsi_not_overbought(candles)
        ):
            entry = round(candle_close, 2)
            sl = round(vwap * (1 - SL_BEYOND_VWAP_PCT / 100), 2)
            risk = entry - sl

            if risk <= 0:
                return None

            # Target: previous swing high or 2× risk
            swing_high = float(candles["High"].iloc[-20:-2].max()) if len(candles) >= 22 else float(candles["High"].max())
            target = max(
                round(swing_high, 2) if swing_high > entry else 0,
                round(entry + risk * self.config.risk_reward_ratio, 2),
            )

            return Signal(
                stock=stock, token=token, direction="LONG",
                entry_price=entry, stop_loss=sl, target=target,
                strategy_name=self.name,
                confidence=self._calc_confidence(distance_pct, nifty_dir, "LONG", candle_vol, avg_vol),
                reason=(
                    f"VWAP Bounce LONG: {stock} ({entry:.2f}) completed candle bounced off "
                    f"VWAP ({vwap:.2f}), green candle, vol {candle_vol:.0f} vs avg {avg_vol:.0f}. "
                    f"Above VWAP for {self._candles_above_vwap.get(token, 0)} candles. "
                    f"NIFTY: {nifty_dir}"
                ),
            )

        # ── SHORT SETUP (2-candle bounce confirmation) ────────────────
        prev_is_short_bounce = (
            prev_high >= vwap * (1 - VWAP_ZONE_PCT / 100)
            and prev_close < vwap
            and prev_close < prev_open  # Red candle
        )
        curr_is_short_confirm = (
            candle_close < vwap
            and candle_close < candle_open  # Also red
        )
        if (
            nifty_dir != "BULLISH"
            and (trend_15m != "BULLISH")
            and self._candles_below_vwap.get(token, 0) >= MIN_CANDLES_ABOVE
            and prev_is_short_bounce and curr_is_short_confirm
            and (avg_vol <= 0 or candle_vol >= avg_vol * 1.5)
            and self._rsi_not_oversold(candles)
        ):
            entry = round(candle_close, 2)
            sl = round(vwap * (1 + SL_BEYOND_VWAP_PCT / 100), 2)
            risk = sl - entry

            if risk <= 0:
                return None

            swing_low = float(candles["Low"].iloc[-20:-2].min()) if len(candles) >= 22 else float(candles["Low"].min())
            target = min(
                round(swing_low, 2) if swing_low < entry else float("inf"),
                round(entry - risk * self.config.risk_reward_ratio, 2),
            )

            return Signal(
                stock=stock, token=token, direction="SHORT",
                entry_price=entry, stop_loss=sl, target=target,
                strategy_name=self.name,
                confidence=self._calc_confidence(distance_pct, nifty_dir, "SHORT", candle_vol, avg_vol),
                reason=(
                    f"VWAP Bounce SHORT: {stock} ({entry:.2f}) completed candle rejected at "
                    f"VWAP ({vwap:.2f}), red candle, vol {candle_vol:.0f} vs avg {avg_vol:.0f}. "
                    f"Below VWAP for {self._candles_below_vwap.get(token, 0)} candles. "
                    f"NIFTY: {nifty_dir}"
                ),
            )

        return None

    # ──────────────────────────────────────────────────────────
    # VWAP position tracking (candle-based, not tick-based)
    # ──────────────────────────────────────────────────────────

    def _update_vwap_position(self, token: str, candle_close: float, vwap: float):
        """Track consecutive COMPLETED candles above/below VWAP."""
        if candle_close > vwap:
            self._candles_above_vwap[token] = self._candles_above_vwap.get(token, 0) + 1
            self._candles_below_vwap[token] = 0
        elif candle_close < vwap:
            self._candles_below_vwap[token] = self._candles_below_vwap.get(token, 0) + 1
            self._candles_above_vwap[token] = 0

    # ──────────────────────────────────────────────────────────
    # Filters
    # ──────────────────────────────────────────────────────────

    def _rsi_not_overbought(self, candles: pd.DataFrame, threshold: float = None) -> bool:
        if threshold is None:
            threshold = self.config.rsi_overbought_entry
        rsi = self._calc_rsi(candles["Close"])
        return rsi is None or rsi <= threshold

    def _rsi_not_oversold(self, candles: pd.DataFrame, threshold: float = None) -> bool:
        if threshold is None:
            threshold = self.config.rsi_oversold_entry
        rsi = self._calc_rsi(candles["Close"])
        return rsi is None or rsi >= threshold

    def _calc_rsi(self, closes: pd.Series, period: int = 14) -> Optional[float]:
        if len(closes) < period + 1:
            return None
        rsi_series = calculate_rsi(closes, period=period)
        val = float(rsi_series.iloc[-1])
        return round(val, 1)

    def _calculate_vwap(self, candles: pd.DataFrame) -> float:
        """Fallback VWAP calculation from candle data."""
        try:
            df = candles[candles["Volume"] > 0].copy()
            if df.empty:
                return 0.0
            tp = (df["High"] + df["Low"] + df["Close"]) / 3
            total_vol = df["Volume"].sum()
            if total_vol == 0:
                return 0.0
            return round(float((tp * df["Volume"]).sum() / total_vol), 2)
        except Exception:
            return 0.0

    def _calc_confidence(self, distance_pct: float, nifty_dir: str,
                         direction: str, candle_vol: float, avg_vol: float) -> float:
        """Confidence score based on bounce quality."""
        score = 0.5  # Base: completed candle bounce = already confirmed

        # Closer to VWAP = more precise bounce
        if distance_pct < 0.1:
            score += 0.2
        elif distance_pct < 0.2:
            score += 0.1

        # NIFTY alignment
        if (direction == "LONG" and nifty_dir == "BULLISH") or \
           (direction == "SHORT" and nifty_dir == "BEARISH"):
            score += 0.2
        elif nifty_dir == "NEUTRAL":
            score += 0.1

        # Volume strength on bounce
        if avg_vol > 0 and candle_vol >= avg_vol * 2.0:
            score += 0.1  # Strong institutional defense

        return min(round(score, 2), 1.0)

    def reset_daily(self):
        """Reset per-stock tracking at start of new trading day."""
        self._candles_above_vwap.clear()
        self._candles_below_vwap.clear()
        self._last_candle_idx.clear()
