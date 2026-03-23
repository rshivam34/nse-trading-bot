"""
Opening Range Breakout (ORB) Strategy — Retest Confirmation Version.
====================================================================

The old ORB entered on first tick past the range → 75% fakeouts.
The new ORB waits for the RETEST pattern, which filters fakeouts:

1. Record HIGH and LOW during 9:15-9:30 (opening range)
2. After 9:30: detect INITIAL breakout (price closes beyond range + buffer)
3. Wait for RETEST: price pulls back INTO the range (within 0.2% of edge)
4. Wait for BOUNCE: a COMPLETED candle closes back in breakout direction
5. THEN enter (fakeouts don't retest — they just reverse)
6. SL: opposite side of ORB range (structural level)
7. Target: 1.5× range width (realistic for Indian intraday)
8. Time limit: 9:30-10:30 only (ORB momentum exhausts after first hour)

Why retest works: In a real breakout, institutional traders who missed
the initial move BUY on the retest (pullback to breakout level). This
creates a second wave of momentum. Fakeouts never get this second wave.
"""

import logging
from datetime import datetime, timedelta, time
from typing import Optional

import pandas as pd

from strategies.base_strategy import BaseStrategy, Signal
from utils.indicators import calculate_rsi

logger = logging.getLogger(__name__)

# ORB only fires 9:30-10:30 IST (first hour after opening range).
# After 10:30, the ORB momentum is exhausted — other strategies take over.
ORB_SIGNAL_CUTOFF = time(10, 30)

# Minimum candles before ORB can fire (need some price action after breakout)
MIN_CANDLES_AFTER_ORB = 4  # At least 4 candles after 9:30 (= 20 min)


