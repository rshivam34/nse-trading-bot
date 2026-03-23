"""
NIFTY/BANKNIFTY Options Strategy — ORB-Based Option Buying.
============================================================

Uses the ORB retest pattern on NIFTY/BANKNIFTY index to buy options.
- NIFTY ORB breaks UP → buy ATM CALL
- NIFTY ORB breaks DOWN → buy ATM PUT

Why options? A 0.5% NIFTY move = 10-30% option premium move.
The same ORB signal captures 3-5× more on options vs equity.

Risk management:
- SL: 30% premium loss (if option drops 30% from entry, exit)
- Target: 50% premium gain
- Max loss per trade: premium paid (limited risk)
- Exit by 2 PM (theta decay accelerates in last 2 hours)
- Only weekly expiry options (most liquid, tightest spreads)

Capital: Works with Rs.15K (NIFTY weekly ATM options cost Rs.100-500/lot)
Lot sizes: NIFTY = 25 units, BANKNIFTY = 15 units

For backtesting: Uses delta approximation (ATM delta ~0.5) to simulate
option premium movement from NIFTY index movement.
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, time
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)

# ORB signal only valid 9:30-10:30 (same as equity ORB)
ORB_SIGNAL_CUTOFF = time(10, 30)
# Exit options by 2 PM (theta decay kills afternoon holders)
OPTIONS_EXIT_TIME = time(14, 0)

# Option parameters
ATM_DELTA = 0.5          # ATM option delta (approximate)
NIFTY_LOT_SIZE = 25
BANKNIFTY_LOT_SIZE = 15


@dataclass
class OptionSignal:
    """Signal to buy a NIFTY/BANKNIFTY option."""
    index: str               # "NIFTY" or "BANKNIFTY"
    direction: str           # "CALL" or "PUT"
    strike: float            # ATM strike price
    entry_premium: float     # Estimated entry premium
    sl_premium: float        # SL at 30% loss
    target_premium: float    # Target at 50% gain
    lot_size: int
    index_entry: float       # Index level at signal time
    index_sl: float          # Index SL (ORB range opposite side)
    index_target: float      # Index target
    reason: str = ""


class NiftyOptionsStrategy:
    """
    ORB-based NIFTY/BANKNIFTY option buying strategy.

    Usage (backtesting):
        strat = NiftyOptionsStrategy(config)
        strat.set_orb_range(nifty_high, nifty_low)
        signal = strat.check_signal(nifty_candles, current_candle)
        if signal:
            # Buy the option, track by premium
    """

    def __init__(self, config, min_range_pct: float = 0.2, max_range_pct: float = 2.0):
        self.config = config
        self._min_range_pct = min_range_pct
        self._max_range_pct = max_range_pct
        self.orb_high: float = 0
        self.orb_low: float = 0
        self.orb_range_set: bool = False
        self._breakout_detected: Optional[str] = None  # "CALL" or "PUT"
        self._breakout_price: float = 0
        self._retesting: bool = False
        self._signal_fired: bool = False

    def set_orb_range(self, high: float, low: float):
        """Set ORB range from 9:15-9:30 NIFTY candles."""
        self.orb_high = high
        self.orb_low = low
        self.orb_range_set = True
        self._breakout_detected = None
        self._retesting = False
        self._signal_fired = False
        logger.debug(f"NIFTY ORB Range: {low:.0f} - {high:.0f} ({(high-low)/low*100:.2f}%)")

    def check_signal(
        self,
        nifty_candles: pd.DataFrame,
        vix: float = 15.0,
    ) -> Optional[OptionSignal]:
        """
        Check for NIFTY ORB breakout + retest → option buy signal.

        Args:
            nifty_candles: NIFTY 5-min candles (must have Close column)
            vix: Current VIX (skip if > 25 DANGER)

        Returns:
            OptionSignal or None
        """
        if not self.orb_range_set or self._signal_fired:
            return None

        if len(nifty_candles) < 4:
            return None

        # VIX gate
        if vix > 25:
            return None

        orb_range = self.orb_high - self.orb_low
        mid = (self.orb_high + self.orb_low) / 2
        range_pct = (orb_range / mid) * 100

        # Range size filter (index-specific — BANKNIFTY is more volatile)
        min_range = self._min_range_pct
        max_range = self._max_range_pct
        if range_pct < min_range or range_pct > max_range:
            return None

        buffer = mid * 0.001  # 0.1% buffer for NIFTY (tighter than equity)
        prev_close = float(nifty_candles["Close"].iloc[-2])
        ltp = float(nifty_candles["Close"].iloc[-1])

        # ── Breakout detection ───────────────────────────────────────
        if self._breakout_detected is None:
            if prev_close > self.orb_high + buffer:
                self._breakout_detected = "CALL"
                self._breakout_price = prev_close
            elif prev_close < self.orb_low - buffer:
                self._breakout_detected = "PUT"
                self._breakout_price = prev_close
            return None

        # ── Retest detection ─────────────────────────────────────────
        if not self._retesting:
            if self._breakout_detected == "CALL":
                if ltp <= self.orb_high * 1.001:  # Pulled back to range high
                    self._retesting = True
                elif ltp < self.orb_low:  # Failed breakout
                    self._breakout_detected = None
                    return None
            elif self._breakout_detected == "PUT":
                if ltp >= self.orb_low * 0.999:
                    self._retesting = True
                elif ltp > self.orb_high:
                    self._breakout_detected = None
                    return None
            return None

        # ── Bounce confirmation ──────────────────────────────────────
        prev_candle_close = float(nifty_candles["Close"].iloc[-2])
        prev_candle_open = float(nifty_candles["Open"].iloc[-2])

        if self._breakout_detected == "CALL":
            is_bounce = prev_candle_close > self.orb_high and prev_candle_close > prev_candle_open
            if is_bounce:
                self._signal_fired = True
                # ATM strike: round NIFTY to nearest 50
                strike = round(ltp / 50) * 50
                # Estimate premium using delta approximation
                estimated_premium = max(50, orb_range * ATM_DELTA)
                sl_premium = round(estimated_premium * 0.7, 2)  # 30% loss
                target_premium = round(estimated_premium * 1.5, 2)  # 50% gain

                return OptionSignal(
                    index="NIFTY", direction="CALL", strike=strike,
                    entry_premium=round(estimated_premium, 2),
                    sl_premium=sl_premium, target_premium=target_premium,
                    lot_size=NIFTY_LOT_SIZE,
                    index_entry=ltp, index_sl=self.orb_low, index_target=ltp + orb_range * 1.5,
                    reason=f"NIFTY ORB CALL: broke above {self.orb_high:.0f}, retested, bounced. Strike {strike}CE"
                )

        elif self._breakout_detected == "PUT":
            is_bounce = prev_candle_close < self.orb_low and prev_candle_close < prev_candle_open
            if is_bounce:
                self._signal_fired = True
                strike = round(ltp / 50) * 50
                estimated_premium = max(50, orb_range * ATM_DELTA)
                sl_premium = round(estimated_premium * 0.7, 2)
                target_premium = round(estimated_premium * 1.5, 2)

                return OptionSignal(
                    index="NIFTY", direction="PUT", strike=strike,
                    entry_premium=round(estimated_premium, 2),
                    sl_premium=sl_premium, target_premium=target_premium,
                    lot_size=NIFTY_LOT_SIZE,
                    index_entry=ltp, index_sl=self.orb_high, index_target=ltp - orb_range * 1.5,
                    reason=f"NIFTY ORB PUT: broke below {self.orb_low:.0f}, retested, rejected. Strike {strike}PE"
                )

        return None

    def reset_daily(self):
        """Reset for new trading day."""
        self.orb_high = 0
        self.orb_low = 0
        self.orb_range_set = False
        self._breakout_detected = None
        self._retesting = False
        self._signal_fired = False
