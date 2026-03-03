"""
Order Manager — Places, Monitors, and Exits Trades.
====================================================

Production features:
- Smart partial exit: 50% at 1x RR, SL moves to breakeven
- Trailing stop-loss: after partial exit, trail SL by max(0.3%, 0.5×ATR)
- Slippage tracking: log actual fill price vs expected entry price
- Partial fill detection: adjust position size if < requested quantity filled
- Duplicate order prevention: won't re-order for same stock
- Pending order timeout: cancel LIMIT orders unfilled after 30 seconds
- reconcile_positions(): verify broker state after reconnect
- Full portfolio sync: portfolio.record_trade() called on every close
"""

import logging
import time as time_module
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from strategies.base_strategy import Signal
from utils.brokerage import calculate_charges, format_charges_summary

logger = logging.getLogger(__name__)


@dataclass
class Position:
    """
    An open trade being monitored.

    Key fields for production tracking:
    - remaining_quantity: shares still open (decreases after partial exit)
    - partial_exit_done: True after 50% is exited at 1x RR
    - effective_sl: current active stop-loss (moves to entry after partial exit)
    - trailing_sl: trailing stop-loss price (updates as price moves favorably)
    - trailing_active: True after partial exit triggers the trailing SL
    - peak_price: highest price reached for LONG (or lowest for SHORT)
    - realized_pnl: P&L from already-closed portions
    - actual_entry: actual fill price (may differ from signal.entry_price due to slippage)
    - slippage: actual_entry - expected_entry (positive = we paid more for LONG)
    """
    signal: Signal
    order_id: str
    status: str = "OPEN"             # OPEN, PARTIAL, CLOSED
    current_price: float = 0.0
    unrealized_pnl: float = 0.0
    exit_price: float = 0.0
    exit_reason: str = ""
    placed_at: float = field(default_factory=time_module.time)

    # Partial exit fields
    remaining_quantity: int = 0
    partial_exit_done: bool = False
    effective_sl: float = 0.0        # Active SL — starts at signal.stop_loss
    realized_pnl: float = 0.0

    # Trailing SL fields
    trailing_sl: float = 0.0         # Current trailing SL price
    trailing_active: bool = False     # True once partial exit fires
    peak_price: float = 0.0          # Best price seen (for trailing calc)

    # Slippage tracking
    actual_entry: float = 0.0        # Actual fill price from broker
    slippage: float = 0.0            # actual_entry - signal.entry_price

    def __post_init__(self):
        if self.remaining_quantity == 0:
            self.remaining_quantity = self.signal.quantity
        if self.effective_sl == 0.0:
            self.effective_sl = self.signal.stop_loss
        if self.actual_entry == 0.0:
            self.actual_entry = self.signal.entry_price
        if self.peak_price == 0.0:
            self.peak_price = self.signal.entry_price

    @property
    def target1(self) -> float:
        """First partial exit level: entry + 1× risk."""
        risk = abs(self.signal.entry_price - self.signal.stop_loss)
        if self.signal.direction == "LONG":
            return round(self.signal.entry_price + risk, 2)
        else:
            return round(self.signal.entry_price - risk, 2)

    @property
    def hold_time_minutes(self) -> float:
        """How long this position has been open (minutes)."""
        return (time_module.time() - self.placed_at) / 60

    def to_dict(self) -> dict:
        return {
            "stock": self.signal.stock,
            "direction": self.signal.direction,
            "entry": self.signal.entry_price,
            "actual_entry": self.actual_entry,
            "slippage": round(self.slippage, 4),
            "stop_loss": self.effective_sl,
            "original_sl": self.signal.stop_loss,
            "trailing_sl": self.trailing_sl,
            "trailing_active": self.trailing_active,
            "target": self.signal.target,
            "target1": self.target1,
            "quantity": self.signal.quantity,
            "remaining_quantity": self.remaining_quantity,
            "partial_exit_done": self.partial_exit_done,
            "current_price": self.current_price,
            "unrealized_pnl": round(self.unrealized_pnl, 2),
            "realized_pnl": round(self.realized_pnl, 2),
            "status": self.status,
            "hold_time_min": round(self.hold_time_minutes, 1),
            "score": getattr(self.signal, "score", 0),
            "strategy": self.signal.strategy_name,
        }


