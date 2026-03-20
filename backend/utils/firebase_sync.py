"""
Firebase Sync -- Pushes live trading data to the dashboard.
============================================================
The dashboard (GitHub Pages) reads from Firebase Realtime DB in real-time.
This module WRITES data that the dashboard then READS.

Firebase Realtime Database structure:
/signals/{auto_id}         -- New trading signals (scored 70+)
/trades/{auto_id}          -- Executed trades (with gross/net P&L + charges)
/portfolio                 -- Current capital and P&L (updated every ~5 seconds)
/positions/{stock}         -- Open positions with live P&L + trailing SL
/reports/{date}            -- End-of-day summary reports
/status                    -- Bot status (running, stopped, kill_switch_active)
/kill_switch               -- Dashboard writes here to trigger emergency stop
/trading_enabled           -- Global ON/OFF toggle (dashboard writes, bot reads)
/market_context            -- NIFTY direction + VIX for the dashboard
/regime                    -- Market regime (TRENDING / VOLATILE / etc.)
/news_sentiment            -- Per-stock news sentiment summary
/analytics                 -- Running performance analytics
/premarket_status          -- Pre-market checks result (margin OK, holiday, etc.)
"""

import logging
from datetime import datetime
from typing import Optional

# Firebase Admin SDK — the server-side Firebase library
import firebase_admin
from firebase_admin import credentials, db

logger = logging.getLogger(__name__)

# Track whether Firebase has been initialized (can only init once per process)
_firebase_app: Optional[firebase_admin.App] = None


