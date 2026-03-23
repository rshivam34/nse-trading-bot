"""
Fundamental Filter — Red Flags + Fair Value + Earnings Calendar.
================================================================

Runs once at pre-market startup. For each stock in the watchlist:
1. Checks for fundamental red flags (ROE < 10%, D/E > 2, EPS < 0)
2. Computes fair value modifier based on PE vs sector average
3. Checks earnings calendar (skip stocks reporting this week)

Results cached in JSON for 7 days (fundamentals don't change daily).

Data source: yfinance (RELIANCE.NS, TCS.NS, etc. — free, no API key).
"""

import json
import logging
import os
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class StockFundamentals:
    """Fundamental metrics and flags for a single stock."""
    stock: str = ""
    roe: float = 0.0
    debt_equity: float = 0.0
    eps: float = 0.0
    pe_ratio: float = 0.0
    industry_pe: float = 0.0
    has_red_flag: bool = False
    red_flag_reasons: list = field(default_factory=list)
    fair_value_modifier: int = 0        # -5 (overvalued), 0 (fair), +5 (undervalued)
    has_earnings_this_week: bool = False
    fetched_at: str = ""                # ISO datetime for cache expiry


class FundamentalFilter:
    """
    Fetches and caches fundamental data for watchlist stocks.

    Usage:
        filt = FundamentalFilter("logs/fundamental_cache.json")
        data = filt.analyze(["RELIANCE", "TCS", ...], sector_map)
        # data["RELIANCE"].has_red_flag = False
        # data["RELIANCE"].fair_value_modifier = 5  (undervalued)
        # filt.earnings_skip_set = {"INFY", "WIPRO"}
    """

    def __init__(self, cache_path: str = "logs/fundamental_cache.json", cache_expiry_days: int = 7):
        self.cache_path = cache_path
        self.cache_expiry_days = cache_expiry_days
        self.cache: dict[str, dict] = {}
        self.earnings_skip_set: set[str] = set()

    # BFSI sectors — banks/NBFCs inherently have high D/E (5-15 is normal)
    # D/E check must be skipped for these sectors to avoid false red flags
    BFSI_SECTORS = {"NIFTY Bank", "NIFTY Financial"}

    def analyze(
        self,
        watchlist_symbols: list[str],
        sector_map: dict[str, str],
    ) -> dict[str, StockFundamentals]:
        """
        Main entry. Fetch/cache fundamentals for all watchlist stocks.

        Args:
            watchlist_symbols: List of stock symbols (e.g., ["RELIANCE", "TCS"]).
            sector_map: Dict mapping stock → sector name (for industry PE average).

        Returns:
            Dict mapping stock symbol to StockFundamentals.
        """
        try:
            import yfinance  # noqa: F401 — check availability
        except ImportError:
            logger.warning("yfinance not installed — fundamental filter disabled")
            return {}

        # Load cache
        self._load_cache()

        results: dict[str, StockFundamentals] = {}
        now = datetime.now()
        expiry_cutoff = now - timedelta(days=self.cache_expiry_days)
        fetch_count = 0
        cache_hit_count = 0

        for symbol in watchlist_symbols:
            sector = sector_map.get(symbol, "")
            # Check cache
            cached = self.cache.get(symbol)
            if cached and self._is_cache_valid(cached, expiry_cutoff):
                fund = self._dict_to_fundamentals(cached)
                # Re-check red flags with sector context (cache may have stale BFSI flag)
                if sector in self.BFSI_SECTORS:
                    fund.red_flag_reasons = [r for r in fund.red_flag_reasons if "D/E" not in r]
                    fund.has_red_flag = len(fund.red_flag_reasons) > 0
                cache_hit_count += 1
            else:
                # Fetch fresh (pass sector so D/E check skips BFSI)
                fund = self._fetch_fundamentals(symbol, sector=sector)
                fetch_count += 1
                if fund:
                    self.cache[symbol] = asdict(fund)

            if fund:
                results[symbol] = fund

                # Track earnings skip
                if fund.has_earnings_this_week:
                    self.earnings_skip_set.add(symbol)

        # Compute fair value modifiers (needs all PE data + sector averages)
        self._compute_fair_value_modifiers(results, sector_map)

        # Save updated cache
        self._save_cache()

        logger.info(
            f"Fundamental analysis: {len(results)} stocks "
            f"({cache_hit_count} cached, {fetch_count} fetched). "
            f"Red flags: {sum(1 for f in results.values() if f.has_red_flag)}. "
            f"Earnings skip: {len(self.earnings_skip_set)} stocks."
        )

        return results

    def _fetch_fundamentals(self, stock: str, sector: str = "") -> Optional[StockFundamentals]:
        """Fetch fundamental data for a single stock via yfinance."""
        try:
            import yfinance as yf

            ticker = yf.Ticker(f"{stock}.NS")
            info = ticker.info or {}

            fund = StockFundamentals(
                stock=stock,
                fetched_at=datetime.now().isoformat(),
            )

            # Extract metrics (yfinance field names)
            fund.roe = self._safe_float(info.get("returnOnEquity", 0)) * 100  # Convert decimal to %
            fund.debt_equity = self._safe_float(info.get("debtToEquity", 0)) / 100  # yfinance gives as %
            fund.eps = self._safe_float(info.get("trailingEps", 0))
            fund.pe_ratio = self._safe_float(info.get("trailingPE", 0))

            # Red flag detection
            fund.red_flag_reasons = []
            if fund.roe > 0 and fund.roe < 10:
                fund.red_flag_reasons.append(f"ROE {fund.roe:.1f}% < 10%")
            # Skip D/E check for BFSI — banks/NBFCs inherently have D/E 5-15
            is_bfsi = sector in self.BFSI_SECTORS
            if not is_bfsi and fund.debt_equity > 2.0:
                fund.red_flag_reasons.append(f"D/E {fund.debt_equity:.1f} > 2.0")
            if fund.eps < 0:
                fund.red_flag_reasons.append(f"EPS {fund.eps:.1f} (negative)")

            fund.has_red_flag = len(fund.red_flag_reasons) > 0

            # Earnings calendar check
            fund.has_earnings_this_week = self._check_earnings(ticker)

            return fund

        except Exception as e:
            logger.debug(f"Fundamental fetch failed for {stock}: {e}")
            # Return neutral defaults
            return StockFundamentals(
                stock=stock,
                fetched_at=datetime.now().isoformat(),
            )

    def _check_earnings(self, ticker) -> bool:
        """Check if stock has earnings within 7 days."""
        try:
            cal = ticker.calendar
            if cal is None or cal.empty:
                return False

            # calendar can be a DataFrame with 'Earnings Date' column or similar
            today = datetime.now().date()
            week_ahead = today + timedelta(days=7)

            # Try different calendar formats yfinance returns
            if hasattr(cal, 'index'):
                for date_val in cal.index:
                    try:
                        if hasattr(date_val, 'date'):
                            d = date_val.date()
                        else:
                            d = date_val
                        if today <= d <= week_ahead:
                            return True
                    except (TypeError, AttributeError):
                        continue

            return False

        except Exception:
            return False

    def _compute_fair_value_modifiers(
        self,
        results: dict[str, StockFundamentals],
        sector_map: dict[str, str],
    ):
        """Compute PE vs sector average to determine fair value modifier."""
        # Group stocks by sector and compute average PE
        sector_pe: dict[str, list[float]] = {}
        for stock, fund in results.items():
            sector = sector_map.get(stock, "OTHER")
            if fund.pe_ratio > 0 and fund.pe_ratio < 500:  # Filter outliers
                sector_pe.setdefault(sector, []).append(fund.pe_ratio)

        # Compute sector average PE
        sector_avg_pe: dict[str, float] = {}
        for sector, pe_list in sector_pe.items():
            if pe_list:
                # Use median to avoid outlier influence
                sorted_pe = sorted(pe_list)
                mid = len(sorted_pe) // 2
                sector_avg_pe[sector] = sorted_pe[mid]

        # Assign fair value modifier per stock
        for stock, fund in results.items():
            sector = sector_map.get(stock, "OTHER")
            avg_pe = sector_avg_pe.get(sector, 0)

            if avg_pe > 0 and fund.pe_ratio > 0:
                fund.industry_pe = round(avg_pe, 1)
                pe_ratio_vs_industry = fund.pe_ratio / avg_pe

                if pe_ratio_vs_industry > 2.0:
                    fund.fair_value_modifier = -5  # Overvalued
                elif pe_ratio_vs_industry < 0.7:
                    fund.fair_value_modifier = 5   # Undervalued
                else:
                    fund.fair_value_modifier = 0   # Fair

    # ── Cache management ──────────────────────────────────────────────

    def _load_cache(self):
        """Load fundamental cache from JSON file."""
        try:
            if os.path.exists(self.cache_path):
                with open(self.cache_path, "r") as f:
                    self.cache = json.load(f)
                logger.info(f"Fundamental cache loaded: {len(self.cache)} stocks")
            else:
                self.cache = {}
        except Exception as e:
            logger.warning(f"Failed to load fundamental cache: {e}")
            self.cache = {}

    def _save_cache(self):
        """Save fundamental cache to JSON file."""
        try:
            os.makedirs(os.path.dirname(self.cache_path) or ".", exist_ok=True)
            with open(self.cache_path, "w") as f:
                json.dump(self.cache, f, indent=2, default=str)
        except Exception as e:
            logger.warning(f"Failed to save fundamental cache: {e}")

    def _is_cache_valid(self, cached: dict, expiry_cutoff: datetime) -> bool:
        """Check if cached entry is still valid (within expiry window)."""
        fetched_at = cached.get("fetched_at", "")
        if not fetched_at:
            return False
        try:
            fetch_time = datetime.fromisoformat(fetched_at)
            return fetch_time > expiry_cutoff
        except (ValueError, TypeError):
            return False

    def _dict_to_fundamentals(self, d: dict) -> StockFundamentals:
        """Convert cached dict back to StockFundamentals dataclass."""
        return StockFundamentals(
            stock=d.get("stock", ""),
            roe=d.get("roe", 0.0),
            debt_equity=d.get("debt_equity", 0.0),
            eps=d.get("eps", 0.0),
            pe_ratio=d.get("pe_ratio", 0.0),
            industry_pe=d.get("industry_pe", 0.0),
            has_red_flag=d.get("has_red_flag", False),
            red_flag_reasons=d.get("red_flag_reasons", []),
            fair_value_modifier=d.get("fair_value_modifier", 0),
            has_earnings_this_week=d.get("has_earnings_this_week", False),
            fetched_at=d.get("fetched_at", ""),
        )

    @staticmethod
    def _safe_float(val) -> float:
        """Safely convert to float, handling None and non-numeric values."""
        if val is None:
            return 0.0
        try:
            return float(val)
        except (ValueError, TypeError):
            return 0.0
