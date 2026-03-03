"""
VWAP Bounce Strategy — Full Production Implementation
======================================================
Trades pullbacks to VWAP in stocks that have been trending above/below it.

What is a VWAP Bounce?
When a stock has been trading above VWAP for 30+ minutes (institutional support),
a pullback to VWAP and a recovery (green candle forming) is a high-probability
long entry. Institutions often add to positions at VWAP.

LONG Setup:
1. Stock must have been above VWAP for at least 60 ticks (~30 min at NSE tick frequency)
2. Price pulls back to within 0.2% of VWAP from ABOVE
3. The most recent candle's close must be ABOVE the open (green candle = recovery)
4. Volume is not below average (no selling into the bounce)
5. NIFTY direction is BULLISH or NEUTRAL
6. RSI is not overbought (< 70)
Entry: Close of the bounce candle
SL: 0.3% below VWAP (if it breaks VWAP cleanly, setup is invalid)
Target: Previous swing high above current price (or 1.5× risk minimum)

SHORT Setup: Mirror image — below VWAP, bounce UP to VWAP, red candle at VWAP.
"""

import logging
from typing import Optional

import pandas as pd

from strategies.base_strategy import BaseStrategy, Signal

logger = logging.getLogger(__name__)

MIN_TICKS_NEEDED = 60    # Need 60 ticks for the "30+ min above VWAP" check
SL_BUFFER_PCT = 0.3      # 0.3% SL below/above VWAP
BOUNCE_THRESHOLD_PCT = 0.2  # Price must be within 0.2% of VWAP


