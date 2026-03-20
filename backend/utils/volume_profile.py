"""
Volume Profile Manager — Time-of-Day (TOD) volume tracking.
=============================================================

Stores a rolling 10-day volume profile per stock per 5-minute time slot.
Used for RVOL (Relative Volume) calculation: compare current candle volume
to the historical average at the SAME time of day (not just recent candles).

Why this is better than comparing to the last 20 intraday candles:
- Volume has a strong intraday pattern: high at open, low at lunch, moderate at close.
- Comparing a 9:30 AM candle to 11:30 AM candles gives false high RVOL.
- TOD comparison is apples-to-apples: 9:30 today vs 9:30 on the last 10 days.

Also stores:
- 20-day daily volumes per stock for ADV (Average Daily Volume) filter
- NIFTY per-slot volume profile for macro-driven signal flagging

Persistence: JSON file at logs/volume_profiles.json, loaded at startup, saved at end of day.
"""

import json
import logging
from datetime import datetime, time
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# All 5-min time slots from 09:15 to 15:25 (75 slots total)
# Each slot represents the START of a 5-min candle: "09:15" = 9:15-9:20 candle
MARKET_OPEN_H, MARKET_OPEN_M = 9, 15


def generate_time_slots() -> list[str]:
    """Generate all 5-min time slot keys from 09:15 to 15:25."""
    slots = []
    h, m = MARKET_OPEN_H, MARKET_OPEN_M
    while (h, m) < (15, 30):
        slots.append(f"{h:02d}:{m:02d}")
        m += 5
        if m >= 60:
            h += 1
            m -= 60
    return slots


TIME_SLOTS = generate_time_slots()  # 75 entries: "09:15", "09:20", ..., "15:25"

# Max historical days to keep
MAX_TOD_DAYS = 10
MAX_ADV_DAYS = 20


