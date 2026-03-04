"""
Trade Analytics — CSV logging and performance analysis.
=======================================================
Every completed trade is appended to a CSV file (logs/trades.csv).
This gives you a permanent record you can open in Excel/Google Sheets.

Why CSV?
- Persists between bot restarts (unlike in-memory portfolio state)
- Easy to open and analyze in Excel or Google Sheets
- Can be used to tune strategy parameters over time
- Helps you answer: "Is my ORB strategy actually profitable after charges?"

Fields logged per trade:
  date, time, stock, strategy, direction
  entry_price, exit_price, quantity
  gross_pnl, charges, net_pnl
  score, slippage, hold_time_minutes, exit_reason
  nifty_direction, regime, vix, rsi_at_entry, volume_ratio
"""

import csv
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# All fields written to the CSV — order matters (matches column order in the file)
TRADE_FIELDS = [
    "date",
    "time",
    "stock",
    "strategy",
    "direction",
    "entry_price",
    "exit_price",
    "quantity",
    "gross_pnl",
    "charges",
    "net_pnl",
    "score",
    "slippage",
    "hold_time_minutes",
    "exit_reason",
    "nifty_direction",
    "regime",
    "vix",
    "rsi_at_entry",
    "volume_ratio",
    "r_multiple",
    "planned_r_target",
    "confluence_count",
    "confluence_strategies",
    "atr_value",
]


