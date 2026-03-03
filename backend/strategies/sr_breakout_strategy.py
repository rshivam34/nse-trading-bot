"""
Support/Resistance Breakout Strategy
======================================
Trades when price breaks through a key S/R level WITH a volume spike.

Key levels used:
1. Previous day's HIGH, LOW, CLOSE — the most watched levels by institutions
2. 5-day swing HIGH and swing LOW — broader range levels

Entry rules:
- LONG: Price breaks above prev day's HIGH or 5-day HIGH with volume spike
- SHORT: Price breaks below prev day's LOW or 5-day LOW with volume spike
- Volume must be > 3× the 20-candle average (higher bar than ORB)

SL placement:
- LONG: Just below the broken level (1% buffer to avoid false triggers)
- SHORT: Just above the broken level

Target:
- The NEXT key level above/below (e.g., if breaking above prev day high,
  target is the 5-day high or vice versa)
- Minimum target: 2× risk

Market context:
- Only go LONG if NIFTY is BULLISH or NEUTRAL
- Only go SHORT if NIFTY is BEARISH or NEUTRAL
- Price must be above VWAP for LONG, below for SHORT

Why this works:
- Institutional traders (mutual funds, FIIs) place large orders at S/R levels
- A break THROUGH these levels WITH volume = institutional participation
- This creates a "trapped" scenario for those who expected the level to hold
- These traders exit → drives price further in the breakout direction
"""

import logging
from typing import Optional

import pandas as pd

from strategies.base_strategy import BaseStrategy, Signal

logger = logging.getLogger(__name__)

MIN_TICKS_NEEDED = 30  # Need at least 30 ticks for volume analysis
VOLUME_SPIKE_MULTIPLIER = 3.0    # Higher bar for S/R breakout confirmation
LEVEL_BUFFER_PCT = 0.1            # 0.1% buffer to confirm a genuine break