def current_time_slot() -> str:
    """Get the current wall clock's 5-minute slot key."""
    now = datetime.now()
    slot_minute = (now.minute // 5) * 5
    return f"{now.hour:02d}:{slot_minute:02d}"


def is_expiry_day() -> bool:
    """
    Check if today is a weekly F&O expiry day (Thursday).

    On expiry days, rollover activity inflates volumes artificially,
    so the RVOL gate is raised from 2x to 3x to filter out noise.
    """
    return datetime.now().weekday() == 3  # 0=Mon, 3=Thu


class VolumeProfileManager:
    """
    Manages rolling 10-day volume profiles per stock and NIFTY.

    Structure on disk (logs/volume_profiles.json):
    {
        "_last_updated": "2026-03-13",
        "profiles": {
            "RELIANCE": {
                "09:15": [vol_day1, vol_day2, ...],   # up to 10 values
                "09:20": [vol_day1, vol_day2, ...],
                ...
            }
        },
        "nifty_profile": {
            "09:15": [vol_day1, ...],
            ...
        },
        "adv": {
            "RELIANCE": [daily_vol_day1, daily_vol_day2, ...],  # up to 20 values
            ...
        }
    }
    """

    def __init__(self, path: str = "logs/volume_profiles.json"):
        self.path = Path(path)
        # stock symbol -> {slot_key -> [volume_values]}
        self.profiles: dict[str, dict[str, list[int]]] = {}
        # NIFTY slot_key -> [volume_values]
        self.nifty_profile: dict[str, list[int]] = {}
        # stock symbol -> [daily_volume_values] (up to 20)
        self.adv: dict[str, list[int]] = {}
        self._loaded = False

    def load(self):
        """Load profiles from disk. Safe to call multiple times."""
        if self._loaded:
            return

        try:
            if self.path.exists():
                data = json.loads(self.path.read_text())
                self.profiles = data.get("profiles", {})
                self.nifty_profile = data.get("nifty_profile", {})
                self.adv = data.get("adv", {})
                last_updated = data.get("_last_updated", "unknown")

                stock_count = len(self.profiles)
                adv_count = len(self.adv)
                logger.info(
                    f"Volume profiles loaded: {stock_count} stocks, "
                    f"{adv_count} ADV entries (last updated: {last_updated})"
                )
            else:
                logger.info(
                    "No volume profile file found — starting fresh. "
                    "TOD RVOL will use session fallback until 5 days of data accumulate."
                )
        except Exception as e:
            logger.warning(f"Volume profile load failed: {e}. Starting fresh.")

        self._loaded = True

    def save(self):
        """Save profiles to disk."""
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            data = {
                "_last_updated": str(datetime.now().date()),
                "profiles": self.profiles,
                "nifty_profile": self.nifty_profile,
                "adv": self.adv,
            }
            self.path.write_text(json.dumps(data, indent=2))
            logger.info(
                f"Volume profiles saved: {len(self.profiles)} stocks, "
                f"{len(self.adv)} ADV entries"
            )
        except Exception as e:
            logger.warning(f"Volume profile save failed: {e}")

    # ──────────────────────────────────────────────────────────
    # TOD Average Lookups
    # ──────────────────────────────────────────────────────────

    def get_tod_average(self, symbol: str, time_slot: str) -> Optional[float]:
        """
        Get 10-day average volume for a stock at a specific time-of-day slot.

        Returns None if no data exists for this stock/slot combo.
        """
        stock_data = self.profiles.get(symbol, {})
        slot_data = stock_data.get(time_slot, [])
        if not slot_data:
            return None
        return sum(slot_data) / len(slot_data)

    def get_tod_data_days(self, symbol: str, time_slot: str) -> int:
        """How many days of historical TOD data exist for this stock at this slot."""
        stock_data = self.profiles.get(symbol, {})
        return len(stock_data.get(time_slot, []))

    def get_nifty_tod_average(self, time_slot: str) -> Optional[float]:
        """Get 10-day average volume for NIFTY at a specific time-of-day slot."""
        slot_data = self.nifty_profile.get(time_slot, [])
        if not slot_data:
            return None
        return sum(slot_data) / len(slot_data)

    # ──────────────────────────────────────────────────────────
    # ADV (Average Daily Volume)
    # ──────────────────────────────────────────────────────────

    def get_adv(self, symbol: str) -> float:
        """
        Get 20-day average daily volume for a stock.
        Returns 0.0 if no data exists.
        """
        daily_vols = self.adv.get(symbol, [])
        if not daily_vols:
            return 0.0
        return sum(daily_vols) / len(daily_vols)

    def set_adv_from_daily_volumes(self, symbol: str, daily_volumes: list[int]):
        """
        Set ADV data from broker's daily candle volumes (called at startup).

        Args:
            symbol: Stock symbol (e.g., "RELIANCE")
            daily_volumes: List of daily volumes from getCandleData ONE_DAY
                           (most recent last, up to 20 entries)
        """
        if not daily_volumes:
            return
        # Keep only last 20 days
        self.adv[symbol] = daily_volumes[-MAX_ADV_DAYS:]

    # ──────────────────────────────────────────────────────────
    # End-of-Day Update
    # ──────────────────────────────────────────────────────────

    def update_end_of_day(
        self,
        candle_store: dict[str, list[dict]],
        nifty_candle_store: list[dict],
        token_to_symbol: dict[str, str],
        candle_start_slot_indices: dict[str, int],
        nifty_start_slot_index: int = 0,
    ):
        """
        At end of trading day, extract today's candle volumes and add to profiles.

        Each candle maps to a time slot based on its position in the store
        plus the start_slot_index (0 = 09:15 for pre-seeded, higher for late starts).

        Args:
            candle_store: scanner's {token -> [candle_dicts]} for completed candles
            nifty_candle_store: scanner's NIFTY completed candles list
            token_to_symbol: token -> symbol mapping
            candle_start_slot_indices: {token -> starting slot index}
            nifty_start_slot_index: starting slot index for NIFTY candles
        """
        updated_stocks = 0

        # Update stock profiles
        for token, candles in candle_store.items():
            symbol = token_to_symbol.get(token)
            if not symbol or not candles:
                continue

            start_idx = candle_start_slot_indices.get(token, 0)

            if symbol not in self.profiles:
                self.profiles[symbol] = {}

            for i, candle in enumerate(candles):
                slot_idx = start_idx + i
                if slot_idx >= len(TIME_SLOTS):
                    break  # Past market close

                slot_key = TIME_SLOTS[slot_idx]
                volume = candle.get("Volume", 0)

                if volume <= 0:
                    continue

                if slot_key not in self.profiles[symbol]:
                    self.profiles[symbol][slot_key] = []

                self.profiles[symbol][slot_key].append(volume)

                # Trim to rolling 10-day window
                if len(self.profiles[symbol][slot_key]) > MAX_TOD_DAYS:
                    self.profiles[symbol][slot_key] = (
                        self.profiles[symbol][slot_key][-MAX_TOD_DAYS:]
                    )

            updated_stocks += 1

        # Update NIFTY profile
        nifty_updated = 0
        for i, candle in enumerate(nifty_candle_store):
            slot_idx = nifty_start_slot_index + i
            if slot_idx >= len(TIME_SLOTS):
                break

            slot_key = TIME_SLOTS[slot_idx]
            volume = candle.get("Volume", 0)

            if volume <= 0:
                continue

            if slot_key not in self.nifty_profile:
                self.nifty_profile[slot_key] = []

            self.nifty_profile[slot_key].append(volume)

            if len(self.nifty_profile[slot_key]) > MAX_TOD_DAYS:
                self.nifty_profile[slot_key] = (
                    self.nifty_profile[slot_key][-MAX_TOD_DAYS:]
                )
            nifty_updated += 1

        logger.info(
            f"Volume profiles updated: {updated_stocks} stocks, "
            f"{nifty_updated} NIFTY slots"
        )

    # ──────────────────────────────────────────────────────────
    # Utility
    # ──────────────────────────────────────────────────────────

    def slot_index_from_time(self, dt: datetime) -> int:
        """
        Convert a datetime to its time slot index (0 = 09:15, 1 = 09:20, ...).
        Used to determine starting slot for candles built from WebSocket ticks.
        """
        minutes_since_open = (dt.hour - MARKET_OPEN_H) * 60 + (dt.minute - MARKET_OPEN_M)
        return max(0, minutes_since_open // 5)