class VWAPBounceStrategy(BaseStrategy):
    """
    VWAP bounce: buy dips to VWAP in uptrending stocks.
    Full production implementation with candle confirmation and trend requirement.
    """

    def __init__(self, trading_config, indicator_config):
        super().__init__(name="VWAP_BOUNCE")
        self.config = trading_config
        self.indicator_config = indicator_config
        self.is_active = True

        # Track how long each stock has been above/below VWAP
        # {token: count_of_ticks_above_vwap}
        self._ticks_above_vwap: dict[str, int] = {}
        self._ticks_below_vwap: dict[str, int] = {}

    def check_signal(
        self,
        stock: str,
        token: str,
        candles: pd.DataFrame,
        current_tick: dict,
        market_context: dict,
    ) -> Optional[Signal]:
        """Check for VWAP bounce pattern with full production conditions."""

        if len(candles) < MIN_TICKS_NEEDED:
            return None

        # VWAP is pre-computed by scanner and passed in context
        vwap = market_context.get("vwap", 0)
        if vwap <= 0:
            # Fallback: compute it ourselves
            vwap = self._calculate_vwap(candles)
        if vwap <= 0:
            return None

        ltp = current_tick.get("ltp", 0)
        if ltp <= 0:
            return None

        nifty_dir = market_context.get("nifty_direction", "NEUTRAL")
        distance_pct = abs(ltp - vwap) / vwap * 100

        # Update VWAP trend counter for this stock
        self._update_vwap_position(token, ltp, vwap)

        # ── LONG SETUP ───────────────────────────────────────────────────
        if (
            nifty_dir != "BEARISH"
            and distance_pct <= BOUNCE_THRESHOLD_PCT  # Price near VWAP
            and ltp >= vwap                            # Price still at or above VWAP
            and self._has_been_above_vwap_long_enough(token)  # Trending above 30+ min
            and self._is_green_candle(candles)                # Bounce confirmation
            and self._rsi_not_overbought(candles)             # RSI check
            and self._volume_adequate(candles)                 # Not weak volume
        ):
            entry = round(ltp, 2)
            sl = round(vwap * (1 - SL_BUFFER_PCT / 100), 2)
            risk = entry - sl

            if risk <= 0:
                return None

            # Target: previous swing high or 1.5× risk minimum
            swing_high = float(candles["High"].iloc[-30:].max())
            target = max(
                round(swing_high, 2) if swing_high > entry else 0,
                round(entry + risk * self.config.risk_reward_ratio, 2),
            )

            return Signal(
                stock=stock,
                token=token,
                direction="LONG",
                entry_price=entry,
                stop_loss=sl,
                target=target,
                strategy_name=self.name,
                confidence=self._calc_confidence(distance_pct, nifty_dir, "LONG"),
                reason=(
                    f"VWAP Bounce LONG: {stock} ({ltp:.2f}) pulled back to VWAP "
                    f"({vwap:.2f}), green candle recovery. "
                    f"Above VWAP for {self._ticks_above_vwap.get(token, 0)} ticks. "
                    f"NIFTY: {nifty_dir}"
                ),
            )

        # ── SHORT SETUP ──────────────────────────────────────────────────
        if (
            nifty_dir != "BULLISH"
            and distance_pct <= BOUNCE_THRESHOLD_PCT  # Price near VWAP
            and ltp <= vwap                            # Price at or below VWAP
            and self._has_been_below_vwap_long_enough(token)  # Trending below 30+ min
            and self._is_red_candle(candles)                   # Rejection confirmation
            and self._rsi_not_oversold(candles)                # RSI check
            and self._volume_adequate(candles)
        ):
            entry = round(ltp, 2)
            sl = round(vwap * (1 + SL_BUFFER_PCT / 100), 2)
            risk = sl - entry

            if risk <= 0:
                return None

            swing_low = float(candles["Low"].iloc[-30:].min())
            target = min(
                round(swing_low, 2) if swing_low < entry else float("inf"),
                round(entry - risk * self.config.risk_reward_ratio, 2),
            )
            target = round(entry - risk * self.config.risk_reward_ratio, 2)

            return Signal(
                stock=stock,
                token=token,
                direction="SHORT",
                entry_price=entry,
                stop_loss=sl,
                target=target,
                strategy_name=self.name,
                confidence=self._calc_confidence(distance_pct, nifty_dir, "SHORT"),
                reason=(
                    f"VWAP Bounce SHORT: {stock} ({ltp:.2f}) bounced UP to VWAP "
                    f"({vwap:.2f}), red candle rejection. "
                    f"Below VWAP for {self._ticks_below_vwap.get(token, 0)} ticks. "
                    f"NIFTY: {nifty_dir}"
                ),
            )

        return None

    # ──────────────────────────────────────────────────────────
    # Trend duration tracking
    # ──────────────────────────────────────────────────────────

    def _update_vwap_position(self, token: str, ltp: float, vwap: float):
        """
        Track how many consecutive ticks this stock has been above/below VWAP.

        Why: We only trade a VWAP bounce if the stock has been above VWAP
        for at least 30 minutes (config.vwap_trend_min_ticks = 60 ticks).
        A stock that just crossed VWAP isn't "trending" — it's just fluctuating.
        """
        if ltp > vwap:
            self._ticks_above_vwap[token] = self._ticks_above_vwap.get(token, 0) + 1
            self._ticks_below_vwap[token] = 0   # Reset below counter
        elif ltp < vwap:
            self._ticks_below_vwap[token] = self._ticks_below_vwap.get(token, 0) + 1
            self._ticks_above_vwap[token] = 0   # Reset above counter

    def _has_been_above_vwap_long_enough(self, token: str) -> bool:
        """True if stock has been above VWAP for enough ticks (~30 min)."""
        min_ticks = self.indicator_config.vwap_trend_min_ticks
        return self._ticks_above_vwap.get(token, 0) >= min_ticks

    def _has_been_below_vwap_long_enough(self, token: str) -> bool:
        """True if stock has been below VWAP for enough ticks (~30 min)."""
        min_ticks = self.indicator_config.vwap_trend_min_ticks
        return self._ticks_below_vwap.get(token, 0) >= min_ticks

    # ──────────────────────────────────────────────────────────
    # Candle analysis
    # ──────────────────────────────────────────────────────────

    def _is_green_candle(self, candles: pd.DataFrame) -> bool:
        """
        Check if the most recent "candle" is green (close > open).
        A green candle at VWAP = buyers are stepping in = bounce confirmation.

        With tick data we use: latest close > earliest close in last 5 ticks.
        """
        try:
            if len(candles) < 5:
                return False
            recent_close = float(candles["Close"].iloc[-1])
            candle_open = float(candles["Close"].iloc[-5])  # Close 5 ticks ago = "open"
            return recent_close > candle_open
        except Exception:
            return False

    def _is_red_candle(self, candles: pd.DataFrame) -> bool:
        """Check if the most recent candle is red (close < open)."""
        try:
            if len(candles) < 5:
                return False
            recent_close = float(candles["Close"].iloc[-1])
            candle_open = float(candles["Close"].iloc[-5])
            return recent_close < candle_open
        except Exception:
            return False

    def _rsi_not_overbought(self, candles: pd.DataFrame, threshold: float = 70.0) -> bool:
        """True if RSI is not overbought — don't enter long if already stretched."""
        rsi = self._calc_rsi(candles["Close"])
        return rsi is None or rsi <= threshold

    def _rsi_not_oversold(self, candles: pd.DataFrame, threshold: float = 30.0) -> bool:
        """True if RSI is not oversold — don't enter short if already stretched."""
        rsi = self._calc_rsi(candles["Close"])
        return rsi is None or rsi >= threshold

    def _calc_rsi(self, closes: pd.Series, period: int = 14) -> Optional[float]:
        """Calculate RSI (14) from close prices."""
        if len(closes) < period + 1:
            return None
        delta = closes.diff()
        gain = delta.clip(lower=0).rolling(period).mean()
        loss = (-delta.clip(upper=0)).rolling(period).mean()
        if loss.iloc[-1] == 0:
            return 100.0
        rs = gain.iloc[-1] / loss.iloc[-1]
        return round(100 - (100 / (1 + rs)), 1)

    def _volume_adequate(self, candles: pd.DataFrame) -> bool:
        """True if current volume is not significantly below average (not a dead market)."""
        if len(candles) < 21:
            return True
        vol = candles["Volume"]
        current = vol.iloc[-1]
        avg = vol.iloc[-21:-1].mean()
        if avg <= 0:
            return True
        return current >= avg * 0.5   # Volume must be at least 50% of average

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

    def _calc_confidence(self, distance_pct: float, nifty_dir: str, direction: str) -> float:
        """Score 0.0-1.0 for the bounce quality."""
        score = 0.5  # Base (all conditions passed = minimum 0.5)

        if distance_pct < 0.05:    # Within 0.05% of VWAP = very precise bounce
            score += 0.3
        elif distance_pct < 0.1:   # Within 0.1% = good
            score += 0.2
        else:
            score += 0.1

        if direction == "LONG" and nifty_dir == "BULLISH":
            score += 0.2
        elif direction == "SHORT" and nifty_dir == "BEARISH":
            score += 0.2
        elif nifty_dir == "NEUTRAL":
            score += 0.1

        return min(score, 1.0)

    def reset_daily(self):
        """Reset per-stock tracking at start of new trading day."""
        self._ticks_above_vwap.clear()
        self._ticks_below_vwap.clear()