class SRBreakoutStrategy(BaseStrategy):
    """Support/Resistance level breakout with volume confirmation."""

    def __init__(self, config, indicator_config):
        super().__init__(name="SR_BREAKOUT")
        self.config = config
        self.indicator_config = indicator_config

        # Cache of computed key levels per stock
        # Structure: {token: {"prev_high": float, "prev_low": float, ...}}
        self._level_cache: dict[str, dict] = {}

        # Track which levels have been broken today (avoid re-entry at same level)
        self._broken_levels: set[str] = set()  # f"{token}_{level_name}"

    def check_signal(
        self,
        stock: str,
        token: str,
        candles: pd.DataFrame,
        current_tick: dict,
        market_context: dict,
    ) -> Optional[Signal]:
        """Check if price is breaking a key S/R level with volume confirmation."""

        if len(candles) < MIN_TICKS_NEEDED:
            return None

        ltp = current_tick.get("ltp", 0)
        if ltp <= 0:
            return None

        # Get key levels from market context (populated by scanner from prev day data)
        prev_day = market_context.get("prev_day", {})
        if not prev_day:
            return None  # No prev day data = can't run this strategy

        prev_high = prev_day.get("prev_high", 0)
        prev_low = prev_day.get("prev_low", 0)
        prev_close = prev_day.get("prev_close", 0)

        if not (prev_high and prev_low):
            return None

        nifty_dir = market_context.get("nifty_direction", "NEUTRAL")
        is_above_vwap = market_context.get("is_above_vwap", True)
        vwap = market_context.get("vwap", 0)

        # Build all key levels to check
        key_levels = self._build_key_levels(prev_high, prev_low, prev_close, candles)

        # Check for volume spike
        vol_ratio = self._calc_volume_ratio(candles)
        has_volume_spike = vol_ratio >= VOLUME_SPIKE_MULTIPLIER

        if not has_volume_spike:
            return None  # Volume confirmation required for S/R breakout

        # ── Check each level for a breakout ──────────────────────────────
        buffer = ltp * (LEVEL_BUFFER_PCT / 100)

        for level_name, level_price in key_levels.items():
            if level_price <= 0:
                continue

            level_key = f"{token}_{level_name}"
            if level_key in self._broken_levels:
                continue  # Already traded this level today

            # ── LONG: Price breaks ABOVE a resistance level ───────────────
            if (
                ltp > level_price + buffer
                and "high" in level_name.lower()
                and nifty_dir != "BEARISH"
                and (not vwap or ltp > vwap)  # Above VWAP if available
            ):
                # Find next resistance above
                next_level = self._find_next_level_above(level_price, key_levels, ltp)
                entry = round(ltp, 2)
                sl = round(level_price * 0.99, 2)   # 1% below broken level
                risk = entry - sl

                if risk <= 0:
                    continue

                # Target is next key level, minimum 2× risk
                target = max(
                    round(next_level if next_level else 0, 2),
                    round(entry + risk * 2.0, 2),
                )

                self._broken_levels.add(level_key)
                confidence = self._calc_confidence(vol_ratio, nifty_dir, "LONG", is_above_vwap)

                logger.info(
                    f"SR LONG signal: {stock} broke {level_name} ({level_price:.2f}) "
                    f"with {vol_ratio:.1f}× volume"
                )

                return Signal(
                    stock=stock,
                    token=token,
                    direction="LONG",
                    entry_price=entry,
                    stop_loss=sl,
                    target=target,
                    strategy_name=self.name,
                    confidence=confidence,
                    reason=(
                        f"S/R Breakout LONG: {stock} broke {level_name} ({level_price:.2f}). "
                        f"Volume: {vol_ratio:.1f}× avg. NIFTY: {nifty_dir}. "
                        f"Next level target: {target:.2f}"
                    ),
                )

            # ── SHORT: Price breaks BELOW a support level ─────────────────
            if (
                ltp < level_price - buffer
                and "low" in level_name.lower()
                and nifty_dir != "BULLISH"
                and (not vwap or ltp < vwap)  # Below VWAP if available
            ):
                next_level = self._find_next_level_below(level_price, key_levels, ltp)
                entry = round(ltp, 2)
                sl = round(level_price * 1.01, 2)   # 1% above broken level
                risk = sl - entry

                if risk <= 0:
                    continue

                target = min(
                    round(next_level if next_level else 0, 2) or round(entry - risk * 2.0, 2),
                    round(entry - risk * 2.0, 2),
                ) if next_level else round(entry - risk * 2.0, 2)

                self._broken_levels.add(level_key)
                confidence = self._calc_confidence(vol_ratio, nifty_dir, "SHORT", not is_above_vwap)

                return Signal(
                    stock=stock,
                    token=token,
                    direction="SHORT",
                    entry_price=entry,
                    stop_loss=sl,
                    target=target,
                    strategy_name=self.name,
                    confidence=confidence,
                    reason=(
                        f"S/R Breakout SHORT: {stock} broke {level_name} ({level_price:.2f}). "
                        f"Volume: {vol_ratio:.1f}× avg. NIFTY: {nifty_dir}."
                    ),
                )

        return None

    def _build_key_levels(
        self, prev_high: float, prev_low: float, prev_close: float, candles: pd.DataFrame
    ) -> dict[str, float]:
        """
        Build dictionary of all S/R levels to monitor.

        Key levels:
        - prev_day_high: Most-watched resistance
        - prev_day_low: Most-watched support
        - prev_day_close: Psychological level
        - 5day_swing_high: Multi-day resistance
        - 5day_swing_low: Multi-day support
        """
        levels: dict[str, float] = {
            "prev_day_high": prev_high,
            "prev_day_low": prev_low,
            "prev_day_close": prev_close,
        }

        # Add multi-day swing highs/lows from tick buffer
        lookback = min(len(candles), 100)  # Use last 100 ticks as proxy for multi-day
        if lookback >= 20:
            swing_high = float(candles["High"].iloc[-lookback:].max())
            swing_low = float(candles["Low"].iloc[-lookback:].min())
            # Only add if different from prev day levels (avoid duplicates)
            if abs(swing_high - prev_high) / prev_high > 0.005:  # More than 0.5% different
                levels["5day_swing_high"] = swing_high
            if abs(swing_low - prev_low) / prev_low > 0.005:
                levels["5day_swing_low"] = swing_low

        return levels

    def _calc_volume_ratio(self, candles: pd.DataFrame) -> float:
        """Volume ratio: latest candle vs 20-candle average."""
        if len(candles) < 21:
            return 1.0

        vol_series = candles["Volume"]
        current_vol = vol_series.iloc[-1]
        avg_vol = vol_series.iloc[-21:-1].mean()

        if avg_vol <= 0:
            return 1.0

        return round(current_vol / avg_vol, 2)

    def _find_next_level_above(
        self, broken_level: float, all_levels: dict, current_price: float
    ) -> Optional[float]:
        """Find the next resistance level above the broken one."""
        candidates = [
            v for v in all_levels.values()
            if v > broken_level * 1.001  # At least 0.1% above
        ]
        return min(candidates) if candidates else None

    def _find_next_level_below(
        self, broken_level: float, all_levels: dict, current_price: float
    ) -> Optional[float]:
        """Find the next support level below the broken one."""
        candidates = [
            v for v in all_levels.values()
            if v < broken_level * 0.999  # At least 0.1% below
        ]
        return max(candidates) if candidates else None

    def _calc_confidence(
        self, vol_ratio: float, nifty_dir: str, direction: str, vwap_aligned: bool
    ) -> float:
        """Score 0-1 based on breakout strength."""
        score = 0.4

        # Volume strength
        if vol_ratio >= 5.0:
            score += 0.3
        elif vol_ratio >= 3.0:
            score += 0.2

        # Market alignment
        if (direction == "LONG" and nifty_dir == "BULLISH") or (
            direction == "SHORT" and nifty_dir == "BEARISH"
        ):
            score += 0.2
        elif nifty_dir == "NEUTRAL":
            score += 0.1

        # VWAP alignment
        if vwap_aligned:
            score += 0.1

        return min(score, 1.0)

    def reset_daily(self):
        """Clear broken levels at start of new trading day."""
        self._broken_levels.clear()
        self._level_cache.clear()
