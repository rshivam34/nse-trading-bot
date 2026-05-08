"""
Options Manager — NIFTY/BANKNIFTY Option Buying via ORB Retest.
================================================================

Handles the full options trade lifecycle:
1. Track NIFTY/BANKNIFTY ORB range during 9:15-9:30
2. Detect breakout + retest pattern
3. Build option symbol (e.g., "NIFTY27MAR2625500CE")
4. Place order via Angel One NFO segment
5. Monitor premium (SL at 30% loss, target at 50% gain)
6. Exit by 2 PM or force exit at 3:15

This is separate from equity OrderManager — options have
different exchange (NFO), product type (MIS), and position sizing.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, time
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class OptionPosition:
    """Active option position being monitored."""
    index: str                  # "NIFTY" or "BANKNIFTY"
    option_type: str            # "CE" or "PE"
    strike: float
    symbol: str                 # Full symbol e.g. "NIFTY27MAR2625500CE"
    token: str                  # Angel One instrument token
    lot_size: int
    quantity: int               # Actual quantity (lots × lot_size)
    entry_premium: float        # Premium at entry
    current_premium: float = 0
    sl_premium: float = 0       # Exit if premium drops to this (30% loss)
    target_premium: float = 0   # Exit if premium rises to this (50% gain)
    order_id: str = ""
    entry_time: str = ""
    pnl: float = 0


class OptionsManager:
    """Manages NIFTY/BANKNIFTY option trades."""

    def __init__(self, trading_config, broker=None):
        self.config = trading_config
        self.broker = broker

        # ORB ranges for indices
        self._nifty_orb = {"high": 0.0, "low": 0.0, "set": False}
        self._banknifty_orb = {"high": 0.0, "low": 0.0, "set": False}

        # Breakout state machines (same as equity ORB retest)
        self._nifty_state = None     # None → "BREAKOUT" → "RETESTING" → signal
        self._banknifty_state = None
        self._nifty_signal_fired = False
        self._banknifty_signal_fired = False

        # Active option positions
        self.open_positions: list[OptionPosition] = []
        self.closed_trades: list[dict] = []

        # Daily counters
        self.trades_today = 0
        # REWORK 2026-05-01: Read max trades from config (was hardcoded 2)
        # Allows up to 4 F&O trades/day in options-primary mode.
        self.max_options_per_day = getattr(trading_config, "options_max_trades_per_day", 2)

        # Diagnostic logging state — one-shot per index per day, plus 5-min heartbeat
        self._orb_logged = {"NIFTY": False, "BANKNIFTY": False}
        self._range_filter_logged = {"NIFTY": False, "BANKNIFTY": False}
        self._last_heartbeat: dict[str, Optional[datetime]] = {"NIFTY": None, "BANKNIFTY": None}

    def update_orb_range(self, index: str, ltp: float, high: float, low: float):
        """Called during 9:15-9:30 to track index ORB range."""
        orb = self._nifty_orb if index == "NIFTY" else self._banknifty_orb
        if not orb["set"] or high > orb["high"]:
            orb["high"] = high
        if not orb["set"] or low < orb["low"] or orb["low"] == 0:
            orb["low"] = low
        orb["set"] = True

    def check_for_signal(self, index: str, ltp: float, candles=None, vix: float = 15.0) -> Optional[dict]:
        """
        Check if index ORB breakout + retest → option signal.

        Returns dict with signal details or None.
        """
        if self.trades_today >= self.max_options_per_day:
            return None

        if vix > self.config.vix_caution_threshold:
            return None  # DANGER zone

        orb = self._nifty_orb if index == "NIFTY" else self._banknifty_orb
        if not orb["set"]:
            return None

        orb_high = orb["high"]
        orb_low = orb["low"]
        orb_range = orb_high - orb_low
        mid = (orb_high + orb_low) / 2

        if mid <= 0:
            return None

        range_pct = (orb_range / mid) * 100

        # One-shot log: ORB locked at first signal-check call after 9:30 — confirms range computation
        if not self._orb_logged.get(index, False):
            logger.info(
                f"OPTIONS {index} ORB locked: high={orb_high:.2f} low={orb_low:.2f} "
                f"range={orb_range:.2f} ({range_pct:.2f}%)"
            )
            self._orb_logged[index] = True

        # Range filter (index-specific)
        min_range = 0.2
        max_range = 1.5 if index == "NIFTY" else 3.0
        if range_pct < min_range or range_pct > max_range:
            if not self._range_filter_logged.get(index, False):
                logger.info(
                    f"OPTIONS {index}: ORB range {range_pct:.2f}% outside "
                    f"[{min_range}%, {max_range}%] — F&O signals disabled today for this index"
                )
                self._range_filter_logged[index] = True
            return None

        buffer = mid * 0.001  # 0.1% buffer

        # Get state for this index
        signal_fired = self._nifty_signal_fired if index == "NIFTY" else self._banknifty_signal_fired
        state = self._nifty_state if index == "NIFTY" else self._banknifty_state

        # 5-min heartbeat for observability on quiet days — fires regardless of state
        now_dt = datetime.now()
        last_hb = self._last_heartbeat.get(index)
        if last_hb is None or (now_dt - last_hb).total_seconds() >= 300:
            if signal_fired:
                state_str = "SIGNAL_FIRED"
            elif state is None:
                state_str = "WAITING_BREAKOUT"
            elif state.get("retesting"):
                state_str = f"RETESTING_{state['direction']}"
            else:
                state_str = f"BREAKOUT_{state['direction']}"
            logger.info(
                f"OPTIONS {index} heartbeat: LTP={ltp:.2f} "
                f"ORB=[{orb_low:.2f}-{orb_high:.2f}] state={state_str}"
            )
            self._last_heartbeat[index] = now_dt

        if signal_fired:
            return None

        # Breakout detection
        if state is None:
            if ltp > orb_high + buffer:
                new_state = {"direction": "CALL", "breakout_price": ltp}
                if index == "NIFTY":
                    self._nifty_state = new_state
                else:
                    self._banknifty_state = new_state
                logger.info(f"OPTIONS {index}: CALL breakout detected at {ltp:.0f}")
            elif ltp < orb_low - buffer:
                new_state = {"direction": "PUT", "breakout_price": ltp}
                if index == "NIFTY":
                    self._nifty_state = new_state
                else:
                    self._banknifty_state = new_state
                logger.info(f"OPTIONS {index}: PUT breakout detected at {ltp:.0f}")
            return None

        # Retest detection
        direction = state.get("direction")
        if "retesting" not in state:
            if direction == "CALL" and ltp <= orb_high * 1.001:
                state["retesting"] = True
                logger.info(f"OPTIONS {index}: CALL retesting at {ltp:.0f}")
            elif direction == "PUT" and ltp >= orb_low * 0.999:
                state["retesting"] = True
                logger.info(f"OPTIONS {index}: PUT retesting at {ltp:.0f}")
            elif direction == "CALL" and ltp < orb_low:
                # Failed breakout
                if index == "NIFTY":
                    self._nifty_state = None
                else:
                    self._banknifty_state = None
            elif direction == "PUT" and ltp > orb_high:
                if index == "NIFTY":
                    self._banknifty_state = None
                else:
                    self._banknifty_state = None
            return None

        # Bounce confirmation
        if state.get("retesting"):
            if direction == "CALL" and ltp > orb_high + buffer:
                # Bounce confirmed — CALL signal
                if index == "NIFTY":
                    self._nifty_signal_fired = True
                    self._nifty_state = None
                else:
                    self._banknifty_signal_fired = True
                    self._banknifty_state = None

                lot_size = self.config.nifty_lot_size if index == "NIFTY" else self.config.banknifty_lot_size
                strike_interval = 50 if index == "NIFTY" else 100
                strike = round(ltp / strike_interval) * strike_interval

                logger.info(f"OPTIONS SIGNAL: {index} {strike}CE — ORB retest bounce confirmed")
                return {
                    "index": index,
                    "option_type": "CE",
                    "strike": strike,
                    "lot_size": lot_size,
                    "index_price": ltp,
                    "orb_high": orb_high,
                    "orb_low": orb_low,
                }

            elif direction == "PUT" and ltp < orb_low - buffer:
                if index == "NIFTY":
                    self._nifty_signal_fired = True
                    self._nifty_state = None
                else:
                    self._banknifty_signal_fired = True
                    self._banknifty_state = None

                lot_size = self.config.nifty_lot_size if index == "NIFTY" else self.config.banknifty_lot_size
                strike_interval = 50 if index == "NIFTY" else 100
                strike = round(ltp / strike_interval) * strike_interval

                logger.info(f"OPTIONS SIGNAL: {index} {strike}PE — ORB retest rejection confirmed")
                return {
                    "index": index,
                    "option_type": "PE",
                    "strike": strike,
                    "lot_size": lot_size,
                    "index_price": ltp,
                    "orb_high": orb_high,
                    "orb_low": orb_low,
                }

        return None

    def execute_option_signal(self, signal: dict, vix: float = 15.0) -> Optional[OptionPosition]:
        """
        Execute an option signal: build symbol, look up token, place order.

        Returns OptionPosition if successful, None if failed.
        """
        index = signal["index"]
        opt_type = signal["option_type"]
        strike = signal["strike"]
        lot_size = signal["lot_size"]

        # Build option symbol for Angel One
        # Format: NIFTY27MAR2625500CE
        expiry_str = self._get_next_weekly_expiry()
        symbol = f"{index}{expiry_str}{int(strike)}{opt_type}"

        logger.info(f"Looking up option: {symbol}")

        if not self.broker:
            logger.warning("No broker connected — options signal logged but not executed")
            return None

        # Look up token from instrument master
        token = self.broker._lookup_option_token(symbol)
        if not token:
            logger.warning(f"Option token not found for {symbol}. Cannot place order.")
            return None

        # Get current premium (LTP)
        premium = self.broker.get_option_ltp(symbol, token)
        if premium <= 0:
            logger.warning(f"Option premium is 0 for {symbol}. Skipping.")
            return None

        # Check if premium is within budget
        max_premium = self.config.options_max_premium
        if premium > max_premium:
            logger.info(f"Option premium Rs.{premium:.2f} > max Rs.{max_premium:.2f}. Skipping.")
            return None

        # REWORK 2026-05-02: AUTO-SCALING multi-lot sizing (validated +79% backtest at Rs.50K)
        # Position size = 25% of capital_for_options per trade.
        # Number of lots = max(1, capital_per_position / lot_cost), capped at 10 lots.
        # This ensures Rs.50K → 2-3 lots, Rs.1L → 4-5 lots — proportional scaling.
        capital_for_options = getattr(self.config, "options_capital_allocation", min(5000, self.config.initial_capital * 0.3))
        capital_per_position = capital_for_options * 0.25  # 25% per trade
        lot_cost = premium * lot_size
        max_lots_affordable = int(capital_for_options / lot_cost)
        if max_lots_affordable <= 0:
            logger.warning(f"Cannot afford even 1 lot of {symbol} at Rs.{premium:.2f}")
            return None

        # Auto-scale: how many lots fit in 25% of capital? Floor 1, cap 10.
        scaled_lots = max(1, int(capital_per_position / lot_cost))
        scaled_lots = min(scaled_lots, max_lots_affordable, 10)
        quantity = lot_size * scaled_lots
        logger.info(
            f"Auto-scaled lots: {scaled_lots} ({lot_size}x{scaled_lots}={quantity} qty) "
            f"@ Rs.{premium:.2f} premium = Rs.{lot_cost*scaled_lots:.0f} deployed "
            f"(25% target: Rs.{capital_per_position:.0f}, max affordable: {max_lots_affordable} lots)"
        )

        # Place order
        order_id = self.broker.place_option_order(
            option_symbol=symbol,
            token=token,
            transaction="BUY",
            quantity=quantity,
            price=premium,
            order_type="LIMIT",
        )

        if not order_id:
            logger.error(f"Option order placement failed for {symbol}")
            return None

        # Create position
        sl_pct = self.config.options_sl_pct / 100  # 0.30
        target_pct = self.config.options_target_pct / 100  # 0.50

        pos = OptionPosition(
            index=index,
            option_type=opt_type,
            strike=strike,
            symbol=symbol,
            token=token,
            lot_size=lot_size,
            quantity=quantity,
            entry_premium=premium,
            current_premium=premium,
            sl_premium=round(premium * (1 - sl_pct), 2),
            target_premium=round(premium * (1 + target_pct), 2),
            order_id=order_id,
            entry_time=datetime.now().strftime("%H:%M"),
        )

        self.open_positions.append(pos)
        self.trades_today += 1

        logger.info(
            f"OPTION POSITION OPENED: {symbol} | "
            f"Premium: Rs.{premium:.2f} × {quantity} = Rs.{premium * quantity:.2f} | "
            f"SL: Rs.{pos.sl_premium:.2f} | Target: Rs.{pos.target_premium:.2f}"
        )

        return pos

    def monitor_positions(self) -> list[OptionPosition]:
        """
        Monitor open option positions. Check SL, target, time exit.
        Returns list of closed positions.
        """
        if not self.broker or not self.open_positions:
            return []

        now = datetime.now().time()
        closed = []

        for pos in self.open_positions[:]:
            # Get current premium
            current_premium = self.broker.get_option_ltp(pos.symbol, pos.token)
            if current_premium <= 0:
                continue

            pos.current_premium = current_premium
            pos.pnl = (current_premium - pos.entry_premium) * pos.quantity

            # SL: premium dropped 30%
            if current_premium <= pos.sl_premium:
                self._close_option(pos, current_premium, "SL")
                closed.append(pos)
                continue

            # Target: premium gained 50%
            if current_premium >= pos.target_premium:
                self._close_option(pos, current_premium, "TARGET")
                closed.append(pos)
                continue

            # Time exit: 2 PM
            if now >= self.config.options_exit_time:
                self._close_option(pos, current_premium, "TIME_EXIT")
                closed.append(pos)
                continue

        return closed

    def exit_all_positions(self):
        """Force-exit all open option positions."""
        for pos in self.open_positions[:]:
            if self.broker:
                current = self.broker.get_option_ltp(pos.symbol, pos.token)
                if current > 0:
                    self._close_option(pos, current, "FORCE_EXIT")
                else:
                    self._close_option(pos, pos.entry_premium * 0.5, "FORCE_EXIT_NO_LTP")

    def _close_option(self, pos: OptionPosition, exit_premium: float, reason: str):
        """Close an option position — sell the option."""
        if self.broker:
            sell_id = self.broker.place_option_order(
                option_symbol=pos.symbol,
                token=pos.token,
                transaction="SELL",
                quantity=pos.quantity,
                price=exit_premium,
                order_type="MARKET",  # Market order for quick exit
            )
            if not sell_id:
                logger.error(f"Failed to sell option {pos.symbol}. Manual exit needed!")

        gross_pnl = (exit_premium - pos.entry_premium) * pos.quantity
        charges = pos.quantity * pos.entry_premium * 0.001  # ~0.1% option charges

        self.closed_trades.append({
            "index": pos.index,
            "type": pos.option_type,
            "strike": pos.strike,
            "symbol": pos.symbol,
            "entry_premium": pos.entry_premium,
            "exit_premium": exit_premium,
            "quantity": pos.quantity,
            "gross_pnl": round(gross_pnl, 2),
            "charges": round(charges, 2),
            "net_pnl": round(gross_pnl - charges, 2),
            "exit_reason": reason,
            "time": datetime.now().strftime("%H:%M"),
        })

        logger.info(
            f"OPTION CLOSED: {pos.symbol} | {reason} | "
            f"Entry: Rs.{pos.entry_premium:.2f} → Exit: Rs.{exit_premium:.2f} | "
            f"Gross: Rs.{gross_pnl:+.2f} | Net: Rs.{gross_pnl - charges:+.2f}"
        )

        self.open_positions.remove(pos)

    def _get_next_weekly_expiry(self) -> str:
        """
        Get next Thursday expiry in Angel One format: DDMMMYYYY.
        Example: "27MAR2026"
        """
        today = datetime.now()
        days_until_thursday = (3 - today.weekday()) % 7
        if days_until_thursday == 0 and today.hour >= 15:
            days_until_thursday = 7  # If it's Thursday after market close, next week
        next_thursday = today + timedelta(days=days_until_thursday)
        return next_thursday.strftime("%d%b%Y").upper()  # "27MAR2026"

    def reset_daily(self):
        """Reset for new trading day."""
        self._nifty_orb = {"high": 0.0, "low": 0.0, "set": False}
        self._banknifty_orb = {"high": 0.0, "low": 0.0, "set": False}
        self._nifty_state = None
        self._banknifty_state = None
        self._nifty_signal_fired = False
        self._banknifty_signal_fired = False
        self.open_positions.clear()
        self.trades_today = 0
        self._orb_logged = {"NIFTY": False, "BANKNIFTY": False}
        self._range_filter_logged = {"NIFTY": False, "BANKNIFTY": False}
        self._last_heartbeat = {"NIFTY": None, "BANKNIFTY": None}
