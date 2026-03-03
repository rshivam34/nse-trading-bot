"""
Portfolio — Tracks capital, positions, and P&L.
================================================
Tracks GROSS P&L and NET P&L separately so you always see both:

  Gross P&L = raw price movement × quantity
  Net P&L   = gross P&L minus ALL charges (brokerage, STT, GST, etc.)

Why separate? Because at small capital (Rs.1K), charges can eat
30-50% of a small win. You need to see the real number.

Also tracks:
- brokerage_paid_today: total charges accumulated (shows "cost of doing business")
- Per-strategy stats: which strategy is winning / losing
- Average signal score of trades taken
"""

import logging
from datetime import datetime

logger = logging.getLogger(__name__)


class Portfolio:
    """Tracks capital and trading performance with gross/net P&L separation."""

    def __init__(self, initial_capital: float):
        self.initial_capital = initial_capital
        self.current_capital = initial_capital
        self.day_start_capital = initial_capital

        # P&L tracking — gross and net separately
        # Gross: price move × qty (before charges)
        # Net:   what you actually earned/lost after all fees
        self.gross_pnl_today: float = 0.0
        self.net_pnl_today: float = 0.0
        self.brokerage_paid_today: float = 0.0  # Running total of all charges

        # Full trade log for the current day
        self.trade_log: list[dict] = []

        # Per-strategy win/loss/P&L tracking
        # Format: {"ORB": {"trades": 2, "wins": 1, "losses": 1, "total_pnl": 45.0, "total_charges": 12.5}}
        self.strategy_stats: dict[str, dict] = {}

    def record_trade(self, trade_data: dict):
        """
        Log a completed trade and update capital.

        Expected keys in trade_data:
            stock           (str)     — e.g. "RELIANCE"
            strategy_name   (str)     — e.g. "ORB", "VWAP_BOUNCE"
            direction       (str)     — "LONG" or "SHORT"
            entry_price     (float)
            exit_price      (float)
            quantity        (int)
            gross_pnl       (float)   — raw move × qty
            net_pnl         (float)   — after all charges
            charges         (float)   — total brokerage + taxes
            score           (int)     — signal score 0-100
            slippage        (float)   — actual_entry - signal_entry (Rs.)
            hold_time_minutes (float)
            exit_reason     (str)     — e.g. "TARGET", "STOP_LOSS", "FORCE_EXIT"
            timestamp       (str)     — ISO format
        """
        gross_pnl = trade_data.get("gross_pnl", trade_data.get("pnl", 0))
        net_pnl = trade_data.get("net_pnl", gross_pnl)  # Fall back to gross if not provided
        charges = trade_data.get("charges", 0)
        strategy = trade_data.get("strategy_name", "UNKNOWN")

        # Capital grows/shrinks by NET P&L (what we actually made)
        self.current_capital += net_pnl

        # Accumulate today's totals
        self.gross_pnl_today += gross_pnl
        self.net_pnl_today += net_pnl
        self.brokerage_paid_today += charges

        # Track per-strategy performance
        self._update_strategy_stats(strategy, net_pnl, charges)

        # Tag with capital after this trade (useful for debugging drawdowns)
        trade_data["capital_after"] = round(self.current_capital, 2)
        if "timestamp" not in trade_data:
            trade_data["timestamp"] = datetime.now().isoformat()

        self.trade_log.append(trade_data)

        logger.info(
            f"Trade recorded: {trade_data.get('stock', '?')} "
            f"{trade_data.get('direction', '?')} | "
            f"Gross: Rs.{gross_pnl:+,.2f} | "
            f"Charges: Rs.{charges:.2f} | "
            f"Net: Rs.{net_pnl:+,.2f} | "
            f"Capital: Rs.{self.current_capital:,.2f}"
        )

    def _update_strategy_stats(self, strategy: str, net_pnl: float, charges: float):
        """Update per-strategy win/loss record after each trade."""
        if strategy not in self.strategy_stats:
            self.strategy_stats[strategy] = {
                "trades": 0,
                "wins": 0,
                "losses": 0,
                "total_pnl": 0.0,
                "total_charges": 0.0,
            }

        stats = self.strategy_stats[strategy]
        stats["trades"] += 1
        stats["total_pnl"] = round(stats["total_pnl"] + net_pnl, 2)
        stats["total_charges"] = round(stats["total_charges"] + charges, 2)

        if net_pnl > 0:
            stats["wins"] += 1
        else:
            stats["losses"] += 1

    def get_state(self) -> dict:
        """
        Current portfolio snapshot for Firebase and logging.

        Returns both gross and net P&L so the dashboard can display:
        - "Gross P&L: +Rs.80"
        - "Charges: Rs.35"
        - "Net P&L: +Rs.45"   ← the real number
        """
        return {
            "initial_capital": self.initial_capital,
            "current_capital": round(self.current_capital, 2),
            # Net P&L (after charges) — what actually matters
            "day_pnl": round(self.net_pnl_today, 2),
            # Gross P&L — before fees (useful for seeing if strategy is working)
            "day_gross_pnl": round(self.gross_pnl_today, 2),
            # Total charges paid today (helps track cost drag)
            "brokerage_paid_today": round(self.brokerage_paid_today, 2),
            # Total since bot started
            "total_pnl": round(self.current_capital - self.initial_capital, 2),
            "total_return_pct": round(
                ((self.current_capital - self.initial_capital) / self.initial_capital) * 100, 2
            ),
            "trades_today": len(self.trade_log),
            "updated_at": datetime.now().isoformat(),
        }

    def daily_report(self) -> dict:
        """
        End-of-day performance summary.
        Includes charge breakdown so you can see what fees cost you.
        """
        day_trades = self.trade_log
        wins = [t for t in day_trades if t.get("net_pnl", t.get("pnl", 0)) > 0]
        losses = [t for t in day_trades if t.get("net_pnl", t.get("pnl", 0)) <= 0]

        # Average signal score (only for trades that have a score)
        scores = [t.get("score", 0) for t in day_trades if t.get("score", 0) > 0]
        avg_score = round(sum(scores) / len(scores), 1) if scores else 0

        # Average slippage in rupees
        slippages = [abs(t.get("slippage", 0)) for t in day_trades]
        avg_slippage = round(sum(slippages) / len(slippages), 2) if slippages else 0

        report = {
            "starting_capital": round(self.day_start_capital, 2),
            "ending_capital": round(self.current_capital, 2),
            "day_pnl": round(self.net_pnl_today, 2),            # Real bottom line
            "day_gross_pnl": round(self.gross_pnl_today, 2),    # Before charges
            "brokerage_paid": round(self.brokerage_paid_today, 2),
            "trades_taken": len(day_trades),
            "wins": len(wins),
            "losses": len(losses),
            "win_rate": round(len(wins) / len(day_trades) * 100, 1) if day_trades else 0,
            "avg_signal_score": avg_score,
            "avg_slippage_rs": avg_slippage,
            "strategy_breakdown": self.strategy_stats.copy(),
        }

        logger.info(
            f"Daily report — "
            f"Gross: Rs.{report['day_gross_pnl']:+,.2f} | "
            f"Charges: Rs.{report['brokerage_paid']:.2f} | "
            f"Net: Rs.{report['day_pnl']:+,.2f} | "
            f"W/L: {report['wins']}/{report['losses']} | "
            f"Avg score: {avg_score}"
        )
        return report

    def reset_daily(self):
        """Call at start of each new trading day to reset daily counters."""
        self.day_start_capital = self.current_capital
        self.gross_pnl_today = 0.0
        self.net_pnl_today = 0.0
        self.brokerage_paid_today = 0.0
        self.trade_log.clear()
        self.strategy_stats.clear()
        logger.info(
            f"Portfolio reset for new day. "
            f"Starting capital: Rs.{self.current_capital:,.2f}"
        )
