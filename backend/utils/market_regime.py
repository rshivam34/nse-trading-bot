"""
Market Regime Detector — Identifies the Type of Market Day
===========================================================
Different market conditions require different trading approaches.
We detect the regime at 10:30 AM and adjust position sizes, SL widths,
and strategy preferences accordingly.

Four regimes:
1. TRENDING: NIFTY has moved >0.5% by 10:30 AM. Breakout strategies work best.
   → Full position sizes. Favor ORB and EMA crossover strategies.

2. RANGE_BOUND: NIFTY within 0.3% of open by 10:30 AM. Mean reversion works best.
   → Reduce breakout confidence. Favor VWAP bounce strategy.

3. VOLATILE: India VIX > 18 OR NIFTY daily range > 1.5% by 10:30 AM.
   → Widen stop-losses by 20%. Reduce position sizes by 30%.
   → Only take highest-confidence signals (score > 80 instead of 70).

4. GAP_DAY: NIFTY opened >0.7% above/below previous close.
   → Wait until 10:00 AM for gap fill/continuation before any trades.
   → Normal size after wait period.

Usage:
    detector = MarketRegimeDetector(config.trading)
    detector.set_prev_close(prev_nifty_close)
    # Call update_nifty(tick) on every NIFTY tick
    regime = detector.regime            # e.g., "TRENDING"
    multiplier = detector.get_size_multiplier()  # e.g., 0.7 for volatile
"""

import logging
from datetime import datetime, time

logger = logging.getLogger(__name__)

# Regime constants
TRENDING = "TRENDING"
RANGE_BOUND = "RANGE_BOUND"
VOLATILE = "VOLATILE"
GAP_DAY = "GAP_DAY"
UNKNOWN = "UNKNOWN"