class FirebaseSync:
    """
    Pushes live trading data to Firebase Realtime Database.

    The dashboard reads these paths in real-time using Firebase's
    onValue() listeners — it updates the second we write here.
    """

    def __init__(self, firebase_config):
        self.config = firebase_config
        self.is_connected = False
        self._initialize()

    def _initialize(self):
        """
        Connect to Firebase using the service account credentials JSON file.

        The credentials file (firebase-credentials.json) is downloaded from:
        Firebase Console → Project Settings → Service Accounts → Generate New Private Key
        """
        global _firebase_app

        try:
            # Only initialize once — Firebase throws if you call initialize_app() twice
            if _firebase_app is not None:
                self.is_connected = True
                logger.info("Firebase already initialized, reusing connection")
                return

            # Validate config
            if not self.config.database_url:
                logger.error("FIREBASE_DATABASE_URL is missing from .env file")
                return

            if not self.config.credentials_path:
                logger.error("FIREBASE_CREDENTIALS_PATH is missing from .env file")
                return

            # Load the service account credentials
            cred = credentials.Certificate(self.config.credentials_path)

            # Initialize Firebase with database URL
            _firebase_app = firebase_admin.initialize_app(cred, {
                "databaseURL": self.config.database_url
            })

            self.is_connected = True
            logger.info(f"Connected to Firebase: {self.config.database_url}")

            # Write initial bot status
            self._set_bot_status("starting")

        except FileNotFoundError:
            logger.error(
                f"Firebase credentials file not found: {self.config.credentials_path}\n"
                "   Download from Firebase Console → Project Settings → Service Accounts"
            )
        except Exception as e:
            logger.error(f"Firebase initialization error: {e}", exc_info=True)

    # ──────────────────────────────────────────────────────────
    # Write Operations (Backend → Firebase)
    # ──────────────────────────────────────────────────────────

    def push_signal(self, signal) -> bool:
        """
        Push a new trading signal to Firebase.
        The dashboard's LiveSignals component will show this immediately.
        Includes score and score_breakdown so dashboard shows signal quality.

        Firebase path: /signals/{auto_generated_key}
        """
        if not self.is_connected:
            return False

        try:
            data = signal.to_dict()
            data["type"] = "signal"

            # .push() creates a new entry with a unique key (like a new row in a table)
            db.reference("signals").push(data)

            score = data.get("score", 0)
            logger.info(
                f"Signal pushed to Firebase: {signal.direction} {signal.stock} "
                f"| Score: {score}/100"
            )
            return True
        except Exception as e:
            logger.error(f"Failed to push signal: {e}")
            return False

    def push_trade(self, trade_data: dict) -> bool:
        """
        Push an executed/closed trade to Firebase.
        These appear in the TradeHistory component on the dashboard.

        trade_data should include:
        - stock, direction, strategy_name
        - entry_price, exit_price, quantity
        - gross_pnl, net_pnl, charges  ← dashboard shows gross AND net
        - score, slippage, hold_time_minutes
        - exit_reason, timestamp

        Firebase path: /trades/{auto_generated_key}
        """
        if not self.is_connected:
            return False

        try:
            data = dict(trade_data)  # Don't mutate the original
            data["type"] = "trade"
            data["pushed_at"] = datetime.now().isoformat()

            db.reference("trades").push(data)
            stock = data.get("stock", "?")
            net_pnl = data.get("net_pnl", data.get("pnl", 0))
            logger.info(
                f"Trade pushed to Firebase: "
                f"{data.get('direction')} {stock} | "
                f"Net P&L: Rs.{net_pnl:+,.2f}"
            )
            return True
        except Exception as e:
            logger.error(f"Failed to push trade: {e}")
            return False

    def push_portfolio(self, portfolio_state: dict) -> bool:
        """
        Push the current portfolio state to Firebase.
        Called every few seconds so the dashboard shows live P&L.

        Firebase path: /portfolio (overwrite — only latest state matters)

        portfolio_state (from portfolio.get_state()) includes:
        {
            "current_capital": 1045.50,
            "day_pnl": 45.50,          ← NET P&L (after charges)
            "day_gross_pnl": 80.00,    ← Gross P&L (before charges)
            "brokerage_paid_today": 34.50,
            "total_pnl": 45.50,
            "total_return_pct": 4.55,
            "trades_today": 2,
        }
        """
        if not self.is_connected:
            return False

        try:
            portfolio_state["updated_at"] = datetime.now().isoformat()

            # .set() overwrites the entire node (portfolio is "latest state", not history)
            db.reference("portfolio").set(portfolio_state)
            logger.debug(
                f"Portfolio updated: Rs.{portfolio_state.get('current_capital', 0):,.2f} | "
                f"Net P&L: Rs.{portfolio_state.get('day_pnl', 0):+,.2f}"
            )
            return True
        except Exception as e:
            logger.error(f"Failed to push portfolio: {e}")
            return False

    def push_open_position(self, position_data: dict) -> bool:
        """
        Push an open position to Firebase.
        The OpenPositions component shows live P&L for these.

        Firebase path: /positions/{stock_symbol}
        """
        if not self.is_connected:
            return False

        try:
            stock = position_data.get("stock", "UNKNOWN")
            position_data["updated_at"] = datetime.now().isoformat()
            db.reference(f"positions/{stock}").set(position_data)
            return True
        except Exception as e:
            logger.error(f"Failed to push position: {e}")
            return False

    def remove_position(self, stock: str) -> bool:
        """Remove a closed position from Firebase (so dashboard stops showing it)."""
        if not self.is_connected:
            return False

        try:
            db.reference(f"positions/{stock}").delete()
            logger.info(f"Position removed from Firebase: {stock}")
            return True
        except Exception as e:
            logger.error(f"Failed to remove position: {e}")
            return False

    def clear_all_positions(self) -> bool:
        """Delete ALL positions from Firebase on startup.

        Prevents stale phantom positions from showing on the dashboard after
        a restart. The bot will re-push any REAL positions it adopts from
        Angel One's getPosition() API.
        """
        if not self.is_connected:
            return False

        try:
            db.reference("positions").delete()
            logger.info("Cleared all stale positions from Firebase")
            return True
        except Exception as e:
            logger.error(f"Failed to clear Firebase positions: {e}")
            return False

    def push_daily_report(self, report: dict) -> bool:
        """
        Push end-of-day performance report.
        Stored by date so you can review history.

        Firebase path: /reports/2026-03-04
        """
        if not self.is_connected:
            return False

        try:
            today = datetime.now().strftime("%Y-%m-%d")
            report["date"] = today
            report["generated_at"] = datetime.now().isoformat()

            db.reference(f"reports/{today}").set(report)
            logger.info(
                f"Daily report pushed to Firebase: "
                f"Net P&L Rs.{report.get('day_pnl', 0):+,.2f}"
            )
            return True
        except Exception as e:
            logger.error(f"Failed to push daily report: {e}")
            return False

    def push_market_context(self, context: dict) -> bool:
        """
        Push NIFTY market context for the dashboard's MarketContext component.

        Firebase path: /market_context
        context = {"nifty_direction": "BULLISH", "nifty_ltp": 22150.30, "vix": 14.5}
        """
        if not self.is_connected:
            return False

        try:
            context["updated_at"] = datetime.now().isoformat()
            db.reference("market_context").set(context)
            return True
        except Exception as e:
            logger.error(f"Failed to push market context: {e}")
            return False

    def _set_bot_status(self, status: str):
        """
        Update bot status in Firebase.
        Dashboard uses this to show if bot is running/stopped.

        status: "starting" | "running" | "stopped" | "error"
        """
        try:
            db.reference("status").set({
                "state": status,
                "updated_at": datetime.now().isoformat(),
            })
        except Exception as e:
            logger.debug(f"Status update error: {e}")

    def set_running(self):
        """Mark bot as running in Firebase."""
        self._set_bot_status("running")

    def set_stopped(self):
        """Mark bot as stopped in Firebase."""
        self._set_bot_status("stopped")

    # ──────────────────────────────────────────────────────────
    # Read Operations (Listen for Kill Switch from Dashboard)
    # ──────────────────────────────────────────────────────────

    def listen_for_kill_switch(self, callback: callable):
        """
        Watch the /kill_switch path in Firebase.
        When the dashboard presses the kill switch button, it sets:
          /kill_switch = {"active": true, "triggered_at": "..."}

        This listener calls the callback function immediately.
        The callback should stop the bot and exit all positions.

        Note: This runs the listener in the background.
        """
        if not self.is_connected:
            return

        def _on_kill_switch(event):
            """Called when /kill_switch changes in Firebase."""
            if event.data and event.data.get("active"):
                triggered_at = event.data.get("triggered_at", "unknown")
                logger.warning(f"KILL SWITCH ACTIVATED from dashboard at {triggered_at}")
                callback()

        try:
            db.reference("kill_switch").listen(_on_kill_switch)
            logger.info("Watching for kill switch signal from dashboard...")
        except Exception as e:
            logger.error(f"Failed to set up kill switch listener: {e}")

    def reset_kill_switch(self):
        """Reset kill switch to inactive state (call at bot startup)."""
        try:
            db.reference("kill_switch").set({
                "active": False,
                "reset_at": datetime.now().isoformat(),
            })
        except Exception as e:
            logger.debug(f"Kill switch reset error: {e}")

    def push_regime(self, regime_dict: dict) -> bool:
        """
        Push market regime to Firebase.
        The MarketContext dashboard component shows this.

        regime_dict (from MarketRegimeDetector.to_dict()):
        {
            "regime": "TRENDING",
            "nifty_change_pct": 0.82,
            "vix": 14.5,
            "size_multiplier": 1.1,
            "determined_at": "10:30:00"
        }

        Firebase path: /regime
        """
        if not self.is_connected:
            return False

        try:
            regime_dict["updated_at"] = datetime.now().isoformat()
            db.reference("regime").set(regime_dict)
            logger.info(f"Regime pushed: {regime_dict.get('regime', '?')}")
            return True
        except Exception as e:
            logger.error(f"Failed to push regime: {e}")
            return False

    def push_news_sentiment(self, sentiment_summary: dict) -> bool:
        """
        Push news sentiment summary to Firebase.
        The NewsAlert dashboard component reads this.

        sentiment_summary looks like:
        {
            "RELIANCE": {"sentiment": "positive", "score": 0.7, "skip_today": False},
            "INFY": {"sentiment": "negative", "score": -0.4, "skip_today": True},
            "global_risk_day": False
        }

        Firebase path: /news_sentiment
        """
        if not self.is_connected:
            return False

        try:
            db.reference("news_sentiment").set({
                "data": sentiment_summary,
                "fetched_at": datetime.now().isoformat(),
            })
            positive = sum(
                1 for v in sentiment_summary.values()
                if isinstance(v, dict) and v.get("sentiment") == "positive"
            )
            negative = sum(
                1 for v in sentiment_summary.values()
                if isinstance(v, dict) and v.get("sentiment") == "negative"
            )
            logger.info(f"News sentiment pushed: {positive} positive, {negative} negative")
            return True
        except Exception as e:
            logger.error(f"Failed to push news sentiment: {e}")
            return False

    def push_analytics(self, analytics: dict) -> bool:
        """
        Push performance analytics to Firebase.
        The StrategyBreakdown and PerformanceCard components read this.

        analytics (from TradeAnalytics.get_summary()):
        {
            "total_trades": 5,
            "win_rate_pct": 60.0,
            "total_net_pnl": 185.50,
            "total_charges": 87.20,
            "avg_score": 78.4,
            "strategy_breakdown": {...}
        }

        Firebase path: /analytics
        """
        if not self.is_connected:
            return False

        try:
            analytics["updated_at"] = datetime.now().isoformat()
            db.reference("analytics").set(analytics)
            return True
        except Exception as e:
            logger.error(f"Failed to push analytics: {e}")
            return False

    def push_premarket_status(self, status: dict) -> bool:
        """
        Push pre-market check results to Firebase.
        The PreMarketStatus dashboard component reads this.

        status looks like:
        {
            "is_trading_day": True,
            "margin_available": 5200.0,
            "margin_ok": True,
            "broker_connected": True,
            "watchlist_loaded": True,
            "news_loaded": True,
            "checks_passed": True,
            "message": "All systems ready. Market opens in 12 minutes."
        }

        Firebase path: /premarket_status
        """
        if not self.is_connected:
            return False

        try:
            status["checked_at"] = datetime.now().isoformat()
            db.reference("premarket_status").set(status)
            checks_ok = status.get("checks_passed", False)
            msg = status.get("message", "")
            logger.info(f"Pre-market status pushed: {'OK' if checks_ok else 'ISSUES'} — {msg}")
            return True
        except Exception as e:
            logger.error(f"Failed to push premarket status: {e}")
            return False

    def listen_for_trading_enabled(self, callback: callable):
        """
        Watch the /trading_enabled path for global ON/OFF toggle.

        When the user toggles trading off from the dashboard:
          /trading_enabled = {"enabled": false, "changed_at": "..."}

        The callback receives a boolean: True = enabled, False = disabled.
        The bot pauses scanning when disabled (but doesn't exit positions).

        Note: This is different from kill_switch (which exits all positions).
              trading_enabled just pauses new signal detection.
        """
        if not self.is_connected:
            return

        def _on_trading_enabled(event):
            if event.data and isinstance(event.data, dict):
                enabled = event.data.get("enabled", True)
                changed_at = event.data.get("changed_at", "unknown")
                status = "ENABLED" if enabled else "DISABLED"
                logger.info(f"Trading toggle from dashboard: {status} at {changed_at}")
                callback(enabled)

        try:
            db.reference("trading_enabled").listen(_on_trading_enabled)
            logger.info("Watching for trading ON/OFF toggle from dashboard...")
        except Exception as e:
            logger.error(f"Failed to set up trading_enabled listener: {e}")

    def set_trading_enabled(self, enabled: bool):
        """Set the trading_enabled flag in Firebase (called at bot startup)."""
        try:
            db.reference("trading_enabled").set({
                "enabled": enabled,
                "changed_at": datetime.now().isoformat(),
                "source": "bot",
            })
        except Exception as e:
            logger.debug(f"Failed to set trading_enabled: {e}")

    def clear_today_signals(self):
        """Clear yesterday's signals at bot startup so dashboard is fresh."""
        try:
            db.reference("signals").delete()
            logger.info("Cleared old signals from Firebase")
        except Exception as e:
            logger.debug(f"Clear signals error: {e}")
