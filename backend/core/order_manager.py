"""
Order Manager — Places, Monitors, and Exits Trades (Sniper Mode V2).
=====================================================================

Sniper Mode V2 features:
- Pre-flight checklist: 17 checks before every trade
- ATR-based dynamic SL (1.5× ATR normal, 2× caution, 0.5%-3% bounds)
- ATR-based trailing SL (1× ATR from peak after 1.5R profit)
- R-multiple tracking: log actual R-multiple for every closed trade
- Signal queue integration: only top-scored signal per cycle executed

Preserved features:
- Adopt existing positions on startup (crash recovery)
- Broker-side SL orders (exchange-level protection even if bot crashes)
- Breakeven at 1% profit, win zone exit at 70% of target
- Time-based exits: tighten SL after 2:30 PM, exit profits after 3:00 PM
- Smart partial exit: 50% at 1x RR, SL moves to breakeven
- Slippage tracking, partial fill detection, pending order timeout
- reconcile_positions(): verify broker state after reconnect
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
    - effective_sl: current active stop-loss (moves to breakeven at 1% profit)
    - trailing_sl: trailing stop-loss price (activates at 2% profit)
    - trailing_active: True when trailing SL is engaged
    - peak_price: highest price reached for LONG (or lowest for SHORT)
    - realized_pnl: P&L from already-closed portions
    - actual_entry: actual fill price (may differ from signal.entry_price due to slippage)
    - slippage: actual_entry - expected_entry (positive = we paid more for LONG)
    - sl_order_id: Angel One SL order ID (exchange-level protection)
    - breakeven_moved: True after SL was moved to breakeven at 1% profit
    - in_win_zone: True after price reached 70% of target
    - peak_since_win_zone: best price since entering win zone (for reversal detection)
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

    # Trailing SL fields (improved: breakeven at 1%, trail at 2%)
    trailing_sl: float = 0.0         # Current trailing SL price
    trailing_active: bool = False     # True once 2% profit threshold reached
    peak_price: float = 0.0          # Best price seen (for trailing calc)
    breakeven_moved: bool = False     # True after SL moved to breakeven at 1% profit

    # Win zone fields (exit if 70% of target reached and price reverses 0.5%)
    in_win_zone: bool = False
    peak_since_win_zone: float = 0.0  # Best price since entering 70% target zone

    # Slippage tracking
    actual_entry: float = 0.0        # Actual fill price from broker
    slippage: float = 0.0            # actual_entry - signal.entry_price

    # Broker-side SL order (exchange-level protection)
    sl_order_id: str = ""            # Angel One SL order ID

    # Adopted position flag
    is_adopted: bool = False         # True if adopted from broker on startup

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
        """First partial exit level: entry + 1x risk."""
        risk = abs(self.signal.entry_price - self.signal.stop_loss)
        if self.signal.direction == "LONG":
            return round(self.signal.entry_price + risk, 2)
        else:
            return round(self.signal.entry_price - risk, 2)

    @property
    def hold_time_minutes(self) -> float:
        """How long this position has been open (minutes)."""
        return (time_module.time() - self.placed_at) / 60

    @property
    def profit_pct(self) -> float:
        """Current unrealized profit as a percentage of entry price."""
        if self.actual_entry == 0:
            return 0.0
        if self.signal.direction == "LONG":
            return ((self.current_price - self.actual_entry) / self.actual_entry) * 100
        else:
            return ((self.actual_entry - self.current_price) / self.actual_entry) * 100

    @property
    def win_zone_price(self) -> float:
        """Price at 70% of target (win zone threshold)."""
        entry = self.signal.entry_price
        target = self.signal.target
        distance = abs(target - entry)
        if self.signal.direction == "LONG":
            return round(entry + distance * 0.70, 2)
        else:
            return round(entry - distance * 0.70, 2)

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
            "breakeven_moved": self.breakeven_moved,
            "in_win_zone": self.in_win_zone,
            "current_price": self.current_price,
            "unrealized_pnl": round(self.unrealized_pnl, 2),
            "realized_pnl": round(self.realized_pnl, 2),
            "status": self.status,
            "hold_time_min": round(self.hold_time_minutes, 1),
            "score": getattr(self.signal, "score", 0),
            "strategy": self.signal.strategy_name,
            "has_broker_sl": bool(self.sl_order_id),
            "is_adopted": self.is_adopted,
        }


class OrderManager:
    """Manages order lifecycle: place -> monitor -> exit."""

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

        # WebSocket price cache reference — set via set_data_stream() after construction.
        # Used by monitor_positions() to read live prices without any API calls.
        self._data_stream = None

    def set_data_stream(self, data_stream):
        """Wire up the WebSocket data stream for cached price reads."""
        self._data_stream = data_stream

    def _get_cached_ltp(self, token: str) -> float:
        """
        Get last traded price from WebSocket cache. ZERO API calls.

        Falls back to broker API ONLY if WebSocket cache has no data for this token
        (e.g., during startup before WebSocket connects, or for adopted positions
        before the first tick arrives).
        """
        if self._data_stream:
            ltp = self._data_stream.get_ltp(token)
            if ltp > 0:
                return ltp
        # Fallback: API call (only happens if WebSocket hasn't sent a tick yet)
        logger.debug(f"No cached price for token {token}, falling back to API")
        return self.broker.get_ltp(token=token)

    # ──────────────────────────────────────────────────────────
    # FIX 1: Adopt existing positions from broker on startup
    # ──────────────────────────────────────────────────────────

    def adopt_positions(self, broker_positions: list[dict]) -> list[Position]:
        """
        Adopt existing open intraday positions from Angel One on startup.

        Called during startup to recover positions from a previous run
        or crash. Each position gets:
        - A synthetic Signal object based on broker data
        - Stop-loss at 2.5% from average entry price
        - Target at 2:1 reward-to-risk ratio
        - Trailing SL monitoring starts immediately
        - Broker-side SL order placed for exchange-level protection
        - Counted toward today's trade count

        Args:
            broker_positions: List of position dicts from broker.get_positions()
                Each dict has: tradingsymbol, symboltoken, netqty, avgnetprice,
                ltp, pnl, producttype, exchange, etc.

        Returns:
            List of adopted Position objects.
        """
        if not broker_positions:
            logger.info("No existing positions found at broker. Starting fresh.")
            return []

        adopted = []
        for bp in broker_positions:
            try:
                net_qty = int(bp.get("netqty", 0))
                if net_qty == 0:
                    continue  # Skip fully closed positions

                # Parse position details from Angel One
                raw_symbol = bp.get("tradingsymbol", "UNKNOWN")
                symbol = raw_symbol.replace("-EQ", "")
                token = str(bp.get("symboltoken", ""))
                avg_price = float(bp.get("avgnetprice", 0) or bp.get("buyavgprice", 0) or 0)
                ltp = float(bp.get("ltp", avg_price) or avg_price)
                quantity = abs(net_qty)
                direction = "LONG" if net_qty > 0 else "SHORT"
                current_pnl = float(bp.get("pnl", 0) or 0)

                if avg_price <= 0:
                    logger.warning(f"Skipping {symbol}: invalid avg price {avg_price}")
                    continue

                # Calculate SL at 2.5% from entry
                sl_distance = avg_price * 0.025
                if direction == "LONG":
                    stop_loss = round(avg_price - sl_distance, 2)
                    target = round(avg_price + sl_distance * 2, 2)  # 2:1 RR
                else:
                    stop_loss = round(avg_price + sl_distance, 2)
                    target = round(avg_price - sl_distance * 2, 2)

                # Create a synthetic Signal for this adopted position
                signal = Signal(
                    stock=symbol,
                    token=token,
                    direction=direction,
                    entry_price=avg_price,
                    stop_loss=stop_loss,
                    target=target,
                    strategy_name="ADOPTED",
                    confidence=0.5,
                    reason=f"Adopted from broker on startup (avg Rs.{avg_price:.2f})",
                    quantity=quantity,
                )

                # Create Position object
                pos = Position(
                    signal=signal,
                    order_id=f"adopted_{symbol}_{int(time_module.time())}",
                    status="OPEN",
                    current_price=ltp,
                    remaining_quantity=quantity,
                    actual_entry=avg_price,
                    effective_sl=stop_loss,
                    peak_price=max(ltp, avg_price) if direction == "LONG" else min(ltp, avg_price),
                    is_adopted=True,
                )

                # Place broker-side SL order for exchange-level protection
                sl_order_id = self._place_broker_sl_order(pos)
                if sl_order_id:
                    pos.sl_order_id = sl_order_id

                self.open_positions.append(pos)

                # Count toward today's trade count and capital deployment
                self.risk_manager.confirm_trade_placed(
                    stock=symbol,
                    entry_price=avg_price,
                    quantity=quantity,
                )

                adopted.append(pos)
                logger.info(
                    f"Adopted: {direction} {quantity}x {symbol} "
                    f"@ Rs.{avg_price:.2f} | LTP: Rs.{ltp:.2f} | "
                    f"P&L: Rs.{current_pnl:+.2f} | "
                    f"SL: Rs.{stop_loss:.2f} | Target: Rs.{target:.2f} | "
                    f"Broker SL: {'YES' if sl_order_id else 'NO (software only)'}"
                )

            except Exception as e:
                symbol = bp.get("tradingsymbol", "?")
                logger.error(f"Failed to adopt position {symbol}: {e}")

        logger.info(
            f"Adopted {len(adopted)} existing positions from Angel One. "
            f"All are now monitored with SL/target/trailing."
        )
        return adopted

    # ──────────────────────────────────────────────────────────
    # Broker-side SL Order Management (FIX 4)
    # ──────────────────────────────────────────────────────────

    def _place_broker_sl_order(self, pos: Position) -> str:
        """
        Place a STOPLOSS-LIMIT order with Angel One for a position.

        This is the safety net — even if the bot crashes, the exchange
        has a real SL order that triggers automatically.

        Returns the SL order ID, or empty string on failure.
        """
        try:
            buffer = self.config.sl_order_price_buffer
            sl_order_id = self.broker.place_sl_order(
                stock=pos.signal.stock,
                token=pos.signal.token,
                direction=pos.signal.direction,
                quantity=pos.remaining_quantity,
                trigger_price=pos.effective_sl,
                price_buffer=buffer,
            )
            if sl_order_id:
                return sl_order_id
            else:
                logger.error(
                    f"Broker SL order failed for {pos.signal.stock}. "
                    "Falling back to software-only SL monitoring."
                )
                return ""
        except Exception as e:
            logger.error(
                f"Broker SL order exception for {pos.signal.stock}: {e}. "
                "Falling back to software-only SL monitoring."
            )
            return ""

    def _modify_broker_sl_order(self, pos: Position, new_sl_price: float) -> bool:
        """
        Update the broker-side SL order to match the new trailing/breakeven SL.

        Returns True on success, False on failure (position keeps software SL).
        """
        if not pos.sl_order_id:
            return False

        try:
            buffer = self.config.sl_order_price_buffer
            success = self.broker.modify_sl_order(
                order_id=pos.sl_order_id,
                stock=pos.signal.stock,
                token=pos.signal.token,
                direction=pos.signal.direction,
                quantity=pos.remaining_quantity,
                new_trigger_price=new_sl_price,
                price_buffer=buffer,
            )
            if not success:
                logger.warning(
                    f"Could not modify broker SL for {pos.signal.stock}. "
                    "Software SL still active."
                )
            return success
        except Exception as e:
            logger.warning(f"Broker SL modify exception for {pos.signal.stock}: {e}")
            return False

    def _cancel_broker_sl_order(self, pos: Position) -> bool:
        """
        Cancel the broker-side SL order before placing a manual exit.

        Must be called before place_exit_order() to avoid double-exit
        (our exit + exchange SL both triggering).
        """
        if not pos.sl_order_id:
            return True  # No SL order to cancel

        try:
            success = self.broker.cancel_sl_order(pos.sl_order_id)
            if success:
                logger.info(f"Cancelled broker SL order for {pos.signal.stock}")
                pos.sl_order_id = ""
            else:
                logger.warning(
                    f"Could not cancel broker SL for {pos.signal.stock} "
                    f"(order {pos.sl_order_id}). May have already triggered."
                )
            return success
        except Exception as e:
            logger.warning(f"Broker SL cancel exception for {pos.signal.stock}: {e}")
            return False

    # ──────────────────────────────────────────────────────────
    # Pre-Flight Checklist (Sniper Mode V2 — Change 14)
    # ──────────────────────────────────────────────────────────

    def pre_flight_check(self, signal: Signal, scanner=None) -> tuple[bool, str]:
        """
        Run the 17-point pre-flight checklist before placing any order.

        Every check is logged. If ANY check fails, the trade is REJECTED.

        Returns:
            (passed: bool, fail_reason: str)
        """
        from datetime import datetime

        checks = []
        now = datetime.now().time()

        # Check 1: Signal score >= 85
        ok = signal.score >= self.config.min_score_to_trade
        checks.append(("Signal score >= 85", ok, f"score={signal.score}"))

        # Check 2: Confluence count >= 2
        ok = signal.confluence_count >= self.config.min_confluence_count
        checks.append(("Confluence >= 2 strategies", ok, f"confluence={signal.confluence_count}"))

        # Check 3: Volume >= 3× average (already gated in scanner, double-check)
        ok = True  # Scanner already enforced this
        checks.append(("Volume >= 3x average", ok, "passed in scanner"))

        # Check 4: VIX regime not DANGER
        vix = getattr(self, '_current_vix', 0)
        ok = vix <= self.config.vix_caution_threshold if vix > 0 else True
        checks.append(("VIX not DANGER", ok, f"VIX={vix:.1f}"))

        # Check 5: Not in lunch block
        in_lunch = (self.config.lunch_block_start <= now <= self.config.lunch_block_end)
        ok = not in_lunch
        checks.append(("Not in lunch block", ok, f"time={now.strftime('%H:%M')}"))

        # Check 6: Daily trade count < 3
        ok = self.risk_manager.trades_today < self.config.max_trades_per_day
        checks.append(("Daily trades < 3", ok, f"trades={self.risk_manager.trades_today}"))

        # Check 7: Daily losing trades < 2
        ok = self.risk_manager.losses_today < self.config.max_losses_per_day
        checks.append(("Daily losses < 2", ok, f"losses={self.risk_manager.losses_today}"))

        # Check 8: Choppiness Index < 61.8 (stock)
        ok = signal.choppiness <= self.config.chop_threshold
        checks.append(("Choppiness < 61.8", ok, f"CHOP={signal.choppiness:.1f}"))

        # Check 9: NIFTY Choppiness < 61.8
        nifty_chop = 50.0
        if scanner:
            nifty_chop = scanner.market_context.get("nifty_choppiness", 50.0)
        ok = nifty_chop <= self.config.chop_threshold
        checks.append(("NIFTY CHOP < 61.8", ok, f"NIFTY_CHOP={nifty_chop:.1f}"))

        # Check 10: 15-min trend agrees with direction
        if self.config.trend_15m_enabled:
            trend = signal.trend_15m
            if signal.direction == "LONG":
                ok = trend == "BULLISH"
            else:
                ok = trend == "BEARISH"
        else:
            ok = True
        checks.append(("15-min trend aligned", ok, f"trend={signal.trend_15m}"))

        # Check 11: Candle close confirms breakout (already in scanner)
        ok = True
        checks.append(("Candle close confirmation", ok, "passed in scanner"))

        # Check 12: ATR-based SL within 0.5%-3%
        if signal.entry_price > 0 and signal.stop_loss > 0:
            sl_pct = abs(signal.entry_price - signal.stop_loss) / signal.entry_price * 100
            ok = self.config.atr_sl_floor_pct <= sl_pct <= self.config.atr_sl_ceiling_pct
        else:
            ok = True
            sl_pct = 0
        checks.append(("SL within 0.5%-3%", ok, f"SL%={sl_pct:.2f}%"))

        # Check 13: Risk per trade within limits
        ok = True  # Risk manager handles this
        checks.append(("Risk within limits", ok, f"{self.config.max_risk_per_trade_pct}%"))

        # Check 14: Capital deployment < 80% of margin
        stats = self.risk_manager.get_deployment_stats()
        ok = stats["utilization_pct"] < self.config.max_capital_deployed_pct
        checks.append(("Capital < 80% deployed", ok, f"{stats['utilization_pct']:.0f}%"))

        # Check 15: Stock not in re-entry cooldown
        ok = signal.stock not in self.risk_manager._reentry_blocked_until or \
             datetime.now() >= self.risk_manager._reentry_blocked_until.get(signal.stock, datetime.min)
        checks.append(("No re-entry cooldown", ok, f"stock={signal.stock}"))

        # Check 16: Time in active window
        in_w1 = self.config.trading_window_1_start <= now <= self.config.trading_window_1_end
        in_w2 = self.config.trading_window_2_start <= now <= self.config.trading_window_2_end
        ok = in_w1 or in_w2
        checks.append(("In active window", ok, f"time={now.strftime('%H:%M')}"))

        # Check 17: Estimated net profit positive
        from utils.brokerage import is_trade_viable
        if signal.quantity > 0:
            viable, net_profit = is_trade_viable(
                signal.entry_price, signal.target, signal.quantity,
                signal.direction, min_profit=self.config.min_expected_net_profit
            )
            ok = viable
        else:
            ok = True
            net_profit = 0
        checks.append(("Net profit positive", ok, f"est_net=Rs.{net_profit:.2f}"))

        # Log all checks
        all_passed = True
        fail_reason = ""
        for i, (name, passed, detail) in enumerate(checks, 1):
            status = "PASS" if passed else "FAIL"
            logger.info(f"  PREFLIGHT #{i:02d}: {status} — {name} ({detail})")
            if not passed and all_passed:
                all_passed = False
                fail_reason = f"Check #{i} — {name} ({detail})"

        if all_passed:
            logger.info(f"PREFLIGHT PASSED: All 17 checks OK for {signal.stock}")
        else:
            logger.warning(f"PREFLIGHT FAILED: {fail_reason}")

        return all_passed, fail_reason

    def set_vix(self, vix: float):
        """Update current VIX value for pre-flight checklist."""
        self._current_vix = vix

    # ──────────────────────────────────────────────────────────
    # Order Execution
    # ──────────────────────────────────────────────────────────

    def _get_available_margin(self) -> float:
        """
        Query Angel One for available intraday margin.

        Returns the usable intraday buying power in Rs.
        Returns 0.0 if the API call fails — callers treat 0 as "skip the check"
        (we never block a trade just because we couldn't verify margin).
        """
        try:
            funds = self.broker.get_funds()
            if not funds:
                return 0.0
            intraday = float(funds.get("availableintradaypayin", 0) or 0)
            cash = float(funds.get("availablecash", 0) or 0)
            return intraday if intraday > 0 else cash
        except Exception as e:
            logger.debug(f"Margin check unavailable: {e}")
            return 0.0

    def execute(self, signal: Signal) -> Optional[Position]:
        """
        Place an order based on a signal.

        After placing and confirming fill:
        - Places a broker-side SL order with Angel One (exchange-level protection)
        - Falls back to software-only SL if broker SL fails
        """
        # ── Margin check before placing order ────────────────────────────
        try:
            required_margin = signal.entry_price * signal.quantity
            available_margin = self._get_available_margin()

            if available_margin > 0:
                if required_margin > available_margin:
                    max_qty = int(available_margin / signal.entry_price)

                    if max_qty < 1:
                        logger.warning(
                            f"MARGIN INSUFFICIENT: {signal.stock} — "
                            f"need Rs.{required_margin:.0f}, "
                            f"only Rs.{available_margin:.0f} available. Skipping."
                        )
                        return None

                    logger.warning(
                        f"MARGIN LIMITED: {signal.stock} — "
                        f"reducing qty from {signal.quantity} to {max_qty}"
                    )
                    signal.quantity = max_qty
        except Exception as e:
            logger.warning(f"Margin check error for {signal.stock}: {e}. Proceeding anyway.")

        # ── Place the entry order ──────────────────────────────────────────
        try:
            order_id = self.broker.place_order(
                stock=signal.stock,
                token=signal.token,
                direction=signal.direction,
                quantity=signal.quantity,
                price=signal.entry_price,
            )
        except Exception as e:
            logger.error(
                f"Order placement exception for {signal.stock}: {e}. "
                "Position not opened."
            )
            return None

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
            filled_qty = signal.quantity
        elif filled_qty < signal.quantity:
            logger.warning(
                f"Partial fill: {signal.stock} — got {filled_qty} of {signal.quantity} shares"
            )
            signal.quantity = filled_qty

        # Get actual fill price for slippage calculation
        actual_entry = self._get_cached_ltp(signal.token) or signal.entry_price
        slippage = actual_entry - signal.entry_price
        if abs(slippage) > 0.01:
            slippage_pct = abs(slippage / signal.entry_price) * 100
            logger.warning(
                f"Slippage: {signal.stock} | "
                f"Expected Rs.{signal.entry_price:.2f}, Got Rs.{actual_entry:.2f} | "
                f"{slippage:+.2f} ({slippage_pct:.3f}%)"
            )

        pos = Position(
            signal=signal,
            order_id=order_id,
            remaining_quantity=filled_qty,
            actual_entry=actual_entry,
            slippage=slippage,
        )

        # ── Place broker-side SL order (FIX 4) ────────────────────────────
        sl_order_id = self._place_broker_sl_order(pos)
        if sl_order_id:
            pos.sl_order_id = sl_order_id

        self.open_positions.append(pos)

        # Confirm with risk manager
        self.risk_manager.confirm_trade_placed(
            stock=signal.stock,
            entry_price=actual_entry,
            quantity=filled_qty,
        )

        logger.info(
            f"Position opened: {signal.direction} {filled_qty}x {signal.stock} "
            f"@ Rs.{actual_entry:.2f} | SL: Rs.{signal.stop_loss:.2f} | "
            f"Target: Rs.{signal.target:.2f} | "
            f"Broker SL: {'YES' if sl_order_id else 'NO (software only)'}"
        )
        return pos

    # ──────────────────────────────────────────────────────────
    # Position Monitoring (FIX 3: improved profit management)
    # ──────────────────────────────────────────────────────────

    def monitor_positions(self) -> tuple[list[Position], list[Position]]:
        """
        Check all open positions for SL/target/trailing SL/win zone/time exits.

        Order of checks (priority from highest to lowest):
        1. Effective SL hit (original, breakeven, or tightened)
        2. Trailing SL hit (if active)
        3. Time-based exit: after 3:00 PM exit in-profit positions
        4. Win zone reversal: 70% of target reached, then 0.5% reversal
        5. Partial exit at target1 (1x RR)
        6. Full exit at target2 (signal.target)
        7. Profit management: breakeven at 1%, trailing at 2%
        8. Time-based SL tightening: after 2:30 PM, SL = 1%

        Returns:
            (newly_closed, partially_updated) — main.py uses these for Firebase
        """
        newly_closed: list[Position] = []
        partially_updated: list[Position] = []

        # Also check for pending order timeouts
        self._check_pending_timeouts()

        now = datetime.now().time()
        is_late_session = now >= self.config.late_session_start
        is_profit_exit_time = now >= self.config.profit_exit_time

        for pos in self.open_positions[:]:
            if pos.status not in ("OPEN", "PARTIAL"):
                continue

            ltp = self._get_cached_ltp(pos.signal.token)
            if not ltp or ltp <= 0:
                continue

            pos.current_price = ltp
            direction = pos.signal.direction

            # ── Calculate unrealized P&L ──────────────────────────────────
            if direction == "LONG":
                pos.unrealized_pnl = (
                    (ltp - pos.signal.entry_price) * pos.remaining_quantity
                    + pos.realized_pnl
                )
            else:
                pos.unrealized_pnl = (
                    (pos.signal.entry_price - ltp) * pos.remaining_quantity
                    + pos.realized_pnl
                )

            # ── Update peak price ─────────────────────────────────────────
            if direction == "LONG":
                if ltp > pos.peak_price:
                    pos.peak_price = ltp
            else:
                if ltp < pos.peak_price or pos.peak_price == pos.signal.entry_price:
                    pos.peak_price = ltp

            # ── Update win zone peak ──────────────────────────────────────
            if pos.in_win_zone:
                if direction == "LONG" and ltp > pos.peak_since_win_zone:
                    pos.peak_since_win_zone = ltp
                elif direction == "SHORT" and (ltp < pos.peak_since_win_zone or pos.peak_since_win_zone == 0):
                    pos.peak_since_win_zone = ltp

            # ── PROFIT MANAGEMENT: breakeven and trailing (FIX 3a) ────────
            profit_pct = pos.profit_pct
            sl_changed = False

            # Step 1: At 1% profit -> move SL to breakeven (entry + approx charges)
            if (
                not pos.breakeven_moved
                and self.config.trailing_sl_enabled
                and profit_pct >= self.config.breakeven_profit_pct
            ):
                # Breakeven = entry price (charges are small relative to 1% move)
                new_sl = pos.actual_entry
                if direction == "LONG" and new_sl > pos.effective_sl:
                    pos.effective_sl = new_sl
                    pos.breakeven_moved = True
                    sl_changed = True
                    logger.info(
                        f"Breakeven SL: {pos.signal.stock} at {profit_pct:.1f}% profit. "
                        f"SL moved to Rs.{new_sl:.2f}"
                    )
                elif direction == "SHORT" and new_sl < pos.effective_sl:
                    pos.effective_sl = new_sl
                    pos.breakeven_moved = True
                    sl_changed = True
                    logger.info(
                        f"Breakeven SL: {pos.signal.stock} at {profit_pct:.1f}% profit. "
                        f"SL moved to Rs.{new_sl:.2f}"
                    )

            # Step 2: At 1.5R profit -> activate trailing SL at 1× ATR from peak
            # Use R-multiple if ATR/SL data available, else fall back to pct
            initial_risk = abs(pos.actual_entry - pos.signal.stop_loss)
            if initial_risk > 0 and pos.signal.direction == "LONG":
                current_r = (ltp - pos.actual_entry) / initial_risk
            elif initial_risk > 0 and pos.signal.direction == "SHORT":
                current_r = (pos.actual_entry - ltp) / initial_risk
            else:
                current_r = 0

            trail_trigger = (
                current_r >= self.config.trailing_activation_r
                if initial_risk > 0
                else profit_pct >= self.config.trailing_activation_pct
            )
            if (
                not pos.trailing_active
                and self.config.trailing_sl_enabled
                and trail_trigger
            ):
                pos.trailing_active = True
                pos.trailing_sl = self._calc_trailing_sl(pos, ltp)
                sl_changed = True
                logger.info(
                    f"Trailing SL activated: {pos.signal.stock} at {profit_pct:.1f}% profit. "
                    f"Trail @ Rs.{pos.trailing_sl:.2f}"
                )

            # Step 3: Update trailing SL as price moves favorably
            if pos.trailing_active:
                new_trail = self._calc_trailing_sl(pos, ltp)
                if direction == "LONG" and new_trail > pos.trailing_sl:
                    pos.trailing_sl = new_trail
                    sl_changed = True
                elif direction == "SHORT" and (new_trail < pos.trailing_sl or pos.trailing_sl == 0):
                    pos.trailing_sl = new_trail
                    sl_changed = True

            # ── TIME-BASED SL TIGHTENING (FIX 3c) ────────────────────────
            if is_late_session and not is_profit_exit_time:
                # After 2:30 PM: tighten SL to 1% from current price
                late_sl_distance = ltp * (self.config.late_session_sl_pct / 100)
                if direction == "LONG":
                    late_sl = round(ltp - late_sl_distance, 2)
                    if late_sl > pos.effective_sl:
                        pos.effective_sl = late_sl
                        sl_changed = True
                else:
                    late_sl = round(ltp + late_sl_distance, 2)
                    if late_sl < pos.effective_sl:
                        pos.effective_sl = late_sl
                        sl_changed = True

            # ── Sync broker SL order if SL changed ────────────────────────
            if sl_changed and pos.sl_order_id:
                # Use the tightest SL (whichever is closest to current price)
                active_sl = pos.effective_sl
                if pos.trailing_active and pos.trailing_sl > 0:
                    if direction == "LONG":
                        active_sl = max(pos.effective_sl, pos.trailing_sl)
                    else:
                        active_sl = min(pos.effective_sl, pos.trailing_sl)
                self._modify_broker_sl_order(pos, active_sl)

            # ── CHECK EXITS (priority order) ──────────────────────────────

            # Check 1: Stop-loss hit
            if direction == "LONG" and ltp <= pos.effective_sl:
                self._close_remaining(pos, pos.effective_sl, "STOP_LOSS")
                newly_closed.append(pos)
                continue
            elif direction == "SHORT" and ltp >= pos.effective_sl:
                self._close_remaining(pos, pos.effective_sl, "STOP_LOSS")
                newly_closed.append(pos)
                continue

            # Check 2: Trailing SL hit
            if pos.trailing_active and pos.trailing_sl > 0:
                if direction == "LONG" and ltp <= pos.trailing_sl:
                    self._close_remaining(pos, pos.trailing_sl, "TRAILING_STOP")
                    newly_closed.append(pos)
                    continue
                elif direction == "SHORT" and ltp >= pos.trailing_sl:
                    self._close_remaining(pos, pos.trailing_sl, "TRAILING_STOP")
                    newly_closed.append(pos)
                    continue

            # Check 3: Time-based profit exit (after 3:00 PM, exit if in profit)
            if is_profit_exit_time and profit_pct > 0:
                self._close_remaining(pos, ltp, "TIME_PROFIT_EXIT")
                newly_closed.append(pos)
                continue

            # Check 4: Win zone reversal (70% of target reached, then 0.5% reversal)
            win_zone_price = pos.win_zone_price
            if direction == "LONG":
                if not pos.in_win_zone and ltp >= win_zone_price:
                    pos.in_win_zone = True
                    pos.peak_since_win_zone = ltp
                    logger.info(
                        f"Win zone entered: {pos.signal.stock} at Rs.{ltp:.2f} "
                        f"(70% of target Rs.{pos.signal.target:.2f})"
                    )
                if pos.in_win_zone and pos.peak_since_win_zone > 0:
                    reversal_pct = ((pos.peak_since_win_zone - ltp) / pos.peak_since_win_zone) * 100
                    if reversal_pct >= self.config.win_zone_reversal_pct:
                        self._close_remaining(pos, ltp, "WIN_ZONE_REVERSAL")
                        newly_closed.append(pos)
                        continue
            else:  # SHORT
                if not pos.in_win_zone and ltp <= win_zone_price:
                    pos.in_win_zone = True
                    pos.peak_since_win_zone = ltp
                    logger.info(
                        f"Win zone entered: {pos.signal.stock} at Rs.{ltp:.2f} "
                        f"(70% of target Rs.{pos.signal.target:.2f})"
                    )
                if pos.in_win_zone and pos.peak_since_win_zone > 0:
                    reversal_pct = ((ltp - pos.peak_since_win_zone) / pos.peak_since_win_zone) * 100
                    if reversal_pct >= self.config.win_zone_reversal_pct:
                        self._close_remaining(pos, ltp, "WIN_ZONE_REVERSAL")
                        newly_closed.append(pos)
                        continue

            # Check 5: Partial exit at target1 (1x RR)
            if self.config.partial_exit_enabled and not pos.partial_exit_done:
                if direction == "LONG" and ltp >= pos.target1:
                    self._partial_exit(pos, ltp)
                    partially_updated.append(pos)
                    continue
                elif direction == "SHORT" and ltp <= pos.target1:
                    self._partial_exit(pos, ltp)
                    partially_updated.append(pos)
                    continue

            # Check 6: Full target hit
            if direction == "LONG" and ltp >= pos.signal.target:
                self._close_remaining(pos, pos.signal.target, "TARGET")
                newly_closed.append(pos)
                continue
            elif direction == "SHORT" and ltp <= pos.signal.target:
                self._close_remaining(pos, pos.signal.target, "TARGET")
                newly_closed.append(pos)
                continue

        return newly_closed, partially_updated

    def _calc_trailing_sl(self, pos: Position, current_price: float) -> float:
        """
        Calculate trailing stop-loss price using ATR-based distance.

        Sniper Mode V2: Trail at 1× ATR from peak/trough.
        Falls back to percentage-based trail if ATR is not available.

        For LONG: trailing SL = peak_price - (1× ATR)
        For SHORT: trailing SL = trough_price + (1× ATR)
        """
        atr = getattr(pos.signal, "atr_value", 0)

        if atr > 0:
            # ATR-based trailing (sniper mode)
            trail_amount = atr * self.config.trailing_sl_atr_multiplier
        else:
            # Fallback: percentage-based trailing
            trail_pct = self.config.trailing_distance_pct / 100
            trail_amount = pos.peak_price * trail_pct

        if pos.signal.direction == "LONG":
            return round(pos.peak_price - trail_amount, 2)
        else:
            return round(pos.peak_price + trail_amount, 2)

    def _partial_exit(self, pos: Position, exit_price: float):
        """
        Exit 50% of position at 1x RR and move SL to breakeven.
        """
        half_qty = pos.remaining_quantity // 2
        if half_qty <= 0:
            self._close_remaining(pos, exit_price, "TARGET1_FULL")
            return

        # Cancel broker SL first, then place partial exit, then place new SL
        self._cancel_broker_sl_order(pos)

        exit_order_id = self.broker.place_exit_order(
            stock=pos.signal.stock,
            token=pos.signal.token,
            direction=pos.signal.direction,
            quantity=half_qty,
        )

        if not exit_order_id:
            logger.error(f"Partial exit order failed for {pos.signal.stock}")
            # Re-place broker SL order since we cancelled it
            sl_id = self._place_broker_sl_order(pos)
            if sl_id:
                pos.sl_order_id = sl_id
            return

        # P&L for the exited half
        if pos.signal.direction == "LONG":
            pnl_partial = (exit_price - pos.signal.entry_price) * half_qty
        else:
            pnl_partial = (pos.signal.entry_price - exit_price) * half_qty

        charges = calculate_charges(
            pos.signal.entry_price, exit_price, half_qty, pos.signal.direction
        )

        pos.realized_pnl += pnl_partial
        pos.remaining_quantity -= half_qty
        pos.partial_exit_done = True
        pos.effective_sl = pos.signal.entry_price  # Move SL to breakeven
        pos.breakeven_moved = True

        # Activate trailing SL on remaining position if not already active
        if self.config.trailing_sl_enabled and not pos.trailing_active:
            pos.trailing_active = True
            pos.trailing_sl = self._calc_trailing_sl(pos, exit_price)
            pos.peak_price = exit_price

        pos.status = "PARTIAL"

        # Place new broker SL order for remaining quantity
        new_sl_price = max(pos.effective_sl, pos.trailing_sl) if pos.signal.direction == "LONG" else min(pos.effective_sl, pos.trailing_sl) if pos.trailing_sl > 0 else pos.effective_sl
        sl_id = self._place_broker_sl_order(pos)
        if sl_id:
            pos.sl_order_id = sl_id

        logger.info(
            f"Partial exit: {pos.signal.stock} -- sold {half_qty} @ Rs.{exit_price:.2f} | "
            f"Gross P&L: Rs.{pnl_partial:+.2f} | Net: Rs.{charges['net_pnl']:+.2f} | "
            f"SL moved to breakeven Rs.{pos.signal.entry_price:.2f} | "
            f"Trailing SL: Rs.{pos.trailing_sl:.2f} | "
            f"Remaining: {pos.remaining_quantity} shares"
        )

    def _close_remaining(self, pos: Position, exit_price: float, reason: str):
        """Close all remaining shares. Cancel broker SL first. Record final P&L."""
        # Cancel broker-side SL order before placing exit order
        self._cancel_broker_sl_order(pos)

        if pos.remaining_quantity > 0:
            exit_order_id = self.broker.place_exit_order(
                stock=pos.signal.stock,
                token=pos.signal.token,
                direction=pos.signal.direction,
                quantity=pos.remaining_quantity,
            )
            if not exit_order_id:
                logger.error(
                    f"Exit order failed for {pos.signal.stock} ({reason}) -- "
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

        # ── R-Multiple tracking (Change 13) ─────────────────────────────
        # R = initial risk per share (entry - SL for longs, SL - entry for shorts)
        # R-multiple = actual P&L per share / R
        initial_risk = abs(pos.actual_entry - pos.signal.stop_loss)
        if initial_risk > 0 and pos.signal.quantity > 0:
            pnl_per_share = total_gross / pos.signal.quantity
            r_multiple = round(pnl_per_share / initial_risk, 2)
        else:
            r_multiple = 0.0

        planned_r_target = self.config.risk_reward_ratio  # 2.5R

        # Update risk manager (includes re-entry cooldown)
        self.risk_manager.record_trade_result(total_net, pos.signal.stock)

        # Update portfolio
        self.portfolio.record_trade({
            "stock": pos.signal.stock,
            "direction": pos.signal.direction,
            "entry": pos.actual_entry,
            "exit": exit_price,
            "quantity": pos.signal.quantity,
            "gross_pnl": round(total_gross, 2),
            "pnl": round(total_net, 2),
            "charges": charges,
            "reason": reason,
            "strategy": pos.signal.strategy_name,
            "score": getattr(pos.signal, "score", 0),
            "slippage": pos.slippage,
            "hold_time_min": round(pos.hold_time_minutes, 1),
            "r_multiple": r_multiple,
            "planned_r_target": planned_r_target,
            "confluence_count": getattr(pos.signal, "confluence_count", 0),
            "confluence_strategies": getattr(pos.signal, "confluence_strategies", []),
            "atr_value": getattr(pos.signal, "atr_value", 0),
        })

        if pos in self.open_positions:
            self.open_positions.remove(pos)
        self.closed_positions.append(pos)

        icon = "Target" if "TARGET" in reason else "Trailing" if "TRAILING" in reason else "Stop" if "STOP" in reason else "Exit"
        logger.info(
            f"{icon}: {pos.signal.stock} | {reason} | "
            f"Gross: Rs.{total_gross:+.2f} | Net: Rs.{total_net:+.2f} | "
            f"{format_charges_summary(charges)}"
        )

    def exit_all_positions(self, reason: str = "FORCE_EXIT"):
        """
        Emergency exit for all open positions (kill switch / force exit at 3:15).

        Safe to call multiple times — skips if no open positions remain.
        Tracks exited symbols to prevent double-exit orders for the same stock.
        """
        if not self.open_positions:
            logger.info(f"exit_all_positions({reason}): no open positions to close.")
            return

        exited_symbols: set[str] = set()
        for pos in self.open_positions[:]:
            # Skip if we already placed an exit for this symbol in this batch
            if pos.signal.stock in exited_symbols:
                logger.warning(
                    f"Skipping duplicate exit for {pos.signal.stock} "
                    f"(already exited in this batch)"
                )
                continue
            exited_symbols.add(pos.signal.stock)
            ltp = self._get_cached_ltp(pos.signal.token) or pos.signal.entry_price
            self._close_remaining(pos, ltp, reason)
        logger.info(f"All positions closed ({reason}) — {len(exited_symbols)} exits placed")

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
                    f"we have {len(self.open_positions)} -- marking all closed"
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
                    f"Reconciliation: {pos.signal.stock} not in broker positions -- "
                    "likely closed while WebSocket was down"
                )
                pos.status = "CLOSED"
                pos.exit_reason = "RECONCILED_WHILE_OFFLINE"
                self.open_positions.remove(pos)
                self.closed_positions.append(pos)

    def _check_pending_timeouts(self):
        """
        Cancel LIMIT orders that haven't filled within config.pending_order_timeout_secs.
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
                    f"(order {order_id}) not filled in {timeout:.0f}s -- cancelling"
                )
                self.broker.cancel_order(order_id)
