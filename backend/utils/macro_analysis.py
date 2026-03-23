"""
Macro Analysis — NIFTY DMA Trend + Market Stance System.
=========================================================

Runs once at pre-market startup. Determines:
1. NIFTY trend vs 50/200 DMA (BULLISH / NEUTRAL / BEARISH)
2. Market stance combining VIX + DMA (AGGRESSIVE / MODERATE / DEFENSIVE / CASH)

The stance controls max trades per day and position sizing dynamically.

Data source: yfinance (^NSEI for NIFTY 50 daily candles, free, no API key).
"""

import logging
from dataclasses import dataclass
from datetime import datetime

logger = logging.getLogger(__name__)


@dataclass
class MacroData:
    """Result of macro analysis — used by scanner (score modifier) and risk_manager (stance)."""
    nifty_trend: str = "NEUTRAL"        # BULLISH / NEUTRAL / BEARISH
    nifty_above_50dma: bool = False
    nifty_above_200dma: bool = False
    nifty_current: float = 0.0
    nifty_50dma: float = 0.0
    nifty_200dma: float = 0.0
    market_stance: str = "MODERATE"     # AGGRESSIVE / MODERATE / DEFENSIVE / CASH
    stance_max_trades: int = 3
    stance_size_pct: float = 100.0      # Position sizing override (0-100%)
    reason: str = ""
    timestamp: str = ""


class MacroAnalyzer:
    """
    Analyzes NIFTY 50 trend via 50/200 DMA and determines market stance.

    Usage:
        analyzer = MacroAnalyzer()
        macro = analyzer.analyze(vix=22.5)
        # macro.nifty_trend = "BULLISH"
        # macro.market_stance = "MODERATE"
    """

    def analyze(self, vix: float = 0.0) -> MacroData:
        """
        Main entry point. Fetch NIFTY daily data, compute DMAs, determine stance.

        Args:
            vix: Current India VIX value (0 = no data, uses MODERATE default).

        Returns:
            MacroData with trend, stance, and sizing parameters.
        """
        data = MacroData(timestamp=datetime.now().isoformat())

        # Step 1: Fetch NIFTY daily candles and compute DMAs
        self._fetch_nifty_dma(data)

        # Step 2: Determine market stance from VIX + DMA
        self._determine_stance(data, vix)

        return data

    def _fetch_nifty_dma(self, data: MacroData):
        """Fetch 1 year of NIFTY 50 daily candles and compute 50/200 DMA."""
        try:
            import yfinance as yf
        except ImportError:
            logger.warning("yfinance not installed — macro analysis disabled. pip install yfinance")
            return

        try:
            # Fetch 1 year of NIFTY 50 daily data
            df = yf.download("^NSEI", period="1y", interval="1d", progress=False, auto_adjust=True)

            if df is None or df.empty:
                logger.warning("No NIFTY data returned from yfinance — using NEUTRAL defaults")
                return

            # Handle MultiIndex columns (yfinance sometimes returns multi-level)
            if hasattr(df.columns, 'levels') and len(df.columns.levels) > 1:
                df.columns = df.columns.get_level_values(0)

            if "Close" not in df.columns:
                logger.warning("NIFTY data missing 'Close' column — using NEUTRAL defaults")
                return

            close = df["Close"].dropna()

            if len(close) < 200:
                logger.warning(
                    f"Only {len(close)} NIFTY daily candles (need 200 for DMA). "
                    f"50 DMA {'available' if len(close) >= 50 else 'unavailable'}."
                )

            # Current NIFTY close
            data.nifty_current = round(float(close.iloc[-1]), 2)

            # 50-day SMA
            if len(close) >= 50:
                data.nifty_50dma = round(float(close.rolling(50).mean().iloc[-1]), 2)
                data.nifty_above_50dma = data.nifty_current > data.nifty_50dma

            # 200-day SMA
            if len(close) >= 200:
                data.nifty_200dma = round(float(close.rolling(200).mean().iloc[-1]), 2)
                data.nifty_above_200dma = data.nifty_current > data.nifty_200dma

            # Determine trend
            if data.nifty_above_50dma and data.nifty_above_200dma:
                data.nifty_trend = "BULLISH"
            elif not data.nifty_above_50dma and not data.nifty_above_200dma:
                data.nifty_trend = "BEARISH"
            else:
                data.nifty_trend = "NEUTRAL"

            logger.info(
                f"NIFTY DMA: current={data.nifty_current}, "
                f"50DMA={data.nifty_50dma}, 200DMA={data.nifty_200dma}, "
                f"trend={data.nifty_trend}"
            )

        except Exception as e:
            logger.warning(f"NIFTY DMA fetch failed: {e}. Using NEUTRAL defaults.")

    def _determine_stance(self, data: MacroData, vix: float):
        """
        Combine VIX zone + NIFTY DMA trend into a single market stance.

        Stance rules (VIX >= 18 = CASH, no intermediate zones):
        - AGGRESSIVE: VIX < 18 AND above both DMAs → 5 trades, 100% size
        - MODERATE:   VIX < 18 AND below 50 DMA but above 200 → 3 trades, 100% size
        - DEFENSIVE:  VIX < 18 AND below 200 DMA → 2 trades, 50% size
        - CASH:       VIX >= 18 → 0 trades, 0% size (wars/tariffs/crises only)
        """
        reasons = []

        # VIX >= 18 = CASH (no trades at all)
        # VIX > 18 only happens during crises (Apr 2025 tariffs, May 2025 India-Pak, Mar 2026 US-Iran)
        if vix >= 18:
            data.market_stance = "CASH"
            data.stance_max_trades = 0
            data.stance_size_pct = 0.0
            data.reason = f"CASH: VIX {vix:.1f} >= 18 (crisis conditions — no trades)"
            return
        else:
            # VIX < 18 = NORMAL zone, could be AGGRESSIVE or MODERATE
            if vix > 0:
                reasons.append(f"VIX {vix:.1f} (NORMAL zone)")

        # DMA-based adjustment (can only make stance more defensive, not less)
        if data.nifty_200dma > 0:  # Have DMA data
            if not data.nifty_above_200dma:
                # Below 200 DMA = at least DEFENSIVE
                reasons.append(f"NIFTY below 200 DMA ({data.nifty_200dma:.0f})")
                if data.market_stance in ("AGGRESSIVE", "MODERATE"):
                    data.market_stance = "DEFENSIVE"
                    data.stance_max_trades = 2
                    data.stance_size_pct = 50.0
            elif not data.nifty_above_50dma:
                # Below 50 DMA but above 200 = MODERATE
                reasons.append(f"NIFTY below 50 DMA ({data.nifty_50dma:.0f})")
                if data.market_stance == "AGGRESSIVE":
                    data.market_stance = "MODERATE"
                    data.stance_max_trades = 3
                    data.stance_size_pct = 100.0
            else:
                # Above both DMAs
                reasons.append(f"NIFTY above both DMAs (bullish structure)")

        # If nothing pushed us defensive, and VIX is calm → AGGRESSIVE
        if data.market_stance == "MODERATE" and vix > 0 and vix < 18 and data.nifty_above_50dma and data.nifty_above_200dma:
            data.market_stance = "AGGRESSIVE"
            data.stance_max_trades = 5
            data.stance_size_pct = 100.0

        data.reason = f"{data.market_stance}: {', '.join(reasons) if reasons else 'defaults'}"
