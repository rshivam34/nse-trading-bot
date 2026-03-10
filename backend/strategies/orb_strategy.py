"""
Opening Range Breakout (ORB) Strategy
======================================
The simplest and most reliable intraday strategy for beginners.

Logic:
1. First 15 minutes (9:15-9:30): Record the HIGH and LOW
2. After 9:30: Wait for price to break above HIGH or below LOW
3. LONG: Break above HIGH → Buy, SL at LOW, Target at 2× risk
4. SHORT: Break below LOW → Sell, SL at HIGH, Target at 2× risk
5. Exit by 3:15 PM if target/SL not hit

Multi-Confirmation Filters (added for production):
All 4 must pass for the signal to fire. If any fail, skip the trade.

1. GAP FILTER: Skip if stock opened >1.5% from prev close.
   Gapped stocks have unreliable opening ranges (sentiment-driven, not technical).

2. VWAP FILTER: Only go LONG above VWAP, SHORT below VWAP.
   VWAP is the "institutional fair price". Trading in VWAP's direction
   means you're aligned with where the big money is positioned.

3. VOLUME SPIKE: Breakout candle volume must be >2x the 20-candle average.
   A breakout without volume is a "fake breakout". Real moves have volume.

4. RSI FILTER: Skip LONG if RSI(14) > 75 (already overbought).
   Skip SHORT if RSI(14) < 25 (already oversold). Avoid chasing exhausted moves.

5. SPREAD CHECK: Skip if estimated spread > 0.1% (illiquid or volatile).

6. PREV DAY PROXIMITY: Skip if entry is within 0.3% of prev H/L/C.
   These price levels act as natural resistance/support — lower win rate near them.

7. NIFTY ALIGNMENT: Don't go LONG in bearish market, SHORT in bullish.
"""

import logging
from typing import Optional

import pandas as pd

from strategies.base_strategy import BaseStrategy, Signal
from utils.indicators import calculate_rsi

logger = logging.getLogger(__name__)


