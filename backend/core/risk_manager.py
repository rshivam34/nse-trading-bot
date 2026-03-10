"""
Risk Manager — The Guardian of Your Capital (Sniper Mode V2)
==============================================================
This module enforces ALL safety rules. It has VETO power over every trade.
If the risk manager says no, the trade does not happen. Period.

Sniper Mode V2 changes:
- Hard cap: 3 trades/day maximum (no exceptions)
- Max 2 losing trades/day (sniper mode is about quality, not quantity)
- VIX graduated response: NORMAL (<18) / CAUTION (18-20) / DANGER (>20)
- ATR-based position sizing (risk amount / ATR-based SL distance)
- Lunch block fully enforced (11:30-13:00 = no new trades)
- 1.5% risk per trade (tightened from 2%)
- 80% margin deployment limit still applies

Re-entry prevention:
- After exiting a stock, cannot re-enter same stock for 30 minutes

Other protections:
- Time-based position sizing (100% in active windows, 0% during lunch)
- Market regime size multiplier (0.7x for volatile, 1.1x for trending)
- Duplicate order prevention (never trade same stock twice until closed)
- Expected net P&L check (skip if profit after charges too low)
"""

import logging
from datetime import datetime, timedelta
from typing import Optional

from strategies.base_strategy import Signal
from utils.brokerage import is_trade_viable

logger = logging.getLogger(__name__)


