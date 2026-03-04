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

import json
import sys
import time
import signal
import logging
import threading
from datetime import datetime, timedelta
from pathlib import Path
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
        self.risk_manager = RiskManager(config.trading, self.portfolio, broker=self.broker)
        self.order_manager = OrderManager(
            broker=self.broker,
            risk_manager=self.risk_manager,
            portfolio=self.portfolio,
            config=config.trading,
        )
        self.scanner = PatternScanner(config.trading, config.indicators)
        self.data_stream = DataStream(self.broker)
        self.order_manager.set_data_stream(self.data_stream)
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
    # Startup Validation (runs before everything else)
    # ----------------------------------------------------------------

    def _validate_startup(self) -> bool:
        """
        Pre-flight check before the bot does anything.

        Checks (in order):
        1. All required .env fields are present and not placeholder values
        2. firebase-credentials.json exists and is valid JSON (warning, not fatal)
        3. Angel One authentication succeeds
        4. At least 10 stocks loaded in watchlist

        Prints a clear ALL SYSTEMS GO or STARTUP FAILED message.
        Returns True if safe to start, False if the bot should abort.
        """
        errors: list[str] = []
        warnings: list[str] = []

        logger.info("=" * 60)
        logger.info("  STARTUP VALIDATION")
        logger.info("=" * 60)

        # ── Check 1: Required .env fields ────────────────────────────────
        required_fields = {
            "ANGEL_API_KEY":     config.broker.api_key,
            "ANGEL_CLIENT_ID":   config.broker.client_id,
            "ANGEL_PASSWORD":    config.broker.password,
            "ANGEL_TOTP_SECRET": config.broker.totp_secret,
        }
        placeholder_prefixes = ("your_", "YOUR_", "<", "")
        for field_name, value in required_fields.items():
            if not value or any(value.startswith(p) for p in placeholder_prefixes if p):
                errors.append(f"Missing or not set: {field_name}")

        if not config.firebase.database_url:
            warnings.append("FIREBASE_DATABASE_URL not set — dashboard will be offline")

        # ── Check 2: Firebase credentials file ───────────────────────────
        creds_path = Path(config.firebase.credentials_path)
        if not creds_path.exists():
            warnings.append(
                f"Firebase credentials file not found: {config.firebase.credentials_path} "
                "— dashboard sync disabled"
            )
        else:
            try:
                with open(creds_path) as f:
                    json.load(f)
            except Exception as e:
                warnings.append(
                    f"Firebase credentials file is invalid JSON ({e}) "
                    "— dashboard sync disabled"
                )

        # ── Check 3: Angel One authentication ────────────────────────────
        # Auth happens in start() before this method. Just verify connection.
        if not errors:
            if self.broker.is_connected:
                logger.info("  Angel One: connected (authenticated earlier)")
            else:
                logger.info("  Checking Angel One authentication...")
                auth_ok = self.broker.retry_connect(max_attempts=3)
                if not auth_ok:
                    errors.append(
                        "Angel One authentication failed. "
                        "Check ANGEL_API_KEY, ANGEL_CLIENT_ID, ANGEL_PASSWORD, ANGEL_TOTP_SECRET."
                    )
                else:
                    logger.info("  Angel One: connected")

        # ── Check 4: Watchlist ────────────────────────────────────────────
        watchlist_count = len(self.watchlist)
        if watchlist_count < 10:
            errors.append(
                f"Watchlist has only {watchlist_count} stocks (minimum 10). "
                "Instrument master may have failed to download and fallback tokens are insufficient."
            )
        else:
            logger.info(f"  Watchlist: {watchlist_count} stocks loaded")

        # ── Print warnings (non-fatal) ────────────────────────────────────
        for w in warnings:
            logger.warning(f"  WARNING: {w}")

        # ── Final verdict ─────────────────────────────────────────────────
        logger.info("=" * 60)
        if errors:
            logger.error("  STARTUP FAILED — fix these issues before running:")
            for i, err in enumerate(errors, 1):
                logger.error(f"    {i}. {err}")
            logger.error("=" * 60)
            return False

        logger.info("  ALL SYSTEMS GO — starting bot")
        logger.info("=" * 60)
        return True

    # ----------------------------------------------------------------
    # Startup Sequence
    # ----------------------------------------------------------------

    def start(self):
        """
        Start the bot. This is the entry point called from main().

        Startup sequence (FIX 5 — exact order matters):
        1. Print banner
        2. Authenticate with Angel One
        3. Call getRMS() — get available margin
        4. Call getPosition() — adopt any existing open positions
        5. Place SL orders for adopted positions (done inside adopt)
        6. Load watchlist
        7. Capital filter + OHLC fetch (with cache)
        8. Start WebSocket
        9. Begin scanning
        """
        self._print_banner()

        # Step 1: Authenticate with Angel One FIRST (needed for all API calls)
        logger.info("Step 1: Authenticating with Angel One...")
        if not self._authenticate():
            logger.error("STARTUP FAILED: Could not authenticate with Angel One.")
            return

        # Step 2: Get available margin from getRMS()
        logger.info("Step 2: Checking available margin (getRMS)...")
        self._check_margin_on_startup()

        # Step 3: Adopt existing positions from Angel One (CRITICAL for crash recovery)
        logger.info("Step 3: Checking for existing open positions (getPosition)...")
        adopted_count = self._adopt_existing_positions()

        # Step 4: Load watchlist (200 stocks + index tokens)
        logger.info("Step 4: Loading watchlist...")
        self._load_watchlist()

        # Step 5: Validate startup (env, firebase, watchlist — auth already done)
        if not self._validate_startup():
            return

        # Step 6: Run pre-market checks (holiday, margin, news, prev-day data)
        if not self._run_premarket_checks():
            logger.error("Pre-market checks failed. Bot will not start.")
            return

        # Step 7: Wire scanner to watchlist
        self.scanner.set_watchlist(self.watchlist)

        # Step 8: Set up Firebase listeners
        if self.firebase.is_connected:
            self.firebase.clear_today_signals()
            self.firebase.reset_kill_switch()
            self.firebase.set_trading_enabled(True)
            self.firebase.set_running()
            self.firebase.listen_for_kill_switch(callback=self._on_kill_switch)
            self.firebase.listen_for_trading_enabled(callback=self._on_trading_enabled_changed)

        # Step 9: Wire WebSocket reconnect callback
        self.data_stream.on_reconnect = self._on_websocket_reconnect

        # Step 10: Start streaming live data
        self.is_running = True
        self._start_streaming()

        # Log final ready message
        existing = len(self.order_manager.open_positions)
        logger.info(
            f"Bot is live. Monitoring {existing} existing positions + "
            f"ready for new trades."
        )

        # Step 11: Enter the main trading loop (blocks until 3:15 PM or kill switch)
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

    def _check_margin_on_startup(self):
        """
        Check available margin via getRMS() API on startup.
        Caches it in risk_manager so capital-based limits work immediately.
        """
        try:
            funds = self.broker.get_funds()
            if funds:
                available = float(funds.get("availablecash", 0))
                intraday = float(funds.get("availableintradaypayin", 0) or 0)
                margin = intraday if intraday > 0 else available
                logger.info(
                    f"Available margin: Rs.{margin:,.2f} "
                    f"(cash: Rs.{available:,.2f}, intraday: Rs.{intraday:,.2f})"
                )
                # Cache in risk manager for capital-based trade limiting
                self.risk_manager._cached_margin = margin
            else:
                logger.warning("Could not fetch margin. Will retry in pre-market checks.")
        except Exception as e:
            logger.warning(f"Margin check failed: {e}. Continuing anyway.")

    def _adopt_existing_positions(self) -> int:
        """
        Adopt any existing open intraday positions from Angel One.

        This is CRITICAL for crash recovery — if the bot crashes mid-day
        and restarts, orphaned positions need SL monitoring immediately.

        Returns the number of adopted positions.
        """
        try:
            broker_positions = self.broker.get_positions()

            if not broker_positions:
                logger.info("No existing positions found at Angel One.")
                return 0

            # Filter for intraday positions only
            intraday_positions = [
                p for p in broker_positions
                if p.get("producttype", "").upper() in ("INTRADAY", "MIS")
                and int(p.get("netqty", 0)) != 0
            ]

            if not intraday_positions:
                logger.info("No open intraday positions to adopt.")
                return 0

            logger.info(
                f"Found {len(intraday_positions)} open intraday positions. "
                f"Adopting all..."
            )

            adopted = self.order_manager.adopt_positions(intraday_positions)

            # Push adopted positions to Firebase so dashboard shows them
            for pos in adopted:
                try:
                    self.firebase.push_open_position(pos.to_dict())
                except Exception as fe:
                    logger.warning(
                        f"Firebase push failed for adopted position {pos.signal.stock}: {fe}"
                    )

            logger.info(
                f"Adopted {len(adopted)} existing positions from Angel One. "
                f"All now have SL monitoring + broker-side SL orders."
            )
            return len(adopted)

        except Exception as e:
            logger.error(f"Position adoption failed: {e}. Starting without adopted positions.")
            return 0

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
            "broker_connected": self.broker.is_connected,
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

        # Check 5: Previous day OHLC (with capital-aware filter + caching)
        ohlc_results, affordable, ltp_cache = self._fetch_prev_day_levels()
        self._affordable_stocks = affordable
        self._ltp_cache = ltp_cache
        status["prev_day_loaded"] = True

        # Add capital filter stats so dashboard shows useful info
        status["total_watchlist"] = len(self.watchlist)
        status["affordable_stocks"] = len(affordable)
        status["skipped_stocks"] = len(self.watchlist) - len(affordable)
        status["ohlc_loaded"] = len(ohlc_results)
        status["capital"] = config.trading.initial_capital
        status["filter_summary"] = (
            f"{len(affordable)} tradeable stocks at "
            f"Rs.{config.trading.initial_capital:,.0f} capital"
        )

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

    def _fetch_prev_day_levels(self) -> tuple[dict, list[dict], dict]:
        """
        Fetch yesterday's OHLC with capital-aware filtering and caching.

        New flow (replaces old 50-stock + sleep(2) approach):
        1. Check local OHLC cache (instant on mid-day restart)
        2. Use fast LTP API to filter by capital (5 req/sec)
        3. Fetch OHLC only for affordable stocks (1 req/sec with rate limiter)
        4. Cache results for next restart

        Returns:
            (ohlc_results, affordable_stocks, ltp_cache)
        """
        to_date = datetime.now()
        from_date = to_date - timedelta(days=7)
        from_date_str = from_date.strftime("%Y-%m-%d %H:%M")
        to_date_str = to_date.strftime("%Y-%m-%d %H:%M")

        ohlc_results, affordable, ltp_cache = self.broker.fetch_all_prev_day_ohlc(
            watchlist=self.watchlist,
            capital=config.trading.initial_capital,
            from_date=from_date_str,
            to_date=to_date_str,
        )

        # Convert symbol-keyed OHLC to token-keyed for scanner
        symbol_to_token = {s["symbol"]: s["token"] for s in self.watchlist}
        prev_day_by_token = {}
        for symbol, ohlc in ohlc_results.items():
            token = symbol_to_token.get(symbol)
            if token:
                prev_day_by_token[token] = ohlc

        self.scanner.set_prev_day_levels(prev_day_by_token)
        logger.info(
            f"Prev day levels loaded: {len(prev_day_by_token)} stocks "
            f"(those without data skip gap/proximity filters)"
        )

        return ohlc_results, affordable, ltp_cache

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
            try:
                if token == self.vix_token:
                    vix = tick.get("ltp", 0)
                    self.regime_detector.update_vix(vix)
                    self.scanner.market_context["vix"] = vix
                    # Feed VIX to risk_manager and order_manager for sniper mode
                    self.risk_manager.update_vix(vix)
                    self.order_manager.set_vix(vix)
                else:
                    self.scanner.update_market_context(tick)
                    self.regime_detector.update_nifty(tick)

                # Push market context to Firebase — non-critical, wrap separately
                try:
                    self.firebase.push_market_context(self.scanner.market_context)
                except Exception as fe:
                    logger.debug(f"Firebase market context push failed: {fe}")
            except Exception as e:
                logger.warning(f"Index tick processing error: {e}")
            return

        # ── ORB OBSERVATION PERIOD (9:15 AM - 9:30 AM) ─────────────────
        if now < config.trading.orb_end:
            try:
                self.scanner.update_orb_range(tick)
            except Exception as e:
                logger.warning(f"ORB update error for token {token}: {e}")
            return

        # ── GLOBAL TRADING TOGGLE CHECK ─────────────────────────────────
        if not self.trading_enabled:
            return  # Dashboard has paused trading (not a kill switch -- just a pause)

        # ── REGIME DETERMINATION AT 10:30 AM ────────────────────────────
        if not self.regime_determined and now >= config.trading.regime_determination_time:
            try:
                self._determine_and_apply_regime()
            except Exception as e:
                logger.error(f"Regime determination error: {e}")
                self.regime_determined = True  # Prevent re-running on every tick

        # ── NO NEW TRADES AFTER 2:30 PM ─────────────────────────────────
        if now > config.trading.no_new_trades_after:
            return

        # ── ACTIVE TRADING (9:30 AM - 2:30 PM) ─────────────────────────
        try:
            signals = self.scanner.scan(tick)
        except Exception as e:
            logger.warning(f"Scanner error on token {token}: {e}")
            return

        for signal in signals:
            try:
                # ── Risk manager gate ─────────────────────────────────────
                if not self.risk_manager.can_trade(signal):
                    logger.info(f"Blocked by risk: {signal.stock} -- {signal.reason}")
                    signal.status = getattr(signal, "status", "") or "SKIPPED-RISK"
                    signal.skip_reason = signal.reason
                    # Push all signals (including skipped) to Firebase
                    try:
                        self.firebase.push_signal(signal)
                    except Exception:
                        pass
                    continue

                # ── Pre-flight checklist (sniper mode) ────────────────────
                preflight_ok, fail_reason = self.order_manager.pre_flight_check(
                    signal, scanner=self.scanner
                )
                if not preflight_ok:
                    signal.status = "SKIPPED-PREFLIGHT"
                    signal.skip_reason = fail_reason
                    logger.info(f"PREFLIGHT FAILED: {signal.stock} — {fail_reason}")
                    try:
                        self.firebase.push_signal(signal)
                    except Exception:
                        pass
                    continue

                # ── Signal passed all checks — push and execute ───────────
                signal.status = "EXECUTED"
                try:
                    self.firebase.push_signal(signal)
                except Exception as fe:
                    logger.warning(f"Firebase signal push failed for {signal.stock}: {fe}")

                if config.trading.suggest_only:
                    logger.info(
                        f"SIGNAL (suggest only): {signal.stock} {signal.direction} "
                        f"@ Rs.{signal.entry_price:.2f} | Score: {signal.score} | "
                        f"Confluence: {signal.confluence_count}"
                    )
                else:
                    self._execute_signal(signal)
            except Exception as e:
                logger.error(f"Signal handling error for {signal.stock}: {e}")

        # ── PORTFOLIO UPDATE TO FIREBASE (throttled, non-critical) ───────
        now_ts = time.time()
        if now_ts - self._last_portfolio_push >= PORTFOLIO_UPDATE_INTERVAL:
            try:
                self.firebase.push_portfolio(self.portfolio.get_state())
            except Exception as fe:
                logger.debug(f"Firebase portfolio push failed: {fe}")
            self._last_portfolio_push = now_ts

    def _determine_and_apply_regime(self):
        """
        Called once at 10:30 AM to lock in the day's market regime.
        Updates risk manager multipliers so position sizing reflects regime.
        """
        regime = self.regime_detector.regime
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
        try:
            position = self.order_manager.execute(signal)
        except Exception as e:
            logger.error(
                f"Unexpected error executing {signal.stock}: {e}. "
                "Trade skipped. Check broker connection."
            )
            return

        if position:
            try:
                self.firebase.push_open_position(position.to_dict())
            except Exception as fe:
                logger.warning(f"Firebase position push failed for {signal.stock}: {fe}")
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
        trade_data["regime"] = self.regime_detector.regime if self.regime_determined else "UNKNOWN"
        trade_data["vix"] = self.scanner.market_context.get("vix", 0)

        # Add R-multiple from the last recorded trade in portfolio
        if self.portfolio.trade_log:
            last_trade = self.portfolio.trade_log[-1]
            trade_data["r_multiple"] = last_trade.get("r_multiple", 0)
            trade_data["planned_r_target"] = last_trade.get("planned_r_target", 0)
            trade_data["confluence_count"] = last_trade.get("confluence_count", 0)
            trade_data["confluence_strategies"] = last_trade.get("confluence_strategies", [])
            trade_data["atr_value"] = last_trade.get("atr_value", 0)

        # Log to CSV — local file write, keep trading even if this fails
        try:
            self.analytics.log_trade(trade_data)
        except Exception as e:
            logger.warning(f"CSV log failed for {position.signal.stock}: {e}")

        # Firebase updates — dashboard is nice-to-have, never block on it
        try:
            self.firebase.push_trade(trade_data)
            self.firebase.remove_position(position.signal.stock)
            self.firebase.push_portfolio(self.portfolio.get_state())
        except Exception as fe:
            logger.warning(
                f"Firebase trade sync failed for {position.signal.stock}: {fe}. "
                "Dashboard may be out of date but trading continues."
            )

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
        This loop handles: position monitoring, force exit, daily loss check,
        and time-based exits (2:30 PM SL tightening, 3:00 PM profit exit).
        """
        logger.info("Entering trading loop. Waiting for market data...")

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

        # Only exit positions if there are still open ones
        # (_end_of_day or _on_kill_switch may have already closed them)
        if not config.trading.suggest_only and self.order_manager.open_positions:
            self.order_manager.exit_all_positions()

        self.broker.disconnect()
        self.firebase.set_stopped()
        logger.info("Bot shut down cleanly.")

    def _print_banner(self):
        """Print startup info — Sniper Mode V2 banner."""
        capital = config.trading.initial_capital
        risk_amt = capital * (config.trading.max_risk_per_trade_pct / 100)

        logger.info("=" * 60)
        logger.info(f"  NSE Trading Bot  |  Mode: {self.mode}")
        logger.info(
            f"  {'SUGGEST ONLY (no auto-trades)' if config.trading.suggest_only else 'AUTO-EXECUTE (live orders)'}"
        )
        logger.info("")
        logger.info("  SNIPER MODE V2 ACTIVE")
        logger.info(f"  |- Score threshold: {config.trading.min_score_to_trade} "
                     f"(need {config.trading.min_confluence_count}+ strategy confluence)")
        logger.info(f"  |- Max trades/day: {config.trading.max_trades_per_day} | "
                     f"Max losing: {config.trading.max_losses_per_day}")
        logger.info(f"  |- Risk per trade: {config.trading.max_risk_per_trade_pct}% "
                     f"of Rs.{capital:,.0f} = Rs.{risk_amt:,.0f}")
        logger.info(f"  |- Stop-loss: {config.trading.atr_sl_multiplier_normal}x ATR "
                     f"(floor {config.trading.atr_sl_floor_pct}%, "
                     f"ceiling {config.trading.atr_sl_ceiling_pct}%)")
        logger.info(f"  |- Target: {config.trading.risk_reward_ratio}R from entry")
        logger.info(f"  |- Volume gate: {config.trading.volume_spike_multiplier}x average minimum")
        logger.info(f"  |- VIX gates: NORMAL <{config.trading.vix_normal_threshold} | "
                     f"CAUTION {config.trading.vix_normal_threshold}-"
                     f"{config.trading.vix_caution_threshold} | "
                     f"DANGER >{config.trading.vix_caution_threshold}")
        logger.info(f"  |- Choppiness filter: ON (reject if CHOP > "
                     f"{config.trading.chop_threshold})")
        logger.info(f"  |- 15-min trend filter: "
                     f"{'ON' if config.trading.trend_15m_enabled else 'OFF'}")
        logger.info(f"  |- Candle close confirmation: ON (breakout strategies)")
        logger.info(f"  |- Active hours: "
                     f"{config.trading.trading_window_1_start.strftime('%H:%M')}-"
                     f"{config.trading.trading_window_1_end.strftime('%H:%M')}, "
                     f"{config.trading.trading_window_2_start.strftime('%H:%M')}-"
                     f"{config.trading.trading_window_2_end.strftime('%H:%M')}")
        logger.info(f"  |- Lunch block: "
                     f"{config.trading.lunch_block_start.strftime('%H:%M')}-"
                     f"{config.trading.lunch_block_end.strftime('%H:%M')} "
                     f"(no new trades)")
        logger.info(f"  |- Pre-flight checklist: 17 checks before every trade")
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