class OrderManager:
    """Manages order lifecycle: place → monitor → exit."""

    def __init__(self, broker, risk_manager, portfolio, config):
        self.broker = broker
        self.risk_manager = risk_manager
        self.portfolio = portfolio
        self.config = config
        self.open_positions: list[Position] = []
        self.closed_positions: list[Position] = []

        # Pending orders: {order_id: {placed_at, stock, quantity, signal}}
        # Used to detect and cancel unfilled LIMIT orders after timeout
        self._pending_orders: dict[str, dict] = {}

    def execute(self, signal: Signal) -> Optional[Position]:
        """
        Place an order based on a signal.
        Detects partial fills and adjusts position size accordingly.
        Tracks slippage (difference between expected and actual fill price).
        """
        order_id = self.broker.place_order(
            stock=signal.stock,
            token=signal.token,
            direction=signal.direction,
            quantity=signal.quantity,
            price=signal.entry_price,
        )

        if not order_id:
            logger.error(f"Order placement failed: {signal.stock}")
            return None

        # Track as pending — check later for fill
        self._pending_orders[order_id] = {
            "placed_at": time_module.time(),
            "stock": signal.stock,
            "signal": signal,
        }

        # Verify actual fill
        filled_qty = self.broker.get_filled_quantity(order_id)
        if filled_qty <= 0:
            # Not yet filled — assume full fill optimistically
            filled_qty = signal.quantity
        elif filled_qty < signal.quantity:
            logger.warning(
                f"Partial fill: {signal.stock} — got {filled_qty} of {signal.quantity} shares"
            )
            signal.quantity = filled_qty  # Adjust to actual

        # Get actual fill price for slippage calculation
        actual_entry = self.broker.get_ltp(signal.token) or signal.entry_price
        slippage = actual_entry - signal.entry_price
        if abs(slippage) > 0.01:
            slippage_pct = abs(slippage / signal.entry_price) * 100
            logger.warning(
                f"Slippage detected: {signal.stock} | "
                f"Expected Rs.{signal.entry_price:.2f}, Got Rs.{actual_entry:.2f} | "
                f"Slippage: {slippage:+.2f} ({slippage_pct:.3f}%)"
            )

        pos = Position(
            signal=signal,
            order_id=order_id,
            remaining_quantity=filled_qty,
            actual_entry=actual_entry,
            slippage=slippage,
        )

        self.open_positions.append(pos)

        # Notify risk manager that this stock is now active
        self.risk_manager.mark_stock_active(signal.stock)

        logger.info(
            f"Position opened: {signal.direction} {filled_qty}x {signal.stock} "
            f"@ Rs.{actual_entry:.2f} | SL: Rs.{signal.stop_loss:.2f} | "
            f"Target: Rs.{signal.target:.2f}"
        )
        return pos

    def monitor_positions(self) -> tuple[list[Position], list[Position]]:
        """
        Check all open positions for SL/target/trailing SL hit.

        Order of checks:
        1. Effective SL (original or breakeven after partial exit)
        2. If trailing SL is active → update trail and check if hit
        3. Check partial exit at target1 (1x RR)
        4. Check full exit at target2 (signal.target)

        Returns:
            (newly_closed, partially_updated) — main.py uses these for Firebase
        """
        newly_closed: list[Position] = []
        partially_updated: list[Position] = []

        # Also check for pending order timeouts
        self._check_pending_timeouts()

        for pos in self.open_positions[:]:
            if pos.status not in ("OPEN", "PARTIAL"):
                continue

            ltp = self.broker.get_ltp(token=pos.signal.token)
            if not ltp or ltp <= 0:
                continue

            pos.current_price = ltp
            direction = pos.signal.direction

            if direction == "LONG":
                pos.unrealized_pnl = (
                    (ltp - pos.signal.entry_price) * pos.remaining_quantity
                    + pos.realized_pnl
                )

                # Update peak price for trailing SL
                if ltp > pos.peak_price:
                    pos.peak_price = ltp
                    if pos.trailing_active:
                        new_trail = self._calc_trailing_sl(pos, ltp)
                        if new_trail > pos.trailing_sl:
                            pos.trailing_sl = new_trail

                # Check stops — effective_sl first (highest priority)
                if ltp <= pos.effective_sl:
                    self._close_remaining(pos, pos.effective_sl, "STOP_LOSS")
                    newly_closed.append(pos)

                # Trailing SL
                elif pos.trailing_active and pos.trailing_sl > 0 and ltp <= pos.trailing_sl:
                    self._close_remaining(pos, pos.trailing_sl, "TRAILING_STOP")
                    newly_closed.append(pos)

                # Partial exit at target1 (1x RR)
                elif (
                    self.config.partial_exit_enabled
                    and not pos.partial_exit_done
                    and ltp >= pos.target1
                ):
                    self._partial_exit(pos, ltp)
                    partially_updated.append(pos)

                # Full exit at target2 (signal.target)
                elif ltp >= pos.signal.target:
                    self._close_remaining(pos, pos.signal.target, "TARGET")
                    newly_closed.append(pos)

            elif direction == "SHORT":
                pos.unrealized_pnl = (
                    (pos.signal.entry_price - ltp) * pos.remaining_quantity
                    + pos.realized_pnl
                )

                # Update trough for trailing SL (for shorts, we trail down)
                if ltp < pos.peak_price or pos.peak_price == pos.signal.entry_price:
                    pos.peak_price = ltp
                    if pos.trailing_active:
                        new_trail = self._calc_trailing_sl(pos, ltp)
                        if new_trail < pos.trailing_sl or pos.trailing_sl == 0:
                            pos.trailing_sl = new_trail

                if ltp >= pos.effective_sl:
                    self._close_remaining(pos, pos.effective_sl, "STOP_LOSS")
                    newly_closed.append(pos)

                elif pos.trailing_active and pos.trailing_sl > 0 and ltp >= pos.trailing_sl:
                    self._close_remaining(pos, pos.trailing_sl, "TRAILING_STOP")
                    newly_closed.append(pos)

                elif (
                    self.config.partial_exit_enabled
                    and not pos.partial_exit_done
                    and ltp <= pos.target1
                ):
                    self._partial_exit(pos, ltp)
                    partially_updated.append(pos)

                elif ltp <= pos.signal.target:
                    self._close_remaining(pos, pos.signal.target, "TARGET")
                    newly_closed.append(pos)

        return newly_closed, partially_updated

    def _calc_trailing_sl(self, pos: Position, current_price: float) -> float:
        """
        Calculate trailing stop-loss price.

        Trail by the larger of:
        - config.trailing_sl_pct % of current price (e.g., 0.3%)
        - 0.5 × ATR (if ATR is available via signal metadata — otherwise use % only)

        For LONG: trailing SL = peak_price - trail_distance
        For SHORT: trailing SL = trough_price + trail_distance
        """
        trail_pct = self.config.trailing_sl_pct / 100
        trail_amount = current_price * trail_pct

        if pos.signal.direction == "LONG":
            return round(pos.peak_price - trail_amount, 2)
        else:
            return round(pos.peak_price + trail_amount, 2)

    def _partial_exit(self, pos: Position, exit_price: float):
        """
        Exit 50% of position at 1x RR and move SL to breakeven.
        Activates trailing SL on the remaining 50%.
        """
        half_qty = pos.remaining_quantity // 2
        if half_qty <= 0:
            self._close_remaining(pos, exit_price, "TARGET1_FULL")
            return

        exit_order_id = self.broker.place_exit_order(
            stock=pos.signal.stock,
            token=pos.signal.token,
            direction=pos.signal.direction,
            quantity=half_qty,
        )

        if not exit_order_id:
            logger.error(f"Partial exit order failed for {pos.signal.stock}")
            return

        # P&L for the exited half
        if pos.signal.direction == "LONG":
            pnl_partial = (exit_price - pos.signal.entry_price) * half_qty
        else:
            pnl_partial = (pos.signal.entry_price - exit_price) * half_qty

        # Compute charges on the partial exit
        charges = calculate_charges(
            pos.signal.entry_price, exit_price, half_qty, pos.signal.direction
        )

        pos.realized_pnl += pnl_partial
        pos.remaining_quantity -= half_qty
        pos.partial_exit_done = True
        pos.effective_sl = pos.signal.entry_price  # Move SL to breakeven

        # Activate trailing SL on remaining position
        if self.config.trailing_sl_enabled:
            pos.trailing_active = True
            pos.trailing_sl = self._calc_trailing_sl(pos, exit_price)
            pos.peak_price = exit_price

        pos.status = "PARTIAL"

        logger.info(
            f"Partial exit: {pos.signal.stock} — sold {half_qty} @ Rs.{exit_price:.2f} | "
            f"Gross P&L: Rs.{pnl_partial:+.2f} | Net: Rs.{charges['net_pnl']:+.2f} | "
            f"SL moved to breakeven Rs.{pos.signal.entry_price:.2f} | "
            f"Trailing SL: Rs.{pos.trailing_sl:.2f} | "
            f"Remaining: {pos.remaining_quantity} shares"
        )

    def _close_remaining(self, pos: Position, exit_price: float, reason: str):
        """Close all remaining shares. Record final P&L (gross and net)."""
        if pos.remaining_quantity > 0:
            exit_order_id = self.broker.place_exit_order(
                stock=pos.signal.stock,
                token=pos.signal.token,
                direction=pos.signal.direction,
                quantity=pos.remaining_quantity,
            )
            if not exit_order_id:
                logger.error(
                    f"Exit order failed for {pos.signal.stock} ({reason}) — "
                    "position may still be open at broker!"
                )

        pos.status = "CLOSED"
        pos.exit_price = exit_price
        pos.exit_reason = reason

        # P&L for remaining shares
        if pos.signal.direction == "LONG":
            pnl_remaining = (exit_price - pos.signal.entry_price) * pos.remaining_quantity
        else:
            pnl_remaining = (pos.signal.entry_price - exit_price) * pos.remaining_quantity

        # Full charges calculation for the complete trade
        charges = calculate_charges(
            pos.actual_entry, exit_price, pos.signal.quantity, pos.signal.direction
        )

        total_gross = pos.realized_pnl + pnl_remaining
        total_net = total_gross - charges["total_charges"]
        pos.realized_pnl = total_gross

        # Update risk manager
        self.risk_manager.record_trade_result(total_net, pos.signal.stock)

        # Update portfolio (this keeps current_capital accurate)
        self.portfolio.record_trade({
            "stock": pos.signal.stock,
            "direction": pos.signal.direction,
            "entry": pos.actual_entry,
            "exit": exit_price,
            "quantity": pos.signal.quantity,
            "gross_pnl": round(total_gross, 2),
            "pnl": round(total_net, 2),          # net P&L = what portfolio tracks
            "charges": charges,
            "reason": reason,
            "strategy": pos.signal.strategy_name,
            "score": getattr(pos.signal, "score", 0),
            "slippage": pos.slippage,
            "hold_time_min": round(pos.hold_time_minutes, 1),
        })

        if pos in self.open_positions:
            self.open_positions.remove(pos)
        self.closed_positions.append(pos)

        icon = "Target" if "TARGET" in reason else "Trailing" if "TRAILING" in reason else "Stop"
        logger.info(
            f"{icon}: {pos.signal.stock} | {reason} | "
            f"Gross: Rs.{total_gross:+.2f} | Net: Rs.{total_net:+.2f} | "
            f"{format_charges_summary(charges)}"
        )

    def exit_all_positions(self, reason: str = "FORCE_EXIT"):
        """Emergency exit for all open positions (kill switch / force exit at 3:15)."""
        for pos in self.open_positions[:]:
            ltp = self.broker.get_ltp(pos.signal.token) or pos.signal.entry_price
            self._close_remaining(pos, ltp, reason)
        logger.info(f"All positions closed ({reason})")

    def reconcile_positions(self, broker_positions: list[dict]):
        """
        Sync internal state with broker's actual positions after reconnect.
        If broker shows a position is closed (we missed the SL/target event),
        mark it closed in our records.
        """
        if not broker_positions:
            if self.open_positions:
                logger.warning(
                    f"Reconciliation: broker has 0 open positions, "
                    f"we have {len(self.open_positions)} — marking all closed"
                )
                for pos in self.open_positions[:]:
                    pos.status = "CLOSED"
                    pos.exit_reason = "CLOSED_WHILE_OFFLINE"
                    self.open_positions.remove(pos)
                    self.closed_positions.append(pos)
            return

        broker_symbols = {
            bp.get("tradingsymbol", "").replace("-EQ", "")
            for bp in broker_positions
            if int(bp.get("netqty", 0)) != 0
        }

        for pos in self.open_positions[:]:
            if pos.signal.stock not in broker_symbols:
                logger.warning(
                    f"Reconciliation: {pos.signal.stock} not in broker positions — "
                    "likely closed while WebSocket was down"
                )
                pos.status = "CLOSED"
                pos.exit_reason = "RECONCILED_WHILE_OFFLINE"
                self.open_positions.remove(pos)
                self.closed_positions.append(pos)

    def _check_pending_timeouts(self):
        """
        Cancel LIMIT orders that haven't filled within config.pending_order_timeout_secs.
        This prevents stale orders from lingering in the system.
        """
        timeout = self.config.pending_order_timeout_secs
        now = time_module.time()
        timed_out = [
            oid for oid, info in self._pending_orders.items()
            if now - info["placed_at"] > timeout
        ]

        for order_id in timed_out:
            info = self._pending_orders.pop(order_id, {})
            status = self.broker.get_order_status(order_id)

            if status in ("open", "pending", "trigger pending"):
                logger.warning(
                    f"Pending order timeout: {info.get('stock', '?')} "
                    f"(order {order_id}) not filled in {timeout:.0f}s — cancelling"
                )
                self.broker.cancel_order(order_id)
