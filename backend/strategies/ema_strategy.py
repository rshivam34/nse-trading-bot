"""
EMA Crossover Strategy — Full Production Implementation
========================================================
Trades when the 9-period EMA crosses the 21-period EMA on 5-minute chart data.

What is an EMA Crossover?
- EMA9 (fast): reacts quickly to price changes
- EMA21 (slow): shows the bigger, slower trend
- When EMA9 crosses ABOVE EMA21 → short-term momentum turning bullish
- When EMA9 crosses BELOW EMA21 → short-term momentum turning bearish

Full confirmation checklist (ALL must pass):
1. EMA9 crossed EMA21 on the most recent tick (fresh signal, not stale)
2. Volume is ABOVE 20-candle average (momentum is real, not random)
3. RSI is not extreme (< 70 for longs, > 30 for shorts)
4. NIFTY direction is aligned
5. Price is on the correct side of VWAP (if available)
6. EMA separation is meaningful (EMAs crossing when nearly identical = noise)

SL placement:
- LONG: Below the recent swing low from last 10 ticks
- SHORT: Above the recent swing high from last 10 ticks

Target: 2× risk from entry

This strategy produces fewer but higher-quality signals than ORB.
Best on trending days (after regime detection shows TRENDING).
"""

import logging
from typing import Optional

import pandas as pd

from strategies.base_strategy import BaseStrategy, Signal

logger = logging.getLogger(__name__)

MIN_TICKS_NEEDED = 30            # Need 30+ ticks for meaningful 21-EMA calculation
MIN_EMA_SEPARATION_PCT = 0.05   # EMAs must be at least 0.05% apart to count as crossover


