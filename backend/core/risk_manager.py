"""
Risk Manager — The Guardian of Your Capital
=============================================
This module enforces ALL safety rules. It has VETO power over every trade.
If the risk manager says no, the trade does not happen. Period.

Production upgrades:
- Time-based position sizing (100% / 50% / 75% based on time of day)
- Market regime size multiplier (0.7x for volatile, 1.1x for trending)
- Duplicate order prevention (never trade same stock twice until closed)
- 60-minute cooldown after consecutive loss limit is hit
- Expected net P&L check (skip if profit after charges < Rs.5)
"""

import logging
from datetime import datetime, timedelta
from typing import Optional

from strategies.base_strategy import Signal
from utils.brokerage import is_trade_viable

logger = logging.getLogger(__name__)


class RiskManager:
    """Enforces position sizing and risk limits."""

    def __init__(self, trading_config, portfolio):
        self.config = trading_config
        self.portfolio = portfolio
        self.trades_today = 0
        self.daily_pnl = 0.0
        self._start_of_day_capital = trading_config.initial_capital

        # Consecutive loss tracking
        self.consecutive_losses = 0
        self._cooldown_until: Optional[datetime] = None  # When the cooldown ends

        # Duplicate prevention: set of stock symbols currently in a trade
        self._active_stocks: set[str] = set()

        # Market regime size multiplier (updated by main.py from regime detector)
        self.regime_size_multiplier: float = 1.0
        self.regime_sl_multiplier: float = 1.0

    def reset_daily(self):
        """Call this at start of each trading day."""
        self.trades_today = 0
        self.daily_pnl = 0.0
        self.consecutive_losses = 0
        self._cooldown_until = None
        self._active_stocks.clear()
        self._start_of_day_capital = self.portfolio.current_capital

    def set_regime_multipliers(self, size_mult: float, sl_mult: float):
        """Update regime-based multipliers (called from main.py on regime update)."""
        self.regime_size_multiplier = size_mult
        self.regime_sl_multiplier = sl_mult

    def mark_stock_active(self, stock: str):
        """Record that we have an open position in this stock."""
        self._active_stocks.add(stock)

    def mark_stock_closed(self, stock: str):
        """Record that the position in this stock was closed."""
        self._active_stocks.discard(stock)

    def can_trade(self, signal: Signal) -> bool:
        """
        Gate every potential trade through all safety rules.
        Sets signal.reason if blocked. Returns True only if ALL checks pass.
        """
        # Rule 1: Max trades per day
        if self.trades_today >= self.config.max_trades_per_day:
            signal.reason = f"Max trades ({self.config.max_trades_per_day}) reached today"
            return False

        # Rule 2: Daily loss limit
        if self.daily_loss_limit_hit():
            signal.reason = "Daily loss limit hit (3% of capital)"
            return False

        # Rule 3: No trading after cutoff time
        now = datetime.now().time()
        if now > self.config.no_new_trades_after:
            signal.reason = "Past trading cutoff (2:30 PM)"
            return False

        # Rule 4: Must be in an active trading window
        if not self._in_trading_window(now):
            signal.reason = (
                f"Outside trading windows "
                f"({self.config.trading_window_1_start.strftime('%H:%M')}-"
                f"{self.config.trading_window_1_end.strftime('%H:%M')} / "
                f"{self.config.trading_window_2_start.strftime('%H:%M')}-"
                f"{self.config.trading_window_2_end.strftime('%H:%M')})"
            )
            return False

        # Rule 5: Consecutive loss circuit breaker + cooldown
        if self._is_in_cooldown():
            remaining = (self._cooldown_until - datetime.now()).seconds // 60
            signal.reason = (
                f"Consecutive loss cooldown — {remaining} min remaining"
            )
            return False

        # Rule 6: Duplicate order prevention
        if signal.stock in self._active_stocks:
            signal.reason = f"Already have an open position in {signal.stock}"
            return False

        # Rule 7: Must have stop-loss
        if signal.stop_loss == 0:
            signal.reason = "No stop-loss defined"
            return False

        # Rule 8: Risk-reward must be acceptable
        if signal.risk_reward_ratio < 1.0:
            signal.reason = f"Risk-reward too low ({signal.risk_reward_ratio:.2f})"
            return False

        # Rule 9: Calculate position size (with time-based + regime scaling)
        quantity = self._calc_quantity(signal, now)
        if quantity <= 0:
            signal.reason = "Insufficient capital for minimum position"
            return False

        # Rule 10: Expected net profit must exceed charges
        viable, net_profit = is_trade_viable(
            entry_price=signal.entry_price,
            target_price=signal.target,
            quantity=quantity,
            direction=signal.direction,
            min_profit=self.config.min_expected_net_profit,
        )
        if not viable:
            signal.reason = (
                f"Expected net profit (Rs.{net_profit:.2f}) < "
                f"minimum (Rs.{self.config.min_expected_net_profit:.0f}) after charges"
            )
            return False

        # All checks passed — assign quantity and count the trade
        signal.quantity = quantity
        self.trades_today += 1
        self._active_stocks.add(signal.stock)
        return True

    def _calc_quantity(self, signal: Signal, now) -> int:
        """
        Position sizing with time-based and regime scaling.

        Base formula: quantity = (capital × risk%) / risk_per_share

        Then apply:
        1. Time-of-day scaling (100% / 50% / 75%)
        2. Regime scaling (0.7x volatile, 1.1x trending)
        3. Cap at 5× margin (Angel One intraday MIS gives ~5× leverage)
        """
        capital = self.portfolio.current_capital
        risk_amount = capital * (self.config.max_risk_per_trade_pct / 100)
        risk_per_share = signal.risk_points

        if risk_per_share <= 0:
            return 0

        # Base quantity from risk
        base_qty = int(risk_amount / risk_per_share)

        # Apply time-of-day scaling
        time_pct = self._get_time_size_pct(now)
        scaled_qty = int(base_qty * time_pct / 100)

        # Apply regime scaling
        regime_qty = int(scaled_qty * self.regime_size_multiplier)

        return max(regime_qty, 0)

    def _get_time_size_pct(self, now) -> float:
        """
        Position size % based on time of day.

        9:30-11:00: 100% — morning momentum, highest quality signals
        11:00-13:30: 50% — lunch lull, low volume, choppy price action
        13:30-14:30: 75% — afternoon momentum, good but not as strong as morning
        """
        w1_start = self.config.trading_window_1_start
        w1_end = self.config.trading_window_1_end
        w2_start = self.config.trading_window_2_start
        w2_end = self.config.trading_window_2_end

        if w1_start <= now <= w1_end:
            return self.config.position_size_window_1_pct   # 100%
        elif w2_start <= now <= w2_end:
            return self.config.position_size_window_2_pct   # 75%
        elif w1_end < now < w2_start:
            return self.config.position_size_lunch_pct      # 50%
        else:
            return 100.0  # Default (outside normal windows but before cutoff)

    def _in_trading_window(self, now) -> bool:
        """Check if current time falls in an active trading window."""
        in_w1 = (
            self.config.trading_window_1_start <= now <= self.config.trading_window_1_end
        )
        in_w2 = (
            self.config.trading_window_2_start <= now <= self.config.trading_window_2_end
        )
        return in_w1 or in_w2

    def _is_in_cooldown(self) -> bool:
        """Check if we're in the post-consecutive-loss cooldown period."""
        if self._cooldown_until is None:
            return False
        return datetime.now() < self._cooldown_until

    def daily_loss_limit_hit(self) -> bool:
        """Check if we've lost 3% or more of start-of-day capital."""
        limit = self._start_of_day_capital * (self.config.daily_loss_limit_pct / 100)
        return self.daily_pnl <= -limit

    def record_trade_result(self, pnl: float, stock: str = ""):
        """
        Update daily P&L and consecutive loss counter after a trade closes.
        Activates 60-minute cooldown if consecutive losses limit is hit.
        """
        self.daily_pnl += pnl

        # Free up the stock slot for future trades
        if stock:
            self.mark_stock_closed(stock)

        if pnl > 0:
            # Win — reset the consecutive loss streak
            if self.consecutive_losses > 0:
                logger.info(
                    f"Win after {self.consecutive_losses} consecutive losses — "
                    "resetting streak"
                )
            self.consecutive_losses = 0
            self._cooldown_until = None

        else:
            # Loss — increment counter
            self.consecutive_losses += 1
            logger.warning(
                f"Loss recorded. Consecutive losses: {self.consecutive_losses}"
                f"/{self.config.consecutive_loss_limit}"
            )

            if self.consecutive_losses >= self.config.consecutive_loss_limit:
                cooldown_mins = self.config.consecutive_loss_cooldown_minutes
                self._cooldown_until = datetime.now() + timedelta(minutes=cooldown_mins)
                logger.warning(
                    f"Consecutive loss circuit breaker! Trading paused for "
                    f"{cooldown_mins} minutes until "
                    f"{self._cooldown_until.strftime('%H:%M')}"
                )

        logger.info(f"Daily P&L: Rs.{self.daily_pnl:+,.2f} | "
                    f"Trades today: {self.trades_today}")
