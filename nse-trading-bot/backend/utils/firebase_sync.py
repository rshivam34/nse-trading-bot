"""
Firebase Sync — Pushes live data to the dashboard.
===================================================
The dashboard (GitHub Pages) reads from Firebase in real-time.
This module writes signals, positions, and reports to Firebase.

TODO (Phase 3): Implement with real Firebase Admin SDK.
Currently logs updates for development.
"""

import logging
import json
from datetime import datetime

logger = logging.getLogger(__name__)


class FirebaseSync:
    """Pushes trading data to Firebase Realtime Database."""

    def __init__(self, firebase_config):
        self.config = firebase_config
        self.is_connected = False

        # TODO: Initialize Firebase
        # import firebase_admin
        # from firebase_admin import credentials, db
        # cred = credentials.Certificate(firebase_config.credentials_path)
        # firebase_admin.initialize_app(cred, {"databaseURL": firebase_config.database_url})
        # self.is_connected = True

    def push_signal(self, signal):
        """Push a new trading signal to Firebase."""
        data = signal.to_dict()
        logger.info(f"📤 [MOCK Firebase] Signal: {json.dumps(data, default=str)}")
        # TODO: db.reference("signals").push(data)

    def push_trade(self, signal):
        """Push an executed trade to Firebase."""
        data = signal.to_dict()
        data["status"] = "EXECUTED"
        logger.info(f"📤 [MOCK Firebase] Trade: {data['stock']} {data['direction']}")
        # TODO: db.reference("trades").push(data)

    def push_portfolio(self, portfolio_state: dict):
        """Push portfolio state update."""
        logger.debug(f"📤 [MOCK Firebase] Portfolio: ₹{portfolio_state.get('current_capital', 0):,.2f}")
        # TODO: db.reference("portfolio").set(portfolio_state)

    def push_daily_report(self, report: dict):
        """Push end-of-day report."""
        today = datetime.now().strftime("%Y-%m-%d")
        logger.info(f"📤 [MOCK Firebase] Daily Report: P&L ₹{report.get('day_pnl', 0):+,.2f}")
        # TODO: db.reference(f"reports/{today}").set(report)
