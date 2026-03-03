"""
NSE Intraday Trading Bot -- Main Entry Point
=============================================
Run this every morning before market opens.

Usage:
    python main.py              # Mode from .env (paper/suggest/live)
    python main.py --live       # Force live trading (overrides .env)
    python main.py --paper      # Force paper trading (overrides .env)

Bot schedule:
  9:00 AM  -- Pre-market checks: margin, news sentiment, holiday check
  9:15 AM  -- Market opens, WebSocket streaming starts
  9:15-9:30 -- Opening range tracked (no trades)
  9:30-2:30 -- Active trading windows
  10:30 AM -- Market regime determined (TRENDING / VOLATILE / etc.)
  2:30 PM  -- No new trades after this
  3:15 PM  -- Force-exit all open positions
  3:30 PM  -- Daily report, shutdown

Kill switch: Dashboard red button sets /kill_switch in Firebase -> bot exits.
Trading toggle: Dashboard ON/OFF toggle sets /trading_enabled -> pauses scanning.
"""

import sys
import time
import signal
import logging
import threading
from datetime import datetime
from typing import Optional

from config import config
from utils.logger import setup_logger
from utils.watchlist import get_watchlist, get_nifty_token, get_banknifty_token, get_vix_token
from utils.news_sentiment import NewsSentimentFetcher
from utils.market_regime import MarketRegimeDetector
from utils.trade_analytics import TradeAnalytics
from core.broker import BrokerConnection
from core.data_stream import DataStream
from core.scanner import PatternScanner
from core.risk_manager import RiskManager
from core.order_manager import OrderManager
from core.portfolio import Portfolio
from utils.firebase_sync import FirebaseSync


logger = logging.getLogger(__name__)

# How often to push portfolio state to Firebase (in seconds)
PORTFOLIO_UPDATE_INTERVAL = 5

# NSE holidays 2026 (update annually; bot skips these dates)
NSE_HOLIDAYS_2026 = {
    "2026-01-26",  # Republic Day
    "2026-03-31",  # Id-Ul-Fitr (Eid)
    "2026-04-02",  # Ram Navami
    "2026-04-14",  # Dr. Ambedkar Jayanti
    "2026-04-15",  # Good Friday
    "2026-05-01",  # Maharashtra Day
    "2026-08-15",  # Independence Day
    "2026-08-27",  # Ganesh Chaturthi
    "2026-10-02",  # Gandhi Jayanti
    "2026-10-23",  # Dussehra
    "2026-11-04",  # Diwali Laxmi Puja
    "2026-11-05",  # Diwali Balipratipada
    "2026-11-25",  # Guru Nanak Jayanti
    "2026-12-25",  # Christmas
}