class MarketRegimeDetector:
    """
    Tracks NIFTY movement throughout the day and determines the market regime.
    Called with every NIFTY tick by scanner.update_market_context().
    """

    def __init__(self, trading_config):
        self.config = trading_config

        # NIFTY tracking
        self.nifty_open: float = 0.0
        self.nifty_prev_close: float = 0.0
        self.nifty_high: float = 0.0
        self.nifty_low: float = 0.0
        self.nifty_current: float = 0.0

        # India VIX tracking (fed in via update_vix)
        self.vix_value: float = 0.0

        # Regime state
        self.regime: str = UNKNOWN
        self.regime_determined: bool = False
        self.regime_determined_at: str = ""

        # Description for dashboard
        self.regime_description: str = "Waiting for regime determination at 10:30 AM"

    def set_prev_close(self, prev_close: float):
        """Set previous day's NIFTY close (fetched at startup)."""
        self.nifty_prev_close = prev_close

    def update_vix(self, vix_value: float):
        """Update India VIX (called when VIX tick arrives)."""
        self.vix_value = vix_value

        # Re-evaluate if already determined — VIX can spike intraday
        if self.regime_determined and vix_value > self.config.volatile_vix_threshold:
            if self.regime != VOLATILE:
                logger.warning(
                    f"VIX spiked to {vix_value:.1f} — regime changing to VOLATILE"
                )
                self.regime = VOLATILE
                self.regime_description = (
                    f"VOLATILE (VIX spiked to {vix_value:.1f} intraday)"
                )

    def update_nifty(self, tick: dict):
        """
        Called on every NIFTY price tick.
        Updates tracking values and determines regime at 10:30 AM.
        """
        ltp = tick.get("ltp", 0)
        if not ltp:
            return

        self.nifty_current = ltp

        # Set open price from first tick of the day
        if not self.nifty_open:
            open_from_tick = tick.get("open", ltp)
            self.nifty_open = open_from_tick
            logger.info(f"NIFTY open price set: {self.nifty_open:.2f}")

        # Track intraday high/low
        high_today = tick.get("high", ltp)
        low_today = tick.get("low", ltp)
        if high_today > self.nifty_high or self.nifty_high == 0:
            self.nifty_high = high_today
        if low_today < self.nifty_low or self.nifty_low == 0:
            self.nifty_low = low_today

        # Determine regime at 10:30 AM (only once)
        now = datetime.now().time()
        if not self.regime_determined and now >= self.config.regime_determination_time:
            self._determine_regime(ltp)

    def _determine_regime(self, current_nifty: float):
        """
        Determines and locks in the market regime for the day.
        Called once at 10:30 AM.
        """
        if not self.nifty_open:
            logger.warning("Cannot determine regime: NIFTY open price unknown")
            self.regime = UNKNOWN
            return

        now_str = datetime.now().strftime("%H:%M:%S")

        # ── CHECK 1: GAP DAY ─────────────────────────────────────────────
        # Did NIFTY open significantly above/below yesterday's close?
        if self.nifty_prev_close > 0:
            gap_pct = abs(
                (self.nifty_open - self.nifty_prev_close) / self.nifty_prev_close
            ) * 100

            if gap_pct >= self.config.gap_day_nifty_threshold_pct:
                self.regime = GAP_DAY
                self.regime_determined = True
                self.regime_determined_at = now_str
                self.regime_description = (
                    f"GAP DAY: NIFTY gapped {gap_pct:+.1f}% from prev close "
                    f"({self.nifty_prev_close:.0f} → {self.nifty_open:.0f}). "
                    "Waiting until 10:00 AM before trading."
                )
                logger.info(f"Market regime: {self.regime_description}")
                return

        # ── CHECK 2: VOLATILE ────────────────────────────────────────────
        # VIX too high or NIFTY daily range too wide?
        nifty_range_pct = 0.0
        if self.nifty_open > 0 and self.nifty_high > 0 and self.nifty_low > 0:
            nifty_range_pct = (
                (self.nifty_high - self.nifty_low) / self.nifty_open
            ) * 100

        if (
            self.vix_value > self.config.volatile_vix_threshold
            or nifty_range_pct > self.config.volatile_nifty_range_pct
        ):
            self.regime = VOLATILE
            self.regime_determined = True
            self.regime_determined_at = now_str
            self.regime_description = (
                f"VOLATILE: VIX={self.vix_value:.1f}, "
                f"NIFTY range={nifty_range_pct:.1f}%. "
                "SL widened +20%, position sizes reduced -30%."
            )
            logger.info(f"Market regime: {self.regime_description}")
            return

        # ── CHECK 3: TRENDING ─────────────────────────────────────────────
        # NIFTY moved more than 0.5% from open?
        nifty_move_pct = 0.0
        if self.nifty_open > 0:
            nifty_move_pct = abs(
                (current_nifty - self.nifty_open) / self.nifty_open
            ) * 100

        if nifty_move_pct >= self.config.trending_nifty_move_pct:
            direction = "UP" if current_nifty > self.nifty_open else "DOWN"
            self.regime = TRENDING
            self.regime_determined = True
            self.regime_determined_at = now_str
            self.regime_description = (
                f"TRENDING {direction}: NIFTY moved {nifty_move_pct:.1f}% from open. "
                "Breakout strategies favored. Full position sizes."
            )
            logger.info(f"Market regime: {self.regime_description}")
            return

        # ── CHECK 4: RANGE-BOUND ───────────────────────────────────────────
        if nifty_move_pct <= self.config.range_bound_nifty_pct:
            self.regime = RANGE_BOUND
            self.regime_determined = True
            self.regime_determined_at = now_str
            self.regime_description = (
                f"RANGE-BOUND: NIFTY within {nifty_move_pct:.1f}% of open. "
                "VWAP bounce favored. Reduce breakout confidence."
            )
            logger.info(f"Market regime: {self.regime_description}")
            return

        # Default: unknown (between range and trending thresholds)
        self.regime = UNKNOWN
        self.regime_determined = True
        self.regime_determined_at = now_str
        self.regime_description = (
            f"MIXED: NIFTY moved {nifty_move_pct:.1f}%. Waiting for clearer direction."
        )

    # ──────────────────────────────────────────────────────────
    # Strategy adjustment multipliers
    # ──────────────────────────────────────────────────────────

    def get_size_multiplier(self) -> float:
        """
        Position size multiplier based on regime.
        - TRENDING: slightly larger (1.1×) — momentum is clear
        - VOLATILE: smaller (0.7×) — protect capital in choppy conditions
        - Others: normal (1.0×)
        """
        if self.regime == VOLATILE:
            return 0.7   # Reduce by 30%
        if self.regime == TRENDING:
            return 1.1   # Increase by 10%
        return 1.0

    def get_sl_multiplier(self) -> float:
        """
        Stop-loss width multiplier based on regime.
        - VOLATILE: wider SL (1.2×) to avoid premature stops in choppy market
        - Others: normal (1.0×)
        """
        if self.regime == VOLATILE:
            return 1.2   # Widen SL by 20%
        return 1.0

    def get_min_score_override(self) -> int:
        """
        Override minimum score threshold based on regime.
        - VOLATILE: require higher confidence (80 instead of 70)
        - Others: use config default
        """
        if self.regime == VOLATILE:
            return 80  # Only take the best setups in volatile markets
        return 0  # 0 = use config default

    def should_wait_for_gap_fill(self) -> bool:
        """
        On gap days, wait until 10:00 AM before trading.
        Returns True if we should skip new trades right now.
        """
        if self.regime == GAP_DAY:
            now = datetime.now().time()
            return now < self.config.gap_day_wait_until
        return False

    def to_dict(self) -> dict:
        """Serialize regime state for Firebase/dashboard."""
        return {
            "regime": self.regime,
            "description": self.regime_description,
            "determined_at": self.regime_determined_at,
            "nifty_open": self.nifty_open,
            "nifty_current": self.nifty_current,
            "nifty_range_pct": round(
                ((self.nifty_high - self.nifty_low) / self.nifty_open * 100)
                if self.nifty_open else 0, 2
            ),
            "vix": self.vix_value,
            "size_multiplier": self.get_size_multiplier(),
            "sl_multiplier": self.get_sl_multiplier(),
        }