class ORBStrategy(BaseStrategy):
    """Opening Range Breakout strategy with multi-confirmation entry."""

    def __init__(self, config):
        super().__init__(name="ORB")
        self.config = config
        self.orb_ranges: dict[str, dict] = {}  # stock → {high, low}

    def set_orb_range(self, stock: str, high: float, low: float):
        """
        Called during 9:15-9:30 to record the opening range.
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
        """
        Check if ORB breakout conditions are met — with all 6 confirmations.
        Returns a Signal if all checks pass, None otherwise.
        """
        # Must have ORB range recorded (set during 9:15-9:30)
        if stock not in self.orb_ranges:
            return None

        orb = self.orb_ranges[stock]
        orb_high = orb["high"]
        orb_low = orb["low"]
        ltp = current_tick.get("ltp", 0)

        # ── CHECK 0: Validate range size ──────────────────────────────────
        mid = (orb_high + orb_low) / 2
        range_pct = ((orb_high - orb_low) / mid) * 100

        if range_pct < self.config.orb_min_range_pct:
            return None  # Range too narrow — no momentum potential
        if range_pct > self.config.orb_max_range_pct:
            return None  # Range too wide — too risky/unpredictable

        risk = orb_high - orb_low
        buffer = orb_high * (self.config.breakout_buffer_pct / 100)
        nifty_dir = market_context.get("nifty_direction", "NEUTRAL")

        # ── CHECK 1: GAP FILTER ───────────────────────────────────────────
        # Skip if stock gapped more than config.gap_filter_pct% at open
        gap_pct = market_context.get("gap_pct", 0)
        if abs(gap_pct) > self.config.gap_filter_pct:
            logger.debug(
                f"ORB skipping {stock}: gap {gap_pct:+.2f}% exceeds "
                f"±{self.config.gap_filter_pct}% filter"
            )
            return None

        # ── CHECK 2: SPREAD FILTER ────────────────────────────────────────
        # Skip if estimated bid-ask spread is too wide (illiquid conditions)
        spread_pct = market_context.get("spread_pct", 0)
        if spread_pct > self.config.spread_max_pct:
            logger.debug(
                f"ORB skipping {stock}: spread proxy {spread_pct:.3f}% "
                f"exceeds {self.config.spread_max_pct}%"
            )
            return None

        # ── Pre-compute filters that are the same for LONG and SHORT ──────
        is_long_breakout = ltp > orb_high + buffer
        is_short_breakout = ltp < orb_low - buffer

        if not is_long_breakout and not is_short_breakout:
            return None  # Price hasn't broken out yet — wait

        direction = "LONG" if is_long_breakout else "SHORT"

        # ── CHECK 3: NIFTY MARKET ALIGNMENT ──────────────────────────────
        if direction == "LONG" and nifty_dir == "BEARISH":
            logger.debug(f"ORB skipping LONG {stock}: NIFTY is BEARISH")
            return None
        if direction == "SHORT" and nifty_dir == "BULLISH":
            logger.debug(f"ORB skipping SHORT {stock}: NIFTY is BULLISH")
            return None

        # ── CHECK 4: VWAP ALIGNMENT ───────────────────────────────────────
        # LONG only when price is above VWAP (institutional support zone)
        # SHORT only when price is below VWAP (institutional resistance zone)
        is_above_vwap = market_context.get("is_above_vwap", True)
        vwap = market_context.get("vwap", 0)

        if direction == "LONG" and not is_above_vwap and vwap > 0:
            logger.debug(
                f"ORB skipping LONG {stock}: price below VWAP ({vwap:.2f})"
            )
            return None
        if direction == "SHORT" and is_above_vwap and vwap > 0:
            logger.debug(
                f"ORB skipping SHORT {stock}: price above VWAP ({vwap:.2f})"
            )
            return None

        # ── CHECK 5: VOLUME SPIKE ─────────────────────────────────────────
        # Current tick volume must be > 2x average volume of last N candles
        if len(candles) >= self.config.volume_lookback:
            if not self._check_volume_spike(candles):
                logger.debug(
                    f"ORB skipping {stock}: no volume spike (need "
                    f"{self.config.volume_spike_multiplier}x average)"
                )
                return None

        # ── CHECK 6: RSI FILTER ───────────────────────────────────────────
        # Skip if already in an exhausted move (overbought for LONG, oversold for SHORT)
        if len(candles) >= 15:  # Need at least 15 candles to compute RSI(14)
            rsi = self._calc_rsi(candles["Close"])
            if rsi is not None:
                if direction == "LONG" and rsi > self.config.rsi_overbought_entry:
                    logger.debug(
                        f"ORB skipping LONG {stock}: RSI {rsi:.1f} > "
                        f"{self.config.rsi_overbought_entry} (overbought)"
                    )
                    return None
                if direction == "SHORT" and rsi < self.config.rsi_oversold_entry:
                    logger.debug(
                        f"ORB skipping SHORT {stock}: RSI {rsi:.1f} < "
                        f"{self.config.rsi_oversold_entry} (oversold)"
                    )
                    return None

        # ── CHECK 7: PREV DAY LEVEL PROXIMITY ────────────────────────────
        # Skip if entry price is within 0.3% of prev day high, low, or close
        prev_day = market_context.get("prev_day", {})
        if prev_day:
            entry_candidate = (orb_high + buffer) if direction == "LONG" else (orb_low - buffer)
            if self._too_close_to_prev_levels(entry_candidate, prev_day):
                logger.debug(
                    f"ORB skipping {stock}: entry within "
                    f"{self.config.prev_day_proximity_pct}% of prev day H/L/C"
                )
                return None

        # ── ALL CHECKS PASSED — Build signal ─────────────────────────────
        # ORB uses final_exit_rr (2.5x from config.final_exit_rr) for its target
        # because it has a well-defined range and partial exit at 1x is planned.
        if direction == "LONG":
            entry = round(orb_high + buffer, 2)
            sl = round(orb_low, 2)
            target = round(entry + (risk * self.config.final_exit_rr), 2)
        else:
            entry = round(orb_low - buffer, 2)
            sl = round(orb_high, 2)
            target = round(entry - (risk * self.config.final_exit_rr), 2)

        confirmations = self._count_confirmations(
            range_pct, nifty_dir, direction, is_above_vwap, gap_pct
        )

        return Signal(
            stock=stock,
            token=token,
            direction=direction,
            entry_price=entry,
            stop_loss=sl,
            target=target,
            strategy_name=self.name,
            confidence=self._calc_confidence(range_pct, nifty_dir, direction, confirmations),
            reason=(
                f"ORB {direction}: price broke {'above' if direction == 'LONG' else 'below'} "
                f"{'high' if direction == 'LONG' else 'low'} ({orb_high if direction == 'LONG' else orb_low:.2f}). "
                f"Range: {range_pct:.1f}%. NIFTY: {nifty_dir}. VWAP: {'above' if is_above_vwap else 'below'}. "
                f"Gap: {gap_pct:+.2f}%. Confirmations: {confirmations}/5"
            ),
        )

    # ──────────────────────────────────────────────────────────
    # Indicator Helpers
    # ──────────────────────────────────────────────────────────

    def _check_volume_spike(self, candles: pd.DataFrame) -> bool:
        """
        Check if the most recent candle has a volume spike.

        A volume spike = current volume > N× the average of the last 20 candles.
        This confirms that real buying/selling pressure is driving the breakout,
        not just a few retail orders.

        We compare the last candle's volume to the previous 20 candles' average
        (excluding the current candle from the average to avoid bias).
        """
        lookback = self.config.volume_lookback
        multiplier = self.config.volume_spike_multiplier

        vol_series = candles["Volume"]
        if len(vol_series) < lookback + 1:
            return True  # Not enough data — give benefit of the doubt

        current_vol = vol_series.iloc[-1]
        avg_vol = vol_series.iloc[-(lookback + 1):-1].mean()

        if avg_vol <= 0:
            return True  # Can't compute — skip filter

        return current_vol >= avg_vol * multiplier

    def _calc_rsi(self, closes: pd.Series, period: int = 14) -> Optional[float]:
        """Calculate RSI using shared indicator function. Returns None if insufficient data."""
        if len(closes) < period + 1:
            return None
        rsi_series = calculate_rsi(closes, period=period)
        val = float(rsi_series.iloc[-1])
        return round(val, 1)

    def _too_close_to_prev_levels(self, price: float, prev_day: dict) -> bool:
        """
        Check if a price is within config.prev_day_proximity_pct of
        yesterday's High, Low, or Close.

        Why: These price levels are "remembered" by traders and act as
        natural support/resistance. Entering right at these levels reduces
        win rate because the price tends to stall or reverse there.

        Example: If prev_high = 1250 and proximity = 0.3%, skip entry
        if our entry price is between 1246.25 and 1253.75.
        """
        proximity = self.config.prev_day_proximity_pct / 100  # Convert % to decimal
        key_levels = [
            prev_day.get("prev_high", 0),
            prev_day.get("prev_low", 0),
            prev_day.get("prev_close", 0),
        ]

        for level in key_levels:
            if level <= 0:
                continue
            distance_pct = abs(price - level) / level
            if distance_pct < proximity:
                return True  # Too close to a key level

        return False

    def _count_confirmations(
        self,
        range_pct: float,
        nifty_dir: str,
        direction: str,
        is_above_vwap: bool,
        gap_pct: float,
    ) -> int:
        """Count how many bullish confirmations are present (for confidence scoring)."""
        count = 0
        if 0.5 <= range_pct <= 1.2:
            count += 1  # Ideal range size
        if direction == "LONG" and nifty_dir == "BULLISH":
            count += 1
        elif direction == "SHORT" and nifty_dir == "BEARISH":
            count += 1
        if direction == "LONG" and is_above_vwap:
            count += 1
        elif direction == "SHORT" and not is_above_vwap:
            count += 1
        if abs(gap_pct) < 0.5:  # Small gap = cleaner ORB setup
            count += 1
        if nifty_dir == "NEUTRAL":
            count += 0  # Neutral is okay, not a bonus
        return count

    def _calc_confidence(
        self,
        range_pct: float,
        nifty_dir: str,
        direction: str,
        confirmations: int,
    ) -> float:
        """
        Confidence score 0-1 based on number of bullish confirmations.
        5 confirmations = perfect setup (1.0 confidence).
        """
        base = 0.4  # Base for passing all required filters
        bonus = confirmations * 0.12  # Each confirmation adds 0.12
        return min(round(base + bonus, 2), 1.0)
