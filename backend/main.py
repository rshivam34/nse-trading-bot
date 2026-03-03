"""
NSE Intraday Trading Bot — Main Entry Point
=============================================
This is the file you run every morning before market opens.

Usage:
    python main.py              # Normal mode (paper trading)
    python main.py --live       # Live trading (after paper testing)

The bot will:
1. Authenticate with Angel One
2. Load watchlist
3. Start streaming real-time data
4. Scan for patterns
5. Generate signals / place trades
6. Push updates to Firebase (for dashboard)
7. Exit all positions by 3:15 PM
8. Generate daily report
"""

import sys
import signal
import logging
from datetime import datetime, time as dtime

from config import config
from utils.logger import setup_logger
from utils.watchlist import get_watchlist
from core.broker import BrokerConnection
from core.data_stream import DataStream
from core.scanner import PatternScanner
from core.risk_manager import RiskManager
from core.order_manager import OrderManager
from core.portfolio import Portfolio
from utils.firebase_sync import FirebaseSync


logger = logging.getLogger(__name__)


class TradingBot:
    """
    Main bot orchestrator.
    Coordinates all components: data → patterns → signals → orders → monitoring.
    """

    def __init__(self):
        self.is_running = False
        self.mode = "PAPER" if config.trading.paper_trading else "LIVE"

        # Initialize components
        self.broker = BrokerConnection(config.broker)
        self.portfolio = Portfolio(config.trading.initial_capital)
        self.risk_manager = RiskManager(config.trading, self.portfolio)
        self.order_manager = OrderManager(self.broker, self.risk_manager, config.trading)
        self.scanner = PatternScanner(config.trading, config.indicators)
        self.data_stream = DataStream(self.broker)
        self.firebase = FirebaseSync(config.firebase)
        self.watchlist = get_watchlist()

    def start(self):
        """Start the trading bot."""
        logger.info("=" * 60)
        logger.info(f"  🤖 NSE Trading Bot Starting — Mode: {self.mode}")
        logger.info(f"  💰 Capital: ₹{config.trading.initial_capital:,.0f}")
        logger.info(f"  📊 Watchlist: {len(self.watchlist)} stocks")
        logger.info(f"  🛡️ Risk/Trade: {config.trading.max_risk_per_trade_pct}%")
        logger.info(f"  🎯 Risk:Reward = 1:{config.trading.risk_reward_ratio}")
        logger.info("=" * 60)

        # Step 1: Authenticate with broker
        if not self._authenticate():
            logger.error("❌ Authentication failed. Exiting.")
            return

        # Step 2: Start data stream
        self.is_running = True
        self._start_streaming()

        # Step 3: Main trading loop
        self._trading_loop()

    def _authenticate(self) -> bool:
        """Connect to Angel One."""
        try:
            self.broker.connect()
            logger.info("✅ Connected to Angel One SmartAPI")
            return True
        except Exception as e:
            logger.error(f"Authentication error: {e}")
            return False

    def _start_streaming(self):
        """Begin real-time price data streaming."""
        tokens = [stock["token"] for stock in self.watchlist]
        self.data_stream.subscribe(tokens, callback=self._on_price_update)
        logger.info(f"📡 Streaming live data for {len(tokens)} stocks")

    def _on_price_update(self, tick_data: dict):
        """
        Called every time a new price tick arrives.
        This is the heart of the bot.
        """
        now = datetime.now().time()

        # Safety: no new trades after 2:30 PM
        if now > config.trading.no_new_trades_after:
            return

        # Safety: still in ORB observation period
        if now < config.trading.orb_end:
            self.scanner.update_orb_range(tick_data)
            return

        # Check for patterns
        signals = self.scanner.scan(tick_data)

        for signal in signals:
            # Risk check
            if not self.risk_manager.can_trade(signal):
                logger.info(f"⚠️ Risk manager blocked: {signal.stock} — {signal.reason}")
                continue

            # Execute or suggest
            if config.trading.suggest_only:
                logger.info(f"💡 SIGNAL: {signal}")
                self.firebase.push_signal(signal)
            else:
                self.order_manager.execute(signal)
                self.firebase.push_trade(signal)

    def _trading_loop(self):
        """Main loop — runs until market close."""
        try:
            while self.is_running:
                now = datetime.now().time()

                # Force exit at 3:15 PM
                if now >= config.trading.force_exit_time:
                    logger.info("⏰ 3:15 PM — Force-exiting all positions")
                    self.order_manager.exit_all_positions()
                    self._generate_report()
                    break

                # Check daily loss limit
                if self.risk_manager.daily_loss_limit_hit():
                    logger.warning("🛑 Daily loss limit hit — stopping bot")
                    self.order_manager.exit_all_positions()
                    self._generate_report()
                    break

                # Monitor open positions (check SL/target)
                self.order_manager.monitor_positions()

                # Push portfolio update to Firebase
                self.firebase.push_portfolio(self.portfolio.get_state())

        except KeyboardInterrupt:
            logger.info("🔴 Bot stopped by user (Ctrl+C)")
            self.shutdown()

    def _generate_report(self):
        """End-of-day performance report."""
        report = self.portfolio.daily_report()
        logger.info("\n📋 Daily Report:")
        logger.info(f"  Starting Capital: ₹{report['starting_capital']:,.2f}")
        logger.info(f"  Ending Capital:   ₹{report['ending_capital']:,.2f}")
        logger.info(f"  Day P&L:          ₹{report['day_pnl']:+,.2f}")
        logger.info(f"  Trades Taken:     {report['trades_taken']}")
        logger.info(f"  Win Rate:         {report['win_rate']}%")
        self.firebase.push_daily_report(report)

    def shutdown(self):
        """Graceful shutdown."""
        logger.info("Shutting down...")
        self.is_running = False
        self.order_manager.exit_all_positions()
        self.data_stream.disconnect()
        self.broker.disconnect()
        logger.info("👋 Bot shut down cleanly")


def main():
    setup_logger(config.log_level, config.log_file)

    # Handle Ctrl+C gracefully
    bot = TradingBot()
    signal.signal(signal.SIGINT, lambda s, f: bot.shutdown())

    # Check for --live flag
    if "--live" in sys.argv:
        config.trading.paper_trading = False
        config.trading.suggest_only = False
        logger.warning("⚡ LIVE TRADING MODE — Real money at risk!")

    bot.start()


if __name__ == "__main__":
    main()
