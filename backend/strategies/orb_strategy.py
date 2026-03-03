"""
Opening Range Breakout (ORB) Strategy
======================================
The simplest and most reliable intraday strategy for beginners.

Logic:
1. First 15 minutes (9:15–9:30): Record the HIGH and LOW
2. After 9:30: Wait for price to break above HIGH or below LOW
3. LONG: Break above HIGH → Buy, SL at LOW, Target at 1.5× risk
4. SHORT: Break below LOW → Sell, SL at HIGH, Target at 1.5× risk
5. Exit by 3:15 PM if target/SL not hit

Market Context Filter:
- Skip LONG if NIFTY is BEARISH
- Skip SHORT if NIFTY is BULLISH
"""

import logging
from typing import Optional

import pandas as pd

from strategies.base_strategy import BaseStrategy, Signal

logger = logging.getLogger(__name__)


class ORBStrategy(BaseStrategy):
    """Opening Range Breakout strategy."""

    def __init__(self, config):
        super().__init__(name="ORB")
        self.config = config
        self.orb_ranges: dict[str, dict] = {}  # stock → {high, low}

    def set_orb_range(self, stock: str, high: float, low: float):
        """
        Called during 9:15–9:30 to record the opening range.
        The scanner calls this as ticks come in during ORB period.
        """
        self.orb_ranges[stock] = {"high": high, "low": low}
        logger.debug(f"ORB Range for {stock}: High={high:.2f}, Low={low:.2f}")

    def check_signal(
        self,
        stock: str,
        token: str,
        candles: pd.DataFrame,
        current_tick: dict,
        market_context: dict,
    ) -> Optional[Signal]:
        """Check if ORB breakout conditions are met."""

        # Must have ORB range recorded
        if stock not in self.orb_ranges:
            return None

        orb = self.orb_ranges[stock]
        orb_high = orb["high"]
        orb_low = orb["low"]
        ltp = current_tick.get("ltp", 0)  # Last Traded Price

        # Validate range size
        mid = (orb_high + orb_low) / 2
        range_pct = ((orb_high - orb_low) / mid) * 100

        if range_pct < self.config.orb_min_range_pct:
            return None  # Range too narrow — no momentum
        if range_pct > self.config.orb_max_range_pct:
            return None  # Range too wide — too risky

        risk = orb_high - orb_low
        buffer = orb_high * (self.config.breakout_buffer_pct / 100)
        nifty_dir = market_context.get("nifty_direction", "NEUTRAL")

        # ── LONG BREAKOUT ──
        if ltp > orb_high + buffer:
            if nifty_dir == "BEARISH":
                return None  # Don't go long in falling market

            entry = round(orb_high + buffer, 2)
            sl = round(orb_low, 2)
            target = round(entry + (risk * self.config.risk_reward_ratio), 2)

            return Signal(
                stock=stock,
                token=token,
                direction="LONG",
                entry_price=entry,
                stop_loss=sl,
                target=target,
                strategy_name=self.name,
                confidence=self._calc_confidence(range_pct, nifty_dir, "LONG"),
                reason=f"Price broke above ORB high ({orb_high:.2f}). "
                       f"Range: {range_pct:.1f}%. NIFTY: {nifty_dir}",
            )

        # ── SHORT BREAKOUT ──
        if ltp < orb_low - buffer:
            if nifty_dir == "BULLISH":
                return None  # Don't short in rising market

            entry = round(orb_low - buffer, 2)
            sl = round(orb_high, 2)
            target = round(entry - (risk * self.config.risk_reward_ratio), 2)

            return Signal(
                stock=stock,
                token=token,
                direction="SHORT",
                entry_price=entry,
                stop_loss=sl,
                target=target,
                strategy_name=self.name,
                confidence=self._calc_confidence(range_pct, nifty_dir, "SHORT"),
                reason=f"Price broke below ORB low ({orb_low:.2f}). "
                       f"Range: {range_pct:.1f}%. NIFTY: {nifty_dir}",
            )

        return None

    def _calc_confidence(self, range_pct: float, nifty_dir: str, direction: str) -> float:
        """
        Simple confidence score (0-1).
        Higher when range is ideal and market context aligns.
        """
        score = 0.5  # Base

        # Ideal range is 0.5–1.2%
        if 0.5 <= range_pct <= 1.2:
            score += 0.2

        # Market alignment bonus
        if direction == "LONG" and nifty_dir == "BULLISH":
            score += 0.2
        elif direction == "SHORT" and nifty_dir == "BEARISH":
            score += 0.2

        # Neutral market is okay but less confident
        if nifty_dir == "NEUTRAL":
            score += 0.1

        return min(score, 1.0)
