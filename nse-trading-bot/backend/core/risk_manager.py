"""
Risk Manager — The Guardian of Your Capital
=============================================
This module enforces ALL safety rules. It has VETO power over every trade.
If the risk manager says no, the trade does not happen. Period.
"""

import logging
from datetime import datetime

from strategies.base_strategy import Signal

logger = logging.getLogger(__name__)


class RiskManager:
    """Enforces position sizing and risk limits."""

    def __init__(self, trading_config, portfolio):
        self.config = trading_config
        self.portfolio = portfolio
        self.trades_today = 0
        self.daily_pnl = 0.0
        self._start_of_day_capital = trading_config.initial_capital

    def reset_daily(self):
        """Call this at start of each trading day."""
        self.trades_today = 0
        self.daily_pnl = 0.0
        self._start_of_day_capital = self.portfolio.current_capital

    def can_trade(self, signal: Signal) -> bool:
        """
        Check if a trade is allowed. Returns True/False.
        Sets signal.reason if blocked.
        """
        # Rule 1: Max trades per day
        if self.trades_today >= self.config.max_trades_per_day:
            signal.reason = f"Max trades ({self.config.max_trades_per_day}) reached"
            return False

        # Rule 2: Daily loss limit
        if self.daily_loss_limit_hit():
            signal.reason = "Daily loss limit hit"
            return False

        # Rule 3: No trading after cutoff time
        now = datetime.now().time()
        if now > self.config.no_new_trades_after:
            signal.reason = "Past trading cutoff time"
            return False

        # Rule 4: Must have stop-loss
        if signal.stop_loss == 0:
            signal.reason = "No stop-loss defined"
            return False

        # Rule 5: Risk-reward must be acceptable
        if signal.risk_reward_ratio < 1.0:
            signal.reason = f"Risk-reward too low ({signal.risk_reward_ratio})"
            return False

        # Rule 6: Trade must be worth the commissions
        estimated_commission = self.config.brokerage_per_order * 2  # Buy + sell
        potential_profit = signal.reward_points * self._calc_quantity(signal)
        if potential_profit < estimated_commission * 2:
            signal.reason = f"Profit (₹{potential_profit:.0f}) doesn't justify commission (₹{estimated_commission:.0f})"
            return False

        # All checks passed — calculate position size
        signal.quantity = self._calc_quantity(signal)
        if signal.quantity <= 0:
            signal.reason = "Insufficient capital for minimum position"
            return False

        self.trades_today += 1
        return True

    def _calc_quantity(self, signal: Signal) -> int:
        """
        Position sizing based on risk.
        Quantity = (Capital × Risk%) / Risk per share
        """
        capital = self.portfolio.current_capital
        risk_amount = capital * (self.config.max_risk_per_trade_pct / 100)
        risk_per_share = signal.risk_points

        if risk_per_share <= 0:
            return 0

        quantity = int(risk_amount / risk_per_share)
        return max(quantity, 0)

    def daily_loss_limit_hit(self) -> bool:
        """Check if we've lost too much today."""
        limit = self._start_of_day_capital * (self.config.daily_loss_limit_pct / 100)
        return self.daily_pnl <= -limit

    def record_trade_result(self, pnl: float):
        """Update daily P&L tracking after a trade closes."""
        self.daily_pnl += pnl
        logger.info(f"📊 Daily P&L: ₹{self.daily_pnl:+,.2f}")