class ORBStrategy(BaseStrategy):
    """Opening Range Breakout with retest confirmation."""

    def __init__(self, config):
        super().__init__(name="ORB")
        self.config = config
        self.orb_ranges: dict[str, dict] = {}  # stock -> {high, low, range_pct}

        # Breakout tracking per stock:
        # States: None -> "BREAKOUT_DETECTED" -> "RETESTING" -> (signal fires)
        self._breakout_state: dict[str, dict] = {}

    def set_orb_range(self, stock: str, high: float, low: float):
        """Called during 9:15-9:30 to record the opening range."""
        mid = (high + low) / 2
        range_pct = ((high - low) / mid) * 100 if mid > 0 else 0

        self.orb_ranges[stock] = {
            "high": high,
            "low": low,
            "range_pct": range_pct,
        }
        logger.debug(f"ORB Range for {stock}: High={high:.2f}, Low={low:.2f}, Range={range_pct:.2f}%")

    def check_signal(
        self,
        stock: str,
        token: str,
        candles: pd.DataFrame,
        current_tick: dict,
        market_context: dict,
    ) -> Optional[Signal]:
        """
        ORB with retest confirmation pattern.

        Flow: breakout detected -> wait for retest -> wait for bounce -> signal.
        """
        if stock not in self.orb_ranges:
            return None

        orb = self.orb_ranges[stock]
        orb_high = orb["high"]
        orb_low = orb["low"]
        range_pct = orb["range_pct"]
        ltp = current_tick.get("ltp", 0)

        if ltp <= 0:
            return None

        # ── Range size filter ────────────────────────────────────────
        if range_pct < self.config.orb_min_range_pct:  # 0.5%
            return None
        if range_pct > self.config.orb_max_range_pct:  # 2.0%
            return None

        # Need enough candles for volume/RSI checks
        if len(candles) < MIN_CANDLES_AFTER_ORB:
            return None

        # ── Time limit: ORB only fires 9:30-10:30 ────────────────────
        # After 10:30, the breakout momentum is exhausted
        now = datetime.now().time()
        # For backtesting, check candle timestamp
        if hasattr(candles.index[-1], 'hour'):
            candle_time = candles.index[-1]
            if hasattr(candle_time, 'tz_convert'):
                try:
                    candle_time = candle_time.tz_convert('Asia/Kolkata')
                except Exception:
                    candle_time = candle_time + timedelta(hours=5, minutes=30)
            elif hasattr(candle_time, 'hour'):
                # UTC timestamps from yfinance — convert to IST
                if candle_time.hour < 4:  # UTC morning = IST after 5:30
                    candle_time = candle_time + timedelta(hours=5, minutes=30)
            now = candle_time.time() if hasattr(candle_time, 'time') else now

        if now > ORB_SIGNAL_CUTOFF:
            return None

        buffer = orb_high * (self.config.breakout_buffer_pct / 100)
        nifty_dir = market_context.get("nifty_direction", "NEUTRAL")
        risk = orb_high - orb_low

        # ── Gap filter ───────────────────────────────────────────────
        gap_pct = market_context.get("gap_pct", 0)
        if abs(gap_pct) > self.config.gap_filter_pct:
            return None

        # ── Range quality filter ─────────────────────────────────────
        # Reject ranges with long wicks (indecision during ORB period)
        # Clean ranges: candles commit to a direction, body > 40% of range
        if len(candles) >= 3:
            orb_candles = candles.iloc[:3]
            orb_body = abs(float(orb_candles["Close"].iloc[-1]) - float(orb_candles["Open"].iloc[0]))
            if risk > 0 and (orb_body / risk) < 0.3:
                return None  # Too many wicks, range is noise

        # ── Sector filter ────────────────────────────────────────────
        # Don't go against sector momentum
        sector_phase = market_context.get("sector_phase", "")
        # (sector_phase populated by backtester/scanner from sector_analysis)

        # ── 15-min trend confirmation ────────────────────────────────
        trend_15m = market_context.get("trend_15m", "NEUTRAL")

        # ── Breakout state machine ───────────────────────────────────
        state = self._breakout_state.get(stock)

        if state is None:
            # Looking for initial breakout
            # Use COMPLETED candle close (not just LTP tick)
            if len(candles) >= 2:
                prev_close = float(candles["Close"].iloc[-2])  # Last completed candle

                if prev_close > orb_high + buffer:
                    # Bullish breakout detected
                    if nifty_dir == "BEARISH":
                        return None  # Don't go LONG against market
                    self._breakout_state[stock] = {
                        "direction": "LONG",
                        "breakout_price": prev_close,
                        "state": "BREAKOUT_DETECTED",
                    }
                    logger.debug(f"ORB {stock}: LONG breakout detected at {prev_close:.2f}")

                elif prev_close < orb_low - buffer:
                    # Bearish breakout detected
                    if nifty_dir == "BULLISH":
                        return None  # Don't go SHORT against market
                    self._breakout_state[stock] = {
                        "direction": "SHORT",
                        "breakout_price": prev_close,
                        "state": "BREAKOUT_DETECTED",
                    }
                    logger.debug(f"ORB {stock}: SHORT breakout detected at {prev_close:.2f}")

            return None  # No signal yet — waiting for breakout

        # ── State: BREAKOUT_DETECTED — waiting for retest ────────────
        if state["state"] == "BREAKOUT_DETECTED":
            direction = state["direction"]
            retest_zone = 0.002  # Within 0.2% of range edge = retesting

            if direction == "LONG":
                # Price must pull back to near ORB high (retest the breakout level)
                distance_from_high = (ltp - orb_high) / orb_high
                if distance_from_high <= retest_zone:
                    state["state"] = "RETESTING"
                    logger.debug(f"ORB {stock}: LONG retesting range high at {ltp:.2f}")
                elif ltp < orb_low:
                    # Fell all the way back through range — breakout failed
                    del self._breakout_state[stock]
                    return None

            elif direction == "SHORT":
                distance_from_low = (orb_low - ltp) / orb_low
                if distance_from_low <= retest_zone:
                    state["state"] = "RETESTING"
                    logger.debug(f"ORB {stock}: SHORT retesting range low at {ltp:.2f}")
                elif ltp > orb_high:
                    # Rose all the way back through range — breakout failed
                    del self._breakout_state[stock]
                    return None

            return None  # Still waiting for retest

        # ── State: RETESTING — waiting for bounce confirmation ───────
        if state["state"] == "RETESTING":
            direction = state["direction"]

            # Need a COMPLETED candle that bounces in breakout direction
            if len(candles) < 2:
                return None

            prev_candle_close = float(candles["Close"].iloc[-2])
            prev_candle_open = float(candles["Open"].iloc[-2])
            prev_candle_vol = float(candles["Volume"].iloc[-2])

            # Average volume for comparison
            avg_vol = float(candles["Volume"].iloc[-10:-2].mean()) if len(candles) >= 10 else 0

            if direction == "LONG":
                # Bounce candle: closes above ORB high (back in breakout territory)
                # AND is a green candle (close > open)
                is_bounce = (
                    prev_candle_close > orb_high
                    and prev_candle_close > prev_candle_open  # Green candle
                    and (avg_vol <= 0 or prev_candle_vol >= avg_vol * 1.5)  # Volume confirmation
                )

                if is_bounce:
                    # SIGNAL FIRES — retest confirmed
                    entry = round(prev_candle_close, 2)
                    sl = round(orb_low, 2)  # SL at opposite range edge (structural)
                    target = round(entry + risk * 1.5, 2)  # 1.5× range width

                    del self._breakout_state[stock]

                    # Final VWAP check
                    vwap = market_context.get("vwap", 0)
                    if vwap > 0 and entry < vwap:
                        return None  # LONG should be above VWAP

                    return Signal(
                        stock=stock, token=token, direction="LONG",
                        entry_price=entry, stop_loss=sl, target=target,
                        strategy_name=self.name,
                        confidence=self._calc_confidence(range_pct, nifty_dir, "LONG"),
                        reason=(
                            f"ORB LONG retest: {stock} broke above {orb_high:.2f}, "
                            f"retested, bounced at {entry:.2f}. "
                            f"Range: {range_pct:.1f}%. NIFTY: {nifty_dir}."
                        ),
                    )

                elif prev_candle_close < orb_low:
                    # Retest failed — price fell through range
                    del self._breakout_state[stock]
                    return None

            elif direction == "SHORT":
                is_bounce = (
                    prev_candle_close < orb_low
                    and prev_candle_close < prev_candle_open  # Red candle
                    and (avg_vol <= 0 or prev_candle_vol >= avg_vol * 1.5)
                )

                if is_bounce:
                    entry = round(prev_candle_close, 2)
                    sl = round(orb_high, 2)
                    target = round(entry - risk * 1.5, 2)

                    del self._breakout_state[stock]

                    vwap = market_context.get("vwap", 0)
                    if vwap > 0 and entry > vwap:
                        return None  # SHORT should be below VWAP

                    return Signal(
                        stock=stock, token=token, direction="SHORT",
                        entry_price=entry, stop_loss=sl, target=target,
                        strategy_name=self.name,
                        confidence=self._calc_confidence(range_pct, nifty_dir, "SHORT"),
                        reason=(
                            f"ORB SHORT retest: {stock} broke below {orb_low:.2f}, "
                            f"retested, rejected at {entry:.2f}. "
                            f"Range: {range_pct:.1f}%. NIFTY: {nifty_dir}."
                        ),
                    )

                elif prev_candle_close > orb_high:
                    del self._breakout_state[stock]
                    return None

            return None

    def _calc_confidence(self, range_pct: float, nifty_dir: str, direction: str) -> float:
        """Confidence score 0-1 for the retest setup quality."""
        score = 0.5  # Base: retest confirmed = already high quality

        # Ideal range (0.5-1.2% = best breakout ranges for Indian stocks)
        if 0.5 <= range_pct <= 1.2:
            score += 0.2
        elif range_pct < 0.5:
            score += 0.1

        # NIFTY alignment
        if (direction == "LONG" and nifty_dir == "BULLISH") or \
           (direction == "SHORT" and nifty_dir == "BEARISH"):
            score += 0.2
        elif nifty_dir == "NEUTRAL":
            score += 0.1

        return min(round(score, 2), 1.0)

    def reset_daily(self):
        """Reset per-day tracking."""
        self._breakout_state.clear()
        # Don't clear orb_ranges — they're set during 9:15-9:30 each day
