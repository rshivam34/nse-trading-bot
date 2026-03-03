"""
Portfolio — Tracks capital, positions, and generates reports.
=============================================================
"""

import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


class Portfolio:
    """Tracks capital and trading performance."""

    def __init__(self, initial_capital: float):
        self.initial_capital = initial_capital
        self.current_capital = initial_capital
        self.day_start_capital = initial_capital
        self.trade_log: list[dict] = []

    def record_trade(self, trade_data: dict):
        """Log a completed trade."""
        pnl = trade_data.get("pnl", 0)
        self.current_capital += pnl
        self.trade_log.append(trade_data)

    def get_state(self) -> dict:
        """Current portfolio state (for Firebase)."""
        return {
            "initial_capital": self.initial_capital,
            "current_capital": round(self.current_capital, 2),
            "day_pnl": round(self.current_capital - self.day_start_capital, 2),
            "total_pnl": round(self.current_capital - self.initial_capital, 2),
            "total_return_pct": round(
                ((self.current_capital - self.initial_capital) / self.initial_capital) * 100, 2
            ),
            "trades_today": len([t for t in self.trade_log]),
        }

    def daily_report(self) -> dict:
        """End-of-day performance summary."""
        day_trades = self.trade_log  # TODO: filter to today's trades
        wins = [t for t in day_trades if t.get("pnl", 0) > 0]
        losses = [t for t in day_trades if t.get("pnl", 0) <= 0]

        return {
            "starting_capital": self.day_start_capital,
            "ending_capital": round(self.current_capital, 2),
            "day_pnl": round(self.current_capital - self.day_start_capital, 2),
            "trades_taken": len(day_trades),
            "win_rate": round(len(wins) / len(day_trades) * 100, 1) if day_trades else 0,
            "wins": len(wins),
            "losses": len(losses),
        }

    def reset_daily(self):
        """Call at start of new trading day."""
        self.day_start_capital = self.current_capital
        self.trade_log.clear()