class EMACrossoverStrategy(BaseStrategy):
    """9 EMA / 21 EMA crossover momentum strategy with full confirmation."""

    def __init__(self, trading_config, indicator_config):
        super().__init__(name="EMA_CROSS")
        self.config = trading_config
        self.indicator_config = indicator_config
        self.is_active = True

        # Store previous EMA values per stock to detect crossovers
        self._prev_ema_fast: dict[str, float] = {}
        self._prev_ema_slow: dict[str, float] = {}

    def check_signal(
        self,
        stock: str,
        token: str,
        candles: pd.DataFrame,
        current_tick: dict,
        market_context: dict,
    ) -> Optional[Signal]:
        """Check if EMA9 just crossed EMA21 with all production confirmations."""

        if len(candles) < MIN_TICKS_NEEDED:
            return None

        closes = candles["Close"]

        ema_fast = self._ema(closes, self.indicator_config.ema_fast)
        ema_slow = self._ema(closes, self.indicator_config.ema_slow)

        if ema_fast is None or ema_slow is None:
            return None

        # Detect crossover: compare current vs previous
        prev_fast = self._prev_ema_fast.get(token, ema_fast)
        prev_slow = self._prev_ema_slow.get(token, ema_slow)

        self._prev_ema_fast[token] = ema_fast
        self._prev_ema_slow[token] = ema_slow

        ltp = current_tick.get("ltp", 0)
        if ltp <= 0:
            return None

        nifty_dir = market_context.get("nifty_direction", "NEUTRAL")
        is_above_vwap = market_context.get("is_above_vwap", True)
        vwap = market_context.get("vwap", 0)

        # ── Pre-checks that apply to both directions ──────────────────────
        # EMA separation must be meaningful (not just noise)
        separation_pct = abs(ema_fast - ema_slow) / ema_slow * 100
        if separation_pct < MIN_EMA_SEPARATION_PCT:
            return None  # EMAs too close — crossover signal is noise

        # Volume confirmation
        if not self._volume_above_average(candles):
            return None

        # ── BULLISH CROSSOVER ─────────────────────────────────────────────
        if (
            prev_fast <= prev_slow    # Was below (or equal)
            and ema_fast > ema_slow   # Now above — just crossed!
            and nifty_dir != "BEARISH"
            and self._rsi_ok(candles, "LONG")
            and (not vwap or ltp > vwap)  # Above VWAP if we have it
        ):
            # SL: below recent swing low
            recent_low = float(candles["Low"].iloc[-10:].min())
            sl = round(recent_low * 0.998, 2)  # 0.2% buffer below swing low
            entry = round(ltp, 2)
            risk = entry - sl

            if risk <= 0 or sl >= entry:
                return None

            target = round(entry + risk * self.config.risk_reward_ratio * 2, 2)

            separation_str = f"{separation_pct:.3f}%"
            confidence = self._calc_confidence(ema_fast, ema_slow, nifty_dir, "LONG")

            logger.info(
                f"EMA crossover LONG: {stock} | EMA9={ema_fast:.2f}, EMA21={ema_slow:.2f} | "
                f"Sep: {separation_str} | NIFTY: {nifty_dir}"
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
                    f"EMA9 ({ema_fast:.2f}) crossed above EMA21 ({ema_slow:.2f}). "
                    f"Separation: {separation_str}. Volume confirmed. "
                    f"NIFTY: {nifty_dir}."
                ),
            )

        # ── BEARISH CROSSOVER ─────────────────────────────────────────────
        if (
            prev_fast >= prev_slow    # Was above (or equal)
            and ema_fast < ema_slow   # Now below — just crossed!
            and nifty_dir != "BULLISH"
            and self._rsi_ok(candles, "SHORT")
            and (not vwap or ltp < vwap)
        ):
            recent_high = float(candles["High"].iloc[-10:].max())
            sl = round(recent_high * 1.002, 2)  # 0.2% buffer above swing high
            entry = round(ltp, 2)
            risk = sl - entry

            if risk <= 0 or sl <= entry:
                return None

            target = round(entry - risk * self.config.risk_reward_ratio * 2, 2)
            confidence = self._calc_confidence(ema_fast, ema_slow, nifty_dir, "SHORT")

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
                    f"EMA9 ({ema_fast:.2f}) crossed below EMA21 ({ema_slow:.2f}). "
                    f"Separation: {separation_pct:.3f}%. Volume confirmed. "
                    f"NIFTY: {nifty_dir}."
                ),
            )

        return None

    # ──────────────────────────────────────────────────────────
    # Indicator helpers
    # ──────────────────────────────────────────────────────────

    def _ema(self, series: pd.Series, period: int) -> Optional[float]:
        """Calculate latest EMA value using pandas ewm."""
        try:
            if len(series) < period:
                return None
            return float(series.ewm(span=period, adjust=False).mean().iloc[-1])
        except Exception:
            return None

    def _rsi_ok(self, candles: pd.DataFrame, direction: str, period: int = 14) -> bool:
        """
        Check RSI is not extreme before entering.
        LONG: RSI should not be > 70 (overbought)
        SHORT: RSI should not be < 30 (oversold)
        """
        if len(candles) < period + 1:
            return True  # Not enough data — give benefit of the doubt

        closes = candles["Close"]
        delta = closes.diff()
        gain = delta.clip(lower=0).rolling(period).mean()
        loss = (-delta.clip(upper=0)).rolling(period).mean()

        if loss.iloc[-1] == 0:
            rsi = 100.0
        else:
            rs = gain.iloc[-1] / loss.iloc[-1]
            rsi = 100 - (100 / (1 + rs))

        if direction == "LONG":
            return rsi <= self.config.rsi_overbought_entry   # Not overbought
        else:
            return rsi >= self.config.rsi_oversold_entry      # Not oversold

    def _volume_above_average(self, candles: pd.DataFrame, lookback: int = 20) -> bool:
        """
        Volume must be at or above the 20-candle average.
        EMA crossovers on low volume are unreliable (just drift, not momentum).
        """
        if len(candles) < lookback + 1:
            return True

        vol = candles["Volume"]
        current = vol.iloc[-1]
        avg = vol.iloc[-(lookback + 1):-1].mean()

        if avg <= 0:
            return True

        return current >= avg   # At least average volume

    def _calc_confidence(
        self, ema_fast: float, ema_slow: float, nifty_dir: str, direction: str
    ) -> float:
        """Score 0.0-1.0 for the crossover strength."""
        score = 0.4

        separation = abs(ema_fast - ema_slow) / ema_slow
        if separation > 0.003:      # >0.3% separation = strong signal
            score += 0.3
        elif separation > 0.001:    # >0.1% = moderate signal
            score += 0.2
        else:
            score += 0.1

        if (direction == "LONG" and nifty_dir == "BULLISH") or (
            direction == "SHORT" and nifty_dir == "BEARISH"
        ):
            score += 0.2
        elif nifty_dir == "NEUTRAL":
            score += 0.1

        return min(score, 1.0)