class RiskManager:
    """Enforces position sizing and risk limits."""

    def __init__(self, trading_config, portfolio, broker=None):
        self.config = trading_config
        self.portfolio = portfolio
        self._broker = broker  # For margin queries via getRMS API
        self.trades_today = 0
        self.losses_today = 0  # Total losing trades today (not just consecutive)
        self.daily_pnl = 0.0
        self._start_of_day_capital = trading_config.initial_capital

        # Consecutive loss tracking
        self.consecutive_losses = 0
        self._cooldown_until: Optional[datetime] = None  # When the cooldown ends

        # Duplicate prevention: set of stock symbols currently in a trade
        self._active_stocks: set[str] = set()

        # Re-entry prevention (FIX 3d): stock -> earliest allowed re-entry time
        self._reentry_blocked_until: dict[str, datetime] = {}

        # Capital deployment tracking (local — no API call needed per signal)
        # Tracks sum of (entry_price × quantity) for all open positions
        self._deployed_capital: float = 0.0
        self._deployed_by_stock: dict[str, float] = {}  # stock -> deployed Rs.
        self._cached_margin: float = 0.0  # Last known margin from broker RMS API

        # Market regime size multiplier (updated by main.py from regime detector)
        self.regime_size_multiplier: float = 1.0
        self.regime_sl_multiplier: float = 1.0

        # VIX value for position sizing decisions
        self._current_vix: float = 0.0

        # Global risk day flag — set when geopolitical/macro events detected in news
        # Reduces ALL position sizes by 50% (same effect as VIX CAUTION)
        self._global_risk_day: bool = False

    def reset_daily(self):
        """Call this at start of each trading day."""
        self.trades_today = 0
        self.losses_today = 0
        self.daily_pnl = 0.0
        self.consecutive_losses = 0
        self._cooldown_until = None
        self._active_stocks.clear()
        self._reentry_blocked_until.clear()
        self._deployed_capital = 0.0
        self._deployed_by_stock.clear()
        self._global_risk_day = False
        self._start_of_day_capital = self.portfolio.current_capital
        self.refresh_margin()  # Get fresh margin at start of day

    def set_regime_multipliers(self, size_mult: float, sl_mult: float):
        """Update regime-based multipliers (called from main.py on regime update)."""
        self.regime_size_multiplier = size_mult
        self.regime_sl_multiplier = sl_mult

    def update_vix(self, vix: float):
        """Update current VIX value for position sizing decisions."""
        self._current_vix = vix

    def set_global_risk_day(self, is_risk_day: bool):
        """Set global risk day flag — reduces all position sizes by 50%.

        Called from main.py when news sentiment detects a major geopolitical
        or macro event (e.g., USA-Iran tensions, trade war, oil shock).
        Effect: same as VIX CAUTION — 50% position size reduction.
        """
        self._global_risk_day = is_risk_day
        if is_risk_day:
            logger.warning("Global risk day ACTIVE — all position sizes reduced 50%")

    def mark_stock_active(self, stock: str):
        """Record that we have an open position in this stock."""
        self._active_stocks.add(stock)

    def mark_stock_closed(self, stock: str):
        """Record that the position in this stock was closed."""
        self._active_stocks.discard(stock)

    # ──────────────────────────────────────────────────────────
    # Margin / Deployed Capital
    # ──────────────────────────────────────────────────────────

    def refresh_margin(self):
        """Fetch available margin from Angel One RMS API and cache it.

        Called after each trade open/close so the cached value stays current.
        Not called on every tick — that would be too many API calls.
        """
        if not self._broker:
            return

        try:
            funds = self._broker.get_funds()
            if funds:
                # availableintradaypayin = cash × intraday leverage (~5×)
                intraday = float(funds.get("availableintradaypayin", 0) or 0)
                cash = float(funds.get("availablecash", 0) or 0)
                self._cached_margin = intraday if intraday > 0 else cash
                logger.debug(f"Margin refreshed: Rs.{self._cached_margin:,.0f}")
        except Exception as e:
            logger.debug(f"Margin refresh failed: {e}")

    def _get_max_deployable(self) -> float:
        """Get the maximum capital we're allowed to have deployed at once.

        Returns 80% (configurable) of broker margin.
        Falls back to initial_capital if broker margin is unavailable.
        """
        pct = self.config.max_capital_deployed_pct / 100
        if self._cached_margin > 0:
            return self._cached_margin * pct
        # Fallback: use initial capital (no leverage assumed — conservative)
        return self.config.initial_capital * pct

    def get_deployment_stats(self) -> dict:
        """Return current capital deployment stats (for logging/dashboard)."""
        max_deploy = self._get_max_deployable()
        return {
            "deployed": round(self._deployed_capital, 2),
            "max_deployable": round(max_deploy, 2),
            "utilization_pct": round(
                (self._deployed_capital / max_deploy * 100) if max_deploy > 0 else 0, 1
            ),
            "cached_margin": round(self._cached_margin, 2),
            "open_positions": len(self._active_stocks),
            "trades_today": self.trades_today,
            "losses_today": self.losses_today,
        }

    # ──────────────────────────────────────────────────────────
    # Core Gate: can_trade()
    # ──────────────────────────────────────────────────────────

    def can_trade(self, signal: Signal) -> bool:
        """
        Gate every potential trade through all safety rules.
        Sets signal.reason if blocked. Returns True only if ALL checks pass.
        """
        # Rule 1: HARD cap on total trades (sniper mode: 3/day max)
        if self.trades_today >= self.config.max_trades_per_day:
            signal.reason = (
                f"Daily trade limit reached ({self.trades_today}/{self.config.max_trades_per_day}). "
                "Monitor-only mode for rest of day."
            )
            signal.status = "SKIPPED-DAILY-LIMIT"
            return False

        # Rule 2: 2 total losses today = done for the day (sniper mode)
        if self.losses_today >= self.config.max_losses_per_day:
            signal.reason = (
                f"Max losses ({self.losses_today}/{self.config.max_losses_per_day}) reached today — "
                "stopping to protect capital"
            )
            return False

        # Rule 3: Daily loss limit (3% of starting capital)
        if self.daily_loss_limit_hit():
            signal.reason = "Daily loss limit hit (3% of capital)"
            signal.status = "SKIPPED-DAILY-LOSS-LIMIT"
            return False

        # Rule 4: No trading after cutoff time
        now = datetime.now().time()
        if now > self.config.no_new_trades_after:
            signal.reason = "Past trading cutoff (2:30 PM)"
            return False

        # Rule 5: Must be in an active trading window
        if not self._in_trading_window(now):
            signal.reason = (
                f"Outside trading windows "
                f"({self.config.trading_window_1_start.strftime('%H:%M')}-"
                f"{self.config.trading_window_1_end.strftime('%H:%M')} / "
                f"{self.config.trading_window_2_start.strftime('%H:%M')}-"
                f"{self.config.trading_window_2_end.strftime('%H:%M')})"
            )
            return False

        # Rule 6: Consecutive loss circuit breaker + cooldown
        if self._is_in_cooldown():
            remaining = int((self._cooldown_until - datetime.now()).total_seconds()) // 60
            signal.reason = (
                f"Consecutive loss cooldown — {remaining} min remaining"
            )
            return False

        # Rule 7: Duplicate order prevention
        if signal.stock in self._active_stocks:
            signal.reason = f"Already have an open position in {signal.stock}"
            return False

        # Rule 7b: Re-entry cooldown (FIX 3d — 30-min block after exiting a stock)
        if signal.stock in self._reentry_blocked_until:
            block_until = self._reentry_blocked_until[signal.stock]
            if datetime.now() < block_until:
                remaining = int((block_until - datetime.now()).total_seconds()) // 60
                signal.reason = (
                    f"Re-entry blocked for {signal.stock} "
                    f"({remaining} min remaining of {self.config.reentry_cooldown_minutes}-min cooldown)"
                )
                return False
            else:
                # Cooldown expired — remove the block
                del self._reentry_blocked_until[signal.stock]

        # Rule 8: Must have stop-loss
        if signal.stop_loss == 0:
            signal.reason = "No stop-loss defined"
            return False

        # Rule 9: Risk-reward must be acceptable
        if signal.risk_reward_ratio < 1.0:
            signal.reason = f"Risk-reward too low ({signal.risk_reward_ratio:.2f})"
            return False

        # Rule 10: Calculate position size (with time-based + regime scaling)
        quantity = self._calc_quantity(signal, now)
        if quantity <= 0:
            signal.reason = "Insufficient capital for minimum position"
            return False

        # Rule 11: Capital deployment check — is there room for this trade?
        estimated_deployment = signal.entry_price * quantity
        max_deployable = self._get_max_deployable()
        if max_deployable > 0:
            remaining_capacity = max_deployable - self._deployed_capital
            if estimated_deployment > remaining_capacity:
                # Try reducing quantity to fit within remaining capacity
                reduced_qty = int(remaining_capacity / signal.entry_price)
                if reduced_qty <= 0:
                    signal.reason = (
                        f"Capital fully deployed: Rs.{self._deployed_capital:,.0f} used "
                        f"of Rs.{max_deployable:,.0f} max "
                        f"({self._deployed_capital / max_deployable * 100:.0f}%)"
                    )
                    return False
                logger.info(
                    f"Reducing {signal.stock} qty from {quantity} to {reduced_qty} "
                    f"(Rs.{remaining_capacity:,.0f} margin remaining)"
                )
                quantity = reduced_qty

        # Rule 12: Expected net profit must exceed charges (capital-scaled)
        capital = self.portfolio.current_capital
        if capital < 2000:
            min_profit = 8.0
        elif capital < 5000:
            min_profit = 12.0
        else:
            min_profit = self.config.min_expected_net_profit

        viable, net_profit = is_trade_viable(
            entry_price=signal.entry_price,
            target_price=signal.target,
            quantity=quantity,
            direction=signal.direction,
            min_profit=min_profit,
        )
        if not viable:
            signal.reason = (
                f"Expected net profit (Rs.{net_profit:.2f}) < "
                f"minimum (Rs.{min_profit:.0f}) after charges"
            )
            return False

        # All checks passed — assign quantity (trade count incremented later
        # by confirm_trade_placed() only if the order actually succeeds)
        signal.quantity = quantity
        return True

    # ──────────────────────────────────────────────────────────
    # Trade Lifecycle Callbacks
    # ──────────────────────────────────────────────────────────

    def confirm_trade_placed(self, stock: str, entry_price: float = 0.0, quantity: int = 0):
        """
        Called by order_manager ONLY after Angel One confirms the order.

        Increments the daily trade count, marks the stock as active,
        and tracks the deployed capital for this position.
        """
        self.trades_today += 1
        self._active_stocks.add(stock)

        # Track deployed capital for this stock
        deployed = entry_price * quantity
        if deployed > 0:
            self._deployed_capital += deployed
            self._deployed_by_stock[stock] = deployed

        stats = self.get_deployment_stats()
        logger.info(
            f"Trade confirmed: {stock} | "
            f"Trades today: {self.trades_today} | "
            f"Deployed: Rs.{stats['deployed']:,.0f} / Rs.{stats['max_deployable']:,.0f} "
            f"({stats['utilization_pct']:.0f}%)"
        )

        # Refresh margin from broker after trade placement
        self.refresh_margin()

    def record_trade_result(self, pnl: float, stock: str = ""):
        """
        Update daily P&L, loss counters, and deployed capital after a trade closes.
        Activates 60-minute cooldown if consecutive losses limit is hit.
        """
        self.daily_pnl += pnl

        # Free up the stock slot and release deployed capital
        if stock:
            self.mark_stock_closed(stock)
            freed = self._deployed_by_stock.pop(stock, 0)
            self._deployed_capital -= freed
            self._deployed_capital = max(0.0, self._deployed_capital)  # safety floor

            # Set re-entry cooldown (FIX 3d — block re-entry for 30 min)
            cooldown_mins = self.config.reentry_cooldown_minutes
            self._reentry_blocked_until[stock] = (
                datetime.now() + timedelta(minutes=cooldown_mins)
            )
            logger.info(
                f"Re-entry blocked for {stock} for {cooldown_mins} min "
                f"(until {self._reentry_blocked_until[stock].strftime('%H:%M')})"
            )

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
            # Loss — increment both counters
            self.losses_today += 1
            self.consecutive_losses += 1
            logger.warning(
                f"Loss recorded. "
                f"Consecutive: {self.consecutive_losses}/{self.config.consecutive_loss_limit} | "
                f"Total today: {self.losses_today}/{self.config.max_losses_per_day}"
            )

            if self.consecutive_losses >= self.config.consecutive_loss_limit:
                cooldown_mins = self.config.consecutive_loss_cooldown_minutes
                self._cooldown_until = datetime.now() + timedelta(minutes=cooldown_mins)
                logger.warning(
                    f"Consecutive loss circuit breaker! Trading paused for "
                    f"{cooldown_mins} minutes until "
                    f"{self._cooldown_until.strftime('%H:%M')}"
                )

        # Refresh margin from broker after position closes (frees margin)
        self.refresh_margin()

        stats = self.get_deployment_stats()
        logger.info(
            f"Daily P&L: Rs.{self.daily_pnl:+,.2f} | "
            f"Trades: {self.trades_today} | Losses: {self.losses_today} | "
            f"Deployed: Rs.{stats['deployed']:,.0f} ({stats['utilization_pct']:.0f}%)"
        )

    # ──────────────────────────────────────────────────────────
    # Position Sizing
    # ──────────────────────────────────────────────────────────

    def _calc_quantity(self, signal: Signal, now) -> int:
        """
        Position sizing with VIX-based, time-based, and regime scaling.

        Sniper Mode V2:
        - VIX < 18 (NORMAL):  full risk (1.5% of capital)
        - VIX 18-20 (CAUTION): half risk (0.75% of capital), wider ATR SL
        - VIX > 20 (DANGER):  blocked before reaching this point

        Base formula: quantity = (capital x risk%) / risk_per_share
        Then apply: time-of-day scaling + regime scaling
        """
        capital = self.portfolio.current_capital
        risk_pct = self.config.max_risk_per_trade_pct  # 1.5%

        # VIX graduated response: reduce risk in caution mode
        vix = getattr(self, '_current_vix', 0)
        if vix >= self.config.vix_normal_threshold and vix <= self.config.vix_caution_threshold:
            risk_pct = self.config.vix_caution_risk_pct  # 0.75%
            logger.info(
                f"VIX={vix:.1f} -> CAUTION: risk reduced to {risk_pct}% per trade"
            )

        risk_amount = capital * (risk_pct / 100)
        risk_per_share = signal.risk_points

        if risk_per_share <= 0:
            return 0

        # Base quantity from risk
        base_qty = int(risk_amount / risk_per_share)

        # Apply time-of-day scaling
        time_pct = self._get_time_size_pct(now)
        scaled_qty = int(base_qty * time_pct / 100)

        # Apply VIX caution size scaling
        if vix >= self.config.vix_normal_threshold and vix <= self.config.vix_caution_threshold:
            vix_size_pct = self.config.vix_caution_size_pct / 100  # 50%
            scaled_qty = int(scaled_qty * vix_size_pct)

        # Apply global risk day scaling (geopolitical/macro event → 50% size)
        if self._global_risk_day:
            scaled_qty = int(scaled_qty * 0.5)
            logger.info("Global risk day: position size halved")

        # Apply regime scaling
        regime_qty = int(scaled_qty * self.regime_size_multiplier)

        return max(regime_qty, 0)

    def _get_time_size_pct(self, now) -> float:
        """
        Position size % based on time of day.

        Sniper mode:
        9:30-11:30:  100% — morning momentum, highest quality signals
        11:30-13:00: 0%   — BLOCKED (lunch block, no new trades)
        13:00-14:30: 100% — afternoon momentum
        """
        w1_start = self.config.trading_window_1_start
        w1_end = self.config.trading_window_1_end
        w2_start = self.config.trading_window_2_start
        w2_end = self.config.trading_window_2_end

        if w1_start <= now <= w1_end:
            return 100.0   # Morning momentum window
        elif w2_start <= now <= w2_end:
            return 100.0   # Afternoon momentum window
        elif w1_end < now < w2_start:
            return 0.0     # Lunch block — no new trades
        else:
            return 100.0  # Default (outside normal windows but before cutoff)

    # ──────────────────────────────────────────────────────────
    # Helper Checks
    # ──────────────────────────────────────────────────────────

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