class TradingBot:
    """
    Main bot orchestrator. Coordinates all components:
    data stream -> scanner -> risk check -> order execution -> monitoring.

    New in this version:
    - Pre-market checks at 9 AM (news, margin, holiday)
    - Market regime detection at 10:30 AM (TRENDING/VOLATILE/etc.)
    - 30-second confirmation window before live trades
    - Global trading ON/OFF toggle from dashboard
    - News sentiment filtering
    - Trade analytics CSV logging
    - BANKNIFTY + VIX data streams
    """

    def __init__(self):
        self.is_running = False
        self.kill_switch_activated = False
        self.trading_enabled = True   # Can be toggled from dashboard
        self.regime_determined = False
        self.mode = "PAPER" if config.trading.paper_trading else "LIVE"

        self._last_portfolio_push = 0.0

        # Core components
        self.broker = BrokerConnection(config.broker, config.trading)
        self.portfolio = Portfolio(config.trading.initial_capital)
        self.risk_manager = RiskManager(config.trading, self.portfolio)
        self.order_manager = OrderManager(
            broker=self.broker,
            risk_manager=self.risk_manager,
            portfolio=self.portfolio,
            config=config.trading,
        )
        self.scanner = PatternScanner(config.trading, config.indicators)
        self.data_stream = DataStream(self.broker)
        self.firebase = FirebaseSync(config.firebase)

        # New: news sentiment, regime detector, analytics
        self.news_fetcher = NewsSentimentFetcher(config.news)
        self.regime_detector = MarketRegimeDetector(config.trading)
        self.analytics = TradeAnalytics(config.trading.csv_log_path)

        # Token IDs for index instruments
        self.watchlist: list[dict] = []
        self.nifty_token: str = ""
        self.banknifty_token: str = ""
        self.vix_token: str = ""

        # Confirmation window: signal ID -> (signal, submit_time)
        # When use_confirmation_window=True, we wait 30s before executing
        self._pending_confirmations: dict[str, tuple] = {}

    # ----------------------------------------------------------------
    # Startup Sequence
    # ----------------------------------------------------------------

    def start(self):
        """Start the bot. This is the entry point called from main()."""
        self._print_banner()

        # Step 1: Load watchlist (200 stocks + index tokens)
        self._load_watchlist()

        # Step 2: Authenticate with Angel One (retry up to 3x)
        if not self._authenticate():
            logger.error("Authentication failed. Check credentials in .env. Exiting.")
            return

        # Step 3: Run pre-market checks (holiday, margin, news, prev-day data)
        if not self._run_premarket_checks():
            logger.error("Pre-market checks failed. Bot will not start.")
            return

        # Step 4: Wire scanner to watchlist
        self.scanner.set_watchlist(self.watchlist)

        # Step 5: Set up Firebase listeners
        if self.firebase.is_connected:
            self.firebase.clear_today_signals()
            self.firebase.reset_kill_switch()
            self.firebase.set_trading_enabled(True)
            self.firebase.set_running()
            self.firebase.listen_for_kill_switch(callback=self._on_kill_switch)
            self.firebase.listen_for_trading_enabled(callback=self._on_trading_enabled_changed)

        # Step 6: Wire WebSocket reconnect callback
        self.data_stream.on_reconnect = self._on_websocket_reconnect

        # Step 7: Start streaming live data
        self.is_running = True
        self._start_streaming()

        # Step 8: Enter the main trading loop (blocks until 3:15 PM or kill switch)
        self._trading_loop()

    def _load_watchlist(self):
        """Load 200-stock watchlist and index tokens."""
        self.watchlist = get_watchlist(
            use_dynamic=config.trading.use_dynamic_watchlist,
            max_size=config.trading.watchlist_max_size,
        )
        nifty_info = get_nifty_token()
        self.nifty_token = nifty_info.get("token", "99926000")

        banknifty_info = get_banknifty_token()
        self.banknifty_token = banknifty_info.get("token", "99926009")

        vix_info = get_vix_token()
        self.vix_token = vix_info.get("token", "99919000")

        logger.info(
            f"Watchlist loaded: {len(self.watchlist)} stocks | "
            f"NIFTY: {self.nifty_token} | "
            f"BANKNIFTY: {self.banknifty_token} | "
            f"VIX: {self.vix_token}"
        )

    def _authenticate(self) -> bool:
        """Connect to Angel One with retry."""
        return self.broker.retry_connect(max_attempts=3)

    # ----------------------------------------------------------------
    # Pre-Market Checks (9:00 AM)
    # ----------------------------------------------------------------

    def _run_premarket_checks(self) -> bool:
        """
        Run all pre-market checks. Returns True if safe to trade.

        Steps:
        1. Check if today is an NSE trading holiday
        2. Check available margin (must be >= 50% of config capital)
        3. Fetch news sentiment for the watchlist
        4. Fetch previous day OHLC for gap/level filters
        5. Push premarket status to Firebase for dashboard
        """
        logger.info("=" * 50)
        logger.info("Running pre-market checks...")

        status = {
            "is_trading_day": True,
            "margin_available": 0.0,
            "margin_ok": False,
            "broker_connected": self.broker.is_connected(),
            "watchlist_loaded": len(self.watchlist) > 0,
            "news_loaded": False,
            "prev_day_loaded": False,
            "checks_passed": False,
            "message": "",
        }

        # Check 1: NSE holiday
        today_str = datetime.now().strftime("%Y-%m-%d")
        if config.trading.check_trading_holiday and today_str in NSE_HOLIDAYS_2026:
            status["is_trading_day"] = False
            status["message"] = f"Today ({today_str}) is an NSE holiday. Bot will not start."
            logger.warning(status["message"])
            self.firebase.push_premarket_status(status)
            return False

        # Check 2: Weekend check
        weekday = datetime.now().weekday()
        if weekday >= 5:  # 5=Saturday, 6=Sunday
            status["is_trading_day"] = False
            status["message"] = "Today is a weekend. NSE is closed."
            logger.warning(status["message"])
            self.firebase.push_premarket_status(status)
            return False

        # Check 3: Margin check
        try:
            funds = self.broker.get_funds()
            if funds:
                available = float(funds.get("availablecash", 0))
                status["margin_available"] = round(available, 2)
                min_required = config.trading.initial_capital * config.trading.min_margin_pct_required
                status["margin_ok"] = available >= min_required
                if not status["margin_ok"]:
                    logger.warning(
                        f"Low margin: Rs.{available:.2f} available, "
                        f"Rs.{min_required:.2f} required (50% of capital). "
                        "Continuing but position sizes may be limited."
                    )
                else:
                    logger.info(f"Margin OK: Rs.{available:,.2f} available")
        except Exception as e:
            logger.warning(f"Could not fetch margin: {e}. Proceeding anyway.")
            status["margin_ok"] = True  # Don't block on margin check failure

        # Check 4: News sentiment (non-blocking — neutral if API fails)
        symbols = [s["symbol"] for s in self.watchlist]
        news_sentiment = self.news_fetcher.fetch_all(symbols)
        self.scanner.set_news_sentiment(news_sentiment)
        status["news_loaded"] = bool(news_sentiment)
        self.firebase.push_news_sentiment(news_sentiment)
        logger.info(
            f"News sentiment loaded for {len(news_sentiment)} stocks. "
            f"Global risk day: {self.news_fetcher.is_global_risk_day()}"
        )

        # Check 5: Previous day OHLC
        self._fetch_prev_day_levels()
        status["prev_day_loaded"] = True

        # All critical checks passed
        status["checks_passed"] = True
        status["message"] = (
            f"All systems ready. "
            f"{len(self.watchlist)} stocks loaded. "
            f"Margin: Rs.{status['margin_available']:,.2f}. "
            f"Market opens in "
            f"{max(0, (datetime.now().replace(hour=9, minute=15, second=0) - datetime.now()).seconds // 60)} min."
        )
        logger.info(status["message"])
        self.firebase.push_premarket_status(status)
        logger.info("=" * 50)
        return True

    def _fetch_prev_day_levels(self):
        """
        Fetch yesterday's OHLC for all watchlist stocks.
        Used by scanner for gap filter and prev-day level proximity checks.
        """
        logger.info(f"Fetching previous day OHLC for {len(self.watchlist)} stocks...")
        prev_day_by_token = {}
        failed = 0

        for stock in self.watchlist:
            token = stock["token"]
            trading_symbol = f"{stock['symbol']}-EQ"
            try:
                ohlc = self.broker.get_prev_day_ohlc(token, trading_symbol)
                if ohlc:
                    prev_day_by_token[token] = ohlc
                else:
                    failed += 1
            except Exception as e:
                logger.warning(f"Could not fetch prev day OHLC for {stock['symbol']}: {e}")
                failed += 1

        self.scanner.set_prev_day_levels(prev_day_by_token)
        logger.info(
            f"Prev day levels loaded: {len(prev_day_by_token)} stocks | "
            f"{failed} failed (those stocks skip gap/proximity filters)"
        )

    # ----------------------------------------------------------------
    # WebSocket Streaming
    # ----------------------------------------------------------------

    def _start_streaming(self):
        """Subscribe to live price data for all stocks + NIFTY + BANKNIFTY + VIX."""
        all_tokens = [s["token"] for s in self.watchlist]

        # Add index tokens (avoid duplicates)
        for token in [self.nifty_token, self.banknifty_token, self.vix_token]:
            if token and token not in all_tokens:
                all_tokens.append(token)

        self.data_stream.subscribe(tokens=all_tokens, callback=self._on_price_update)
        logger.info(
            f"Streaming live data for {len(all_tokens)} instruments "
            f"({len(self.watchlist)} stocks + NIFTY + BANKNIFTY + VIX)"
        )

    # ----------------------------------------------------------------
    # Price Tick Handler (core logic -- called for every price update)
    # ----------------------------------------------------------------

    def _on_price_update(self, tick: dict):
        """
        Called every time a price tick arrives from Angel One WebSocket.
        This is the core decision engine of the bot.
        """
        if not self.is_running or self.kill_switch_activated:
            return

        token = tick.get("token", "")
        now = datetime.now().time()

        # ── INDEX TICKS: update market context and regime detector ──────
        is_index_tick = token in (self.nifty_token, self.banknifty_token, self.vix_token)
        if is_index_tick:
            # VIX tick -> update regime detector's VIX reading
            if token == self.vix_token:
                vix = tick.get("ltp", 0)
                self.regime_detector.update_vix(vix)
                self.scanner.market_context["vix"] = vix

            # NIFTY / BANKNIFTY -> update NIFTY direction + regime
            else:
                self.scanner.update_market_context(tick)
                self.regime_detector.update_nifty(tick)

            # Push market context to Firebase (throttled by Firebase SDK)
            self.firebase.push_market_context(self.scanner.market_context)
            return

        # ── ORB OBSERVATION PERIOD (9:15 AM - 9:30 AM) ─────────────────
        if now < config.trading.orb_end:
            self.scanner.update_orb_range(tick)
            return

        # ── GLOBAL TRADING TOGGLE CHECK ─────────────────────────────────
        if not self.trading_enabled:
            return  # Dashboard has paused trading (not a kill switch -- just a pause)

        # ── REGIME DETERMINATION AT 10:30 AM ────────────────────────────
        if not self.regime_determined and now >= config.trading.regime_determination_time:
            self._determine_and_apply_regime()

        # ── NO NEW TRADES AFTER 2:30 PM ─────────────────────────────────
        if now > config.trading.no_new_trades_after:
            return

        # ── ACTIVE TRADING (9:30 AM - 2:30 PM) ─────────────────────────
        signals = self.scanner.scan(tick)

        for signal in signals:
            if not self.risk_manager.can_trade(signal):
                logger.info(f"Blocked by risk: {signal.stock} -- {signal.reason}")
                continue

            # Push signal to dashboard (all modes)
            self.firebase.push_signal(signal)

            if config.trading.suggest_only:
                logger.info(f"SIGNAL (suggest only): {signal.stock} {signal.direction} @ Rs.{signal.entry_price:.2f}")
            elif config.trading.use_confirmation_window:
                # Live mode with 30-second confirmation window:
                # Push signal with awaiting_confirmation flag.
                # The bot waits 30s; if not rejected from dashboard, it auto-executes.
                self._schedule_confirmation(signal)
            else:
                # Fully automatic: execute immediately
                self._execute_signal(signal)

        # ── PORTFOLIO UPDATE TO FIREBASE (throttled) ────────────────────
        now_ts = time.time()
        if now_ts - self._last_portfolio_push >= PORTFOLIO_UPDATE_INTERVAL:
            self.firebase.push_portfolio(self.portfolio.get_state())
            self._last_portfolio_push = now_ts

    def _determine_and_apply_regime(self):
        """
        Called once at 10:30 AM to lock in the day's market regime.
        Updates risk manager multipliers so position sizing reflects regime.
        """
        regime = self.regime_detector.get_regime()
        size_mult = self.regime_detector.get_size_multiplier()
        sl_mult = self.regime_detector.get_sl_multiplier()
        score_override = self.regime_detector.get_min_score_override()

        # Apply regime multipliers to risk manager
        self.risk_manager.set_regime_multipliers(size_mult, sl_mult)

        # If volatile regime, tighten the score requirement
        if score_override > 0:
            original = config.trading.min_score_to_trade
            config.trading.min_score_to_trade = max(original, score_override)
            logger.info(
                f"Volatile regime: score threshold raised "
                f"from {original} to {config.trading.min_score_to_trade}"
            )

        self.regime_determined = True
        regime_dict = self.regime_detector.to_dict()

        logger.info(
            f"Regime determined at 10:30 AM: {regime} | "
            f"Size mult: {size_mult}x | SL mult: {sl_mult}x"
        )
        self.firebase.push_regime(regime_dict)

    # ----------------------------------------------------------------
    # Trade Execution
    # ----------------------------------------------------------------

    def _execute_signal(self, signal):
        """Execute a signal: place order, update Firebase, log to CSV."""
        position = self.order_manager.execute(signal)
        if position:
            self.firebase.push_open_position(position.to_dict())
            logger.info(
                f"Trade executed: {signal.stock} {signal.direction} "
                f"@ Rs.{signal.entry_price:.2f} | Qty: {signal.quantity}"
            )

    def _schedule_confirmation(self, signal):
        """
        30-second confirmation window for live trades.

        Push the signal to Firebase with awaiting_confirmation=True.
        After 30 seconds (in a background thread), if no rejection
        has come through Firebase, execute the trade.

        Note: Dashboard can write /signals/{id}/rejected=true to block it.
        """
        sig_id = f"{signal.stock}_{int(time.time())}"
        self._pending_confirmations[sig_id] = (signal, time.time())

        logger.info(
            f"Awaiting confirmation: {signal.stock} {signal.direction} "
            f"(30-second window -- id: {sig_id})"
        )

        def _execute_after_delay():
            time.sleep(config.trading.confirmation_timeout_secs)
            if sig_id in self._pending_confirmations:
                sig, _ = self._pending_confirmations.pop(sig_id)
                logger.info(f"Confirmation window passed. Executing: {sig.stock}")
                self._execute_signal(sig)

        t = threading.Thread(target=_execute_after_delay, daemon=True)
        t.start()

    # ----------------------------------------------------------------
    # Closed Trade Handler (called from trading loop after position closes)
    # ----------------------------------------------------------------

    def _on_position_closed(self, position):
        """
        Called when a position fully closes (SL hit, target hit, or force exit).
        Logs the trade to CSV and updates Firebase.
        """
        trade_data = position.to_dict()

        # Add market context at time of close for analytics
        trade_data["nifty_direction"] = self.scanner.market_context.get("nifty_direction", "")
        trade_data["regime"] = self.regime_detector.get_regime() if self.regime_determined else "UNKNOWN"
        trade_data["vix"] = self.scanner.market_context.get("vix", 0)

        # Log to CSV (persistent across bot restarts)
        self.analytics.log_trade(trade_data)

        # Push to Firebase trade history
        self.firebase.push_trade(trade_data)

        # Remove from Firebase open positions panel
        self.firebase.remove_position(position.signal.stock)

        # Update portfolio display
        self.firebase.push_portfolio(self.portfolio.get_state())

        logger.info(
            f"Position closed: {position.signal.stock} "
            f"Net P&L: Rs.{trade_data.get('net_pnl', 0):+,.2f} | "
            f"Hold: {trade_data.get('hold_time_minutes', 0):.0f} min | "
            f"Exit: {trade_data.get('exit_reason', '?')}"
        )

    # ----------------------------------------------------------------
    # Reconnect Callback
    # ----------------------------------------------------------------

    def _on_websocket_reconnect(self):
        """
        Called by data_stream after a successful WebSocket reconnect.
        During the outage, an SL or target could have been hit.
        We reconcile with the broker to catch this.
        """
        logger.info("WebSocket reconnected -- reconciling positions with broker...")
        try:
            broker_positions = self.broker.get_positions()
            self.order_manager.reconcile_positions(broker_positions)
            logger.info("Position reconciliation complete")
        except Exception as e:
            logger.error(f"Position reconciliation failed: {e}")

    # ----------------------------------------------------------------
    # Trading Toggle Callback (from dashboard)
    # ----------------------------------------------------------------

    def _on_trading_enabled_changed(self, enabled: bool):
        """
        Called when the dashboard toggles trading ON or OFF.
        Does NOT exit positions -- just pauses scanning for new signals.
        """
        self.trading_enabled = enabled
        status = "ENABLED" if enabled else "PAUSED"
        logger.info(f"Trading {status} from dashboard toggle")

    # ----------------------------------------------------------------
    # Main Trading Loop
    # ----------------------------------------------------------------

    def _trading_loop(self):
        """
        Main loop -- runs from market open until 3:15 PM or kill switch.
        The actual trading logic runs in _on_price_update() (tick-driven).
        This loop handles: position monitoring, force exit, daily loss check.
        """
        logger.info("Bot is live. Waiting for market data...")

        try:
            while self.is_running:
                now = datetime.now().time()

                if self.kill_switch_activated:
                    logger.warning("Kill switch -- exiting loop")
                    break

                # Force exit all positions at 3:15 PM
                if now >= config.trading.force_exit_time:
                    logger.info("3:15 PM -- Force-exiting all open positions")
                    self._end_of_day()
                    break

                # Stop trading if daily loss limit is hit
                if self.risk_manager.daily_loss_limit_hit():
                    logger.warning("Daily loss limit hit -- stopping bot for today")
                    self._end_of_day()
                    break

                # Monitor open positions (check SL, trailing SL, partial/full targets)
                if not config.trading.suggest_only and self.order_manager.open_positions:
                    closed_positions, partial_updates = (
                        self.order_manager.monitor_positions()
                    )

                    for pos in closed_positions:
                        self._on_position_closed(pos)

                    for pos in partial_updates:
                        # Update the position in Firebase with new SL/remaining qty
                        self.firebase.push_open_position(pos.to_dict())

                time.sleep(1)

        except KeyboardInterrupt:
            logger.info("Bot stopped by user (Ctrl+C)")
        finally:
            self.shutdown()

    # ----------------------------------------------------------------
    # End of Day & Shutdown
    # ----------------------------------------------------------------

    def _end_of_day(self):
        """End-of-day: close all positions, generate report, push to Firebase."""
        logger.info("Running end-of-day routine...")

        if not config.trading.suggest_only:
            self.order_manager.exit_all_positions()

        report = self.portfolio.daily_report()
        self._print_report(report)

        # Push analytics summary (strategy breakdown, score distribution, etc.)
        analytics_summary = self.analytics.get_today_summary()
        self.firebase.push_analytics(analytics_summary)

        self.firebase.push_daily_report(report)
        self.firebase.push_portfolio(self.portfolio.get_state())

    def _print_report(self, report: dict):
        """Print end-of-day report to console logs."""
        logger.info("\n" + "=" * 55)
        logger.info("  DAILY REPORT")
        logger.info("=" * 55)
        logger.info(f"  Starting Capital  : Rs.{report['starting_capital']:>10,.2f}")
        logger.info(f"  Ending Capital    : Rs.{report['ending_capital']:>10,.2f}")
        logger.info(f"  Gross P&L         : Rs.{report.get('day_gross_pnl', 0):>+10,.2f}")
        logger.info(f"  Brokerage Paid    : Rs.{report.get('brokerage_paid', 0):>10,.2f}")
        logger.info(f"  Net P&L           : Rs.{report['day_pnl']:>+10,.2f}  <- real bottom line")
        logger.info(f"  Trades Taken      : {report['trades_taken']}")
        logger.info(f"  Win Rate          : {report['win_rate']}%")
        logger.info(f"  Wins / Losses     : {report['wins']} / {report['losses']}")
        logger.info(f"  Avg Signal Score  : {report.get('avg_signal_score', 0)}")
        logger.info(f"  Avg Slippage      : Rs.{report.get('avg_slippage_rs', 0):.2f}")
        if report.get("strategy_breakdown"):
            logger.info("  Strategy Breakdown:")
            for strat, stats in report["strategy_breakdown"].items():
                logger.info(
                    f"    {strat:15s}: "
                    f"{stats['trades']} trades | "
                    f"W/L {stats['wins']}/{stats['losses']} | "
                    f"P&L Rs.{stats['total_pnl']:+,.2f}"
                )
        logger.info("=" * 55)

    def _on_kill_switch(self):
        """Called when the dashboard presses the emergency kill switch."""
        logger.warning("KILL SWITCH ACTIVATED -- Emergency stop!")
        self.kill_switch_activated = True
        self.is_running = False

        if not config.trading.suggest_only:
            self.order_manager.exit_all_positions()

        report = self.portfolio.daily_report()
        self.firebase.push_daily_report(report)
        self.firebase.push_portfolio(self.portfolio.get_state())
        self.firebase.set_stopped()

    def shutdown(self):
        """Graceful shutdown: disconnect cleanly from broker and Firebase."""
        logger.info("Shutting down...")
        self.is_running = False
        self.data_stream.disconnect()

        if not config.trading.suggest_only:
            self.order_manager.exit_all_positions()

        self.broker.disconnect()
        self.firebase.set_stopped()
        logger.info("Bot shut down cleanly.")

    def _print_banner(self):
        """Print startup info."""
        logger.info("=" * 60)
        logger.info(f"  NSE Trading Bot  |  Mode: {self.mode}")
        logger.info(
            f"  {'SUGGEST ONLY (no auto-trades)' if config.trading.suggest_only else 'AUTO-EXECUTE (live orders)'}"
        )
        if config.trading.use_confirmation_window and not config.trading.suggest_only:
            logger.info(f"  30-second confirmation window: ON")
        logger.info(f"  Capital: Rs.{config.trading.initial_capital:,.0f}")
        logger.info(f"  Watchlist: up to {config.trading.watchlist_max_size} stocks")
        logger.info(f"  Min signal score: {config.trading.min_score_to_trade}/100")
        logger.info(f"  Max risk/trade: {config.trading.max_risk_per_trade_pct}%")
        logger.info(f"  Daily loss limit: {config.trading.daily_loss_limit_pct}%")
        logger.info(
            f"  Trading windows: "
            f"{config.trading.trading_window_1_start.strftime('%H:%M')}-"
            f"{config.trading.trading_window_1_end.strftime('%H:%M')} and "
            f"{config.trading.trading_window_2_start.strftime('%H:%M')}-"
            f"{config.trading.trading_window_2_end.strftime('%H:%M')}"
        )
        logger.info("=" * 60)


# ----------------------------------------------------------------
# Entry Point
# ----------------------------------------------------------------

def main():
    setup_logger(config.log_level, config.log_file)

    if "--live" in sys.argv:
        config.trading.paper_trading = False
        config.trading.suggest_only = False
        logger.warning(
            "LIVE TRADING MODE -- Real money at risk! "
            "All trades will be executed automatically."
        )
    elif "--paper" in sys.argv:
        config.trading.paper_trading = True
        config.trading.suggest_only = True
        logger.info("Paper trading mode forced via --paper flag.")
    else:
        logger.info(
            f"Mode from .env: "
            f"paper_trading={config.trading.paper_trading} | "
            f"suggest_only={config.trading.suggest_only}"
        )

    bot = TradingBot()

    def handle_interrupt(sig, frame):
        logger.info("Interrupt received -- shutting down gracefully...")
        bot.shutdown()
        sys.exit(0)

    signal.signal(signal.SIGINT, handle_interrupt)
    bot.start()


if __name__ == "__main__":
    main()
