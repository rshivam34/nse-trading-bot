"""
Order Manager — Places, monitors, and exits trades.
====================================================
"""

import logging
from dataclasses import dataclass, field
from typing import Optional

from strategies.base_strategy import Signal

logger = logging.getLogger(__name__)


@dataclass
class Position:
    """An open trade being monitored."""
    signal: Signal
    order_id: str
    status: str = "OPEN"         # OPEN, CLOSED
    current_price: float = 0.0
    unrealized_pnl: float = 0.0
    exit_price: float = 0.0
    exit_reason: str = ""

    def to_dict(self) -> dict:
        return {
            "stock": self.signal.stock,
            "direction": self.signal.direction,
            "entry": self.signal.entry_price,
            "stop_loss": self.signal.stop_loss,
            "target": self.signal.target,
            "quantity": self.signal.quantity,
            "current_price": self.current_price,
            "unrealized_pnl": self.unrealized_pnl,
            "status": self.status,
        }


class OrderManager:
    """Manages order lifecycle: place → monitor → exit."""

    def __init__(self, broker, risk_manager, config):
        self.broker = broker
        self.risk_manager = risk_manager
        self.config = config
        self.open_positions: list[Position] = []
        self.closed_positions: list[Position] = []

    def execute(self, signal: Signal) -> Optional[Position]:
        """Place an order based on a signal."""
        order_id = self.broker.place_order(
            stock=signal.stock,
            token=signal.token,
            direction=signal.direction,
            quantity=signal.quantity,
            price=signal.entry_price,
        )

        if order_id:
            pos = Position(signal=signal, order_id=order_id)
            self.open_positions.append(pos)
            logger.info(f"✅ Position opened: {signal}")
            return pos

        logger.error(f"❌ Order failed: {signal}")
        return None

    def monitor_positions(self):
        """Check all open positions for SL/target hit."""
        for pos in self.open_positions[:]:  # Copy list to allow removal
            if pos.status != "OPEN":
                continue

            ltp = self.broker.get_ltp(pos.signal.token)
            pos.current_price = ltp

            if pos.signal.direction == "LONG":
                pos.unrealized_pnl = (ltp - pos.signal.entry_price) * pos.signal.quantity

                if ltp <= pos.signal.stop_loss:
                    self._close_position(pos, pos.signal.stop_loss, "STOP_LOSS")
                elif ltp >= pos.signal.target:
                    self._close_position(pos, pos.signal.target, "TARGET")

            elif pos.signal.direction == "SHORT":
                pos.unrealized_pnl = (pos.signal.entry_price - ltp) * pos.signal.quantity

                if ltp >= pos.signal.stop_loss:
                    self._close_position(pos, pos.signal.stop_loss, "STOP_LOSS")
                elif ltp <= pos.signal.target:
                    self._close_position(pos, pos.signal.target, "TARGET")

    def _close_position(self, pos: Position, exit_price: float, reason: str):
        """Close a position and record the result."""
        pos.status = "CLOSED"
        pos.exit_price = exit_price
        pos.exit_reason = reason

        if pos.signal.direction == "LONG":
            pnl = (exit_price - pos.signal.entry_price) * pos.signal.quantity
        else:
            pnl = (pos.signal.entry_price - exit_price) * pos.signal.quantity

        self.risk_manager.record_trade_result(pnl)
        self.open_positions.remove(pos)
        self.closed_positions.append(pos)

        icon = "🎯" if reason == "TARGET" else "🛑"
        logger.info(f"{icon} Position closed: {pos.signal.stock} | {reason} | P&L: ₹{pnl:+,.2f}")

    def exit_all_positions(self):
        """Emergency exit or end-of-day close."""
        for pos in self.open_positions[:]:
            ltp = self.broker.get_ltp(pos.signal.token) or pos.signal.entry_price
            self._close_position(pos, ltp, "FORCE_EXIT")
        logger.info("🔴 All positions closed")