class TradeAnalytics:
    """
    Logs every trade to CSV and computes performance stats.

    Usage:
        analytics = TradeAnalytics("logs/trades.csv")
        analytics.log_trade(trade_data)       # Call after each trade closes
        summary = analytics.get_summary()     # Call at end of day
    """

    def __init__(self, csv_path: str = "logs/trades.csv"):
        self.csv_path = csv_path
        self._ensure_csv_exists()

    def _ensure_csv_exists(self):
        """Create the CSV file with headers if it doesn't exist yet."""
        path = Path(self.csv_path)
        path.parent.mkdir(parents=True, exist_ok=True)  # Create logs/ folder if needed

        if not path.exists():
            with open(path, "w", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=TRADE_FIELDS)
                writer.writeheader()
            logger.info(f"Created trade log CSV: {self.csv_path}")

    def log_trade(self, trade_data: dict):
        """
        Append one completed trade to the CSV.

        trade_data can have any keys — we only write TRADE_FIELDS columns.
        Missing fields are written as empty string (not an error).

        Typical keys from order_manager.py's to_dict():
            stock, strategy_name (→ "strategy"), direction
            entry_price, exit_price, quantity
            gross_pnl, charges, net_pnl
            score, slippage, hold_time_minutes, exit_reason
            nifty_direction, regime, vix, rsi_at_entry, volume_ratio
        """
        try:
            # Map "strategy_name" → "strategy" (the CSV column name)
            if "strategy_name" in trade_data and "strategy" not in trade_data:
                trade_data = dict(trade_data)  # Don't mutate the caller's dict
                trade_data["strategy"] = trade_data["strategy_name"]

            row = {field: trade_data.get(field, "") for field in TRADE_FIELDS}

            # Auto-fill date and time if not already in trade_data
            now = datetime.now()
            if not row["date"]:
                row["date"] = now.strftime("%Y-%m-%d")
            if not row["time"]:
                row["time"] = now.strftime("%H:%M:%S")

            with open(self.csv_path, "a", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=TRADE_FIELDS)
                writer.writerow(row)

            net_pnl = row.get("net_pnl", 0)
            logger.debug(
                f"Trade logged to CSV: {row.get('stock')} "
                f"{row.get('direction')} | Net P&L: Rs.{net_pnl}"
            )

        except Exception as e:
            logger.error(f"Failed to log trade to CSV: {e}")

    def get_summary(self) -> dict:
        """
        Read the entire CSV and compute all-time performance stats.
        Called at end of day or on-demand.

        Returns a dict suitable for:
        - Logging to console
        - Pushing to Firebase via firebase_sync.push_analytics()
        """
        trades = self._read_all_trades()
        if not trades:
            return {"total_trades": 0, "message": "No trades recorded yet"}

        net_pnls = [float(t.get("net_pnl") or 0) for t in trades]
        gross_pnls = [float(t.get("gross_pnl") or 0) for t in trades]
        charges = [float(t.get("charges") or 0) for t in trades]
        scores = [float(t.get("score") or 0) for t in trades if t.get("score")]
        slippages = [abs(float(t.get("slippage") or 0)) for t in trades]
        hold_times = [float(t.get("hold_time_minutes") or 0) for t in trades]

        wins = [p for p in net_pnls if p > 0]
        losses = [p for p in net_pnls if p <= 0]

        return {
            "total_trades": len(trades),
            "wins": len(wins),
            "losses": len(losses),
            "win_rate_pct": round(len(wins) / len(trades) * 100, 1) if trades else 0,
            "total_gross_pnl": round(sum(gross_pnls), 2),
            "total_charges": round(sum(charges), 2),
            "total_net_pnl": round(sum(net_pnls), 2),
            "avg_win_rs": round(sum(wins) / len(wins), 2) if wins else 0,
            "avg_loss_rs": round(sum(losses) / len(losses), 2) if losses else 0,
            "avg_score": round(sum(scores) / len(scores), 1) if scores else 0,
            "avg_slippage_rs": round(sum(slippages) / len(slippages), 2) if slippages else 0,
            "avg_hold_time_min": round(sum(hold_times) / len(hold_times), 1) if hold_times else 0,
            "strategy_breakdown": self.get_strategy_breakdown(trades),
            "score_distribution": self.get_score_distribution(trades),
        }

    def get_today_summary(self) -> dict:
        """Same as get_summary() but filtered to today's trades only."""
        today = datetime.now().strftime("%Y-%m-%d")
        today_trades = [t for t in self._read_all_trades() if t.get("date") == today]

        if not today_trades:
            return {"total_trades": 0, "date": today}

        net_pnls = [float(t.get("net_pnl") or 0) for t in today_trades]
        gross_pnls = [float(t.get("gross_pnl") or 0) for t in today_trades]
        charges = [float(t.get("charges") or 0) for t in today_trades]
        wins = [p for p in net_pnls if p > 0]
        losses = [p for p in net_pnls if p <= 0]

        return {
            "date": today,
            "total_trades": len(today_trades),
            "wins": len(wins),
            "losses": len(losses),
            "win_rate_pct": round(len(wins) / len(today_trades) * 100, 1),
            "total_gross_pnl": round(sum(gross_pnls), 2),
            "total_charges": round(sum(charges), 2),
            "total_net_pnl": round(sum(net_pnls), 2),
            "strategy_breakdown": self.get_strategy_breakdown(today_trades),
        }

    def get_strategy_breakdown(self, trades: Optional[list] = None) -> dict:
        """
        Per-strategy performance.

        Returns something like:
        {
            "ORB":        {"trades": 3, "wins": 2, "losses": 1, "total_pnl": 120.5, "win_rate_pct": 66.7},
            "VWAP_BOUNCE": {"trades": 1, "wins": 0, "losses": 1, "total_pnl": -45.2, "win_rate_pct": 0.0},
        }

        Useful for: "Which strategies should I keep? Which are losing money?"
        """
        if trades is None:
            trades = self._read_all_trades()

        breakdown: dict[str, dict] = {}
        for trade in trades:
            strategy = trade.get("strategy", "UNKNOWN") or "UNKNOWN"
            net_pnl = float(trade.get("net_pnl") or 0)

            if strategy not in breakdown:
                breakdown[strategy] = {
                    "trades": 0,
                    "wins": 0,
                    "losses": 0,
                    "total_pnl": 0.0,
                }

            breakdown[strategy]["trades"] += 1
            breakdown[strategy]["total_pnl"] = round(
                breakdown[strategy]["total_pnl"] + net_pnl, 2
            )
            if net_pnl > 0:
                breakdown[strategy]["wins"] += 1
            else:
                breakdown[strategy]["losses"] += 1

        # Add win rate % to each strategy
        for stats in breakdown.values():
            t = stats["trades"]
            stats["win_rate_pct"] = round(stats["wins"] / t * 100, 1) if t else 0

        return breakdown

    def get_score_distribution(self, trades: Optional[list] = None) -> dict:
        """
        Counts how many trades were taken at each score range.

        Use this to tune min_score_to_trade:
        - If 70-79 trades have low win rate → raise threshold to 80
        - If 90+ trades have high win rate → keep threshold at 70 (don't miss them)
        """
        if trades is None:
            trades = self._read_all_trades()

        dist = {"70-79": 0, "80-89": 0, "90-100": 0, "below_70": 0}
        for trade in trades:
            score = float(trade.get("score") or 0)
            if score >= 90:
                dist["90-100"] += 1
            elif score >= 80:
                dist["80-89"] += 1
            elif score >= 70:
                dist["70-79"] += 1
            else:
                dist["below_70"] += 1

        return dist

    def _read_all_trades(self) -> list[dict]:
        """Read all rows from the CSV file."""
        try:
            path = Path(self.csv_path)
            if not path.exists():
                return []

            with open(path, "r", newline="") as f:
                reader = csv.DictReader(f)
                return list(reader)

        except Exception as e:
            logger.error(f"Failed to read trade log CSV: {e}")
            return []

    def get_today_trades(self) -> list[dict]:
        """Read only today's trades from the CSV."""
        today = datetime.now().strftime("%Y-%m-%d")
        return [t for t in self._read_all_trades() if t.get("date") == today]
