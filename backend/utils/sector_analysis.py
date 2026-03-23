"""
Sector Analysis — Relative Strength & Rotation Classification.
===============================================================

Runs once at pre-market startup. Analyzes 9 NSE sector indices vs NIFTY 50
to classify sectors as LEADING / IMPROVING / WEAKENING / LAGGING.

Used by signal scorer to give +5 bonus for trades in strong sectors
and -5 penalty for trades in weak sectors.

Data source: yfinance (sector index symbols like ^CNXIT, ^NSEBANK, etc.)
"""

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


# ── 9 Sector Indices tracked via yfinance ──────────────────────────────
SECTOR_DEFINITIONS = [
    ("NIFTY IT",        "^CNXIT",      "GROWTH"),
    ("NIFTY Bank",      "^NSEBANK",    "CYCLICAL"),
    ("NIFTY Pharma",    "^CNXPHARMA",  "DEFENSIVE"),
    ("NIFTY Auto",      "^CNXAUTO",    "CYCLICAL"),
    ("NIFTY FMCG",      "^CNXFMCG",    "DEFENSIVE"),
    ("NIFTY Metal",     "^CNXMETAL",   "CYCLICAL"),
    ("NIFTY Realty",    "^CNXREALTY",   "CYCLICAL"),
    ("NIFTY Energy",    "^CNXENERGY",  "CYCLICAL"),
    ("NIFTY Financial", "^CNXFINANCE", "CYCLICAL"),
]


# ── Stock → Sector mapping for all 200 watchlist symbols ──────────────
# Each stock mapped to its primary sector index name.
# "OTHER" means no sector index tracks it closely.
STOCK_SECTOR_MAP = {
    # ── NIFTY Bank / Financial ────────────────────────────────────────
    "HDFCBANK": "NIFTY Bank", "ICICIBANK": "NIFTY Bank", "SBIN": "NIFTY Bank",
    "KOTAKBANK": "NIFTY Bank", "AXISBANK": "NIFTY Bank", "INDUSINDBK": "NIFTY Bank",
    "BANKBARODA": "NIFTY Bank", "CANBK": "NIFTY Bank", "PNB": "NIFTY Bank",
    "AUBANK": "NIFTY Bank", "IDFCFIRSTB": "NIFTY Bank", "UNIONBANK": "NIFTY Bank",
    "FEDERALBNK": "NIFTY Bank", "J&KBANK": "NIFTY Bank", "IOB": "NIFTY Bank",
    "CUB": "NIFTY Bank", "MAHABANK": "NIFTY Bank", "BANDHANBNK": "NIFTY Bank",

    # ── NIFTY Financial (NBFCs, Insurance, AMCs) ──────────────────────
    "BAJFINANCE": "NIFTY Financial", "BAJAJFINSV": "NIFTY Financial",
    "HDFCLIFE": "NIFTY Financial", "SBILIFE": "NIFTY Financial",
    "ICICIPRULI": "NIFTY Financial", "CHOLAFIN": "NIFTY Financial",
    "MFSL": "NIFTY Financial", "LTF": "NIFTY Financial",
    "SHRIRAMFIN": "NIFTY Financial", "MANAPPURAM": "NIFTY Financial",
    "LICHSGFIN": "NIFTY Financial", "CANFINHOME": "NIFTY Financial",
    "ABCAPITAL": "NIFTY Financial", "CDSL": "NIFTY Financial",
    "BSE": "NIFTY Financial", "MCX": "NIFTY Financial",

    # ── NIFTY IT ──────────────────────────────────────────────────────
    "TCS": "NIFTY IT", "INFY": "NIFTY IT", "WIPRO": "NIFTY IT",
    "HCLTECH": "NIFTY IT", "TECHM": "NIFTY IT", "LTIM": "NIFTY IT",
    "MPHASIS": "NIFTY IT", "COFORGE": "NIFTY IT", "PERSISTENT": "NIFTY IT",
    "LTTS": "NIFTY IT", "KPITTECH": "NIFTY IT", "MASTEK": "NIFTY IT",
    "CYIENT": "NIFTY IT", "NAUKRI": "NIFTY IT", "OFSS": "NIFTY IT",

    # ── NIFTY Pharma ──────────────────────────────────────────────────
    "SUNPHARMA": "NIFTY Pharma", "DIVISLAB": "NIFTY Pharma", "CIPLA": "NIFTY Pharma",
    "DRREDDY": "NIFTY Pharma", "LUPIN": "NIFTY Pharma", "TORNTPHARM": "NIFTY Pharma",
    "AUROPHARMA": "NIFTY Pharma", "ALKEM": "NIFTY Pharma", "IPCALAB": "NIFTY Pharma",
    "AJANTPHARM": "NIFTY Pharma", "GLENMARK": "NIFTY Pharma", "LALPATHLAB": "NIFTY Pharma",
    "METROPOLIS": "NIFTY Pharma", "LAURUSLABS": "NIFTY Pharma", "PFIZER": "NIFTY Pharma",
    "APOLLOHOSP": "NIFTY Pharma",

    # ── NIFTY Auto ────────────────────────────────────────────────────
    "TATAMOTORS": "NIFTY Auto", "M&M": "NIFTY Auto", "MARUTI": "NIFTY Auto",
    "EICHERMOT": "NIFTY Auto", "HEROMOTOCO": "NIFTY Auto", "BAJAJ-AUTO": "NIFTY Auto",
    "MOTHERSON": "NIFTY Auto", "BHARATFORG": "NIFTY Auto", "ESCORTS": "NIFTY Auto",
    "EXIDEIND": "NIFTY Auto", "BALKRISHNA": "NIFTY Auto", "ENDURANCE": "NIFTY Auto",
    "BOSCHLTD": "NIFTY Auto",

    # ── NIFTY FMCG ────────────────────────────────────────────────────
    "HINDUNILVR": "NIFTY FMCG", "ITC": "NIFTY FMCG", "NESTLEIND": "NIFTY FMCG",
    "BRITANNIA": "NIFTY FMCG", "TATACONSUM": "NIFTY FMCG", "GODREJCP": "NIFTY FMCG",
    "DABUR": "NIFTY FMCG", "MARICO": "NIFTY FMCG", "COLPAL": "NIFTY FMCG",
    "VBL": "NIFTY FMCG", "EMAMILTD": "NIFTY FMCG", "BIKAJI": "NIFTY FMCG",
    "JUBLFOOD": "NIFTY FMCG", "DMART": "NIFTY FMCG",

    # ── NIFTY Metal ───────────────────────────────────────────────────
    "TATASTEEL": "NIFTY Metal", "JSWSTEEL": "NIFTY Metal", "HINDALCO": "NIFTY Metal",
    "JINDALSTEL": "NIFTY Metal", "SAIL": "NIFTY Metal", "NMDC": "NIFTY Metal",
    "NATIONALUM": "NIFTY Metal", "JSL": "NIFTY Metal",

    # ── NIFTY Energy ──────────────────────────────────────────────────
    "RELIANCE": "NIFTY Energy", "ONGC": "NIFTY Energy", "BPCL": "NIFTY Energy",
    "COALINDIA": "NIFTY Energy", "NTPC": "NIFTY Energy", "POWERGRID": "NIFTY Energy",
    "GAIL": "NIFTY Energy", "TATAPOWER": "NIFTY Energy", "HINDPETRO": "NIFTY Energy",
    "ADANIENT": "NIFTY Energy", "ADANIPORTS": "NIFTY Energy",
    "NHPC": "NIFTY Energy", "IRFC": "NIFTY Energy", "RECLTD": "NIFTY Energy",
    "MGL": "NIFTY Energy", "GSPL": "NIFTY Energy", "MRPL": "NIFTY Energy",

    # ── NIFTY Realty ──────────────────────────────────────────────────
    "DLF": "NIFTY Realty", "GODREJPROP": "NIFTY Realty", "OBEROIRLTY": "NIFTY Realty",
    "BRIGADE": "NIFTY Realty", "PHOENIXLTD": "NIFTY Realty", "IBREALEST": "NIFTY Realty",

    # ── Infrastructure / Capital Goods ────────────────────────────────
    "LT": "NIFTY Financial", "SIEMENS": "NIFTY Financial",
    "ABB": "NIFTY Financial", "CUMMINSIND": "NIFTY Financial",
    "HAL": "NIFTY Financial", "BEL": "NIFTY Financial",
    "BHEL": "NIFTY Financial", "KALPATPOWR": "NIFTY Financial",
    "KEI": "NIFTY Financial", "NCC": "NIFTY Financial",
    "NBCC": "NIFTY Financial",

    # ── Cement ────────────────────────────────────────────────────────
    "ULTRACEMCO": "NIFTY Financial", "GRASIM": "NIFTY Financial",
    "AMBUJACEM": "NIFTY Financial", "ACC": "NIFTY Financial",
    "DALBHARAT": "NIFTY Financial", "JKCEMENT": "NIFTY Financial",
    "RAMCOCEM": "NIFTY Financial",

    # ── Telecom ───────────────────────────────────────────────────────
    "BHARTIARTL": "NIFTY IT", "INDUSTOWER": "NIFTY IT",

    # ── Chemicals / Specialty ─────────────────────────────────────────
    "PIDILITIND": "NIFTY FMCG", "SRF": "NIFTY FMCG",
    "DEEPAKNTR": "NIFTY FMCG", "NAVINFLUOR": "NIFTY FMCG",
    "CHAMBLFERT": "NIFTY FMCG", "GNFC": "NIFTY FMCG",
    "IOLCP": "NIFTY FMCG", "NOCIL": "NIFTY FMCG",

    # ── Consumer Durables / Retail ────────────────────────────────────
    "TITAN": "NIFTY FMCG", "ASIANPAINT": "NIFTY FMCG",
    "HAVELLS": "NIFTY FMCG", "CROMPTON": "NIFTY FMCG",
    "DIXON": "NIFTY FMCG", "TRENT": "NIFTY FMCG",
    "BATAINDIA": "NIFTY FMCG", "BERGEPAINT": "NIFTY FMCG",
    "KAJARIACER": "NIFTY FMCG", "PVRINOX": "NIFTY FMCG",
    "INDHOTEL": "NIFTY FMCG",

    # ── Miscellaneous / Others ────────────────────────────────────────
    "INDIGO": "NIFTY Auto", "CONCOR": "NIFTY Energy",
    "PIIND": "NIFTY FMCG", "UPL": "NIFTY FMCG",
    "ASTRAL": "NIFTY FMCG", "HFCL": "NIFTY IT",
    "PCBL": "NIFTY Metal", "MMTC": "NIFTY Metal",
    "SUNTV": "NIFTY FMCG", "MCDOWELL-N": "NIFTY FMCG",
}


@dataclass
class SectorStrength:
    """Sector relative strength result."""
    name: str = ""
    symbol: str = ""
    sector_type: str = ""           # GROWTH / CYCLICAL / DEFENSIVE
    return_1m: float = 0.0          # 1-month percentage return
    nifty_return_1m: float = 0.0    # NIFTY 1-month return (benchmark)
    relative_strength: float = 0.0  # sector - nifty (positive = outperforming)
    phase: str = "NEUTRAL"          # LEADING / IMPROVING / WEAKENING / LAGGING


class SectorAnalyzer:
    """
    Analyzes 9 NSE sector indices for relative strength vs NIFTY 50.

    Usage:
        analyzer = SectorAnalyzer()
        sectors = analyzer.analyze()
        # sectors["NIFTY IT"].phase = "LEADING"
        # sectors["NIFTY Metal"].phase = "LAGGING"
    """

    def analyze(self) -> dict[str, SectorStrength]:
        """
        Fetch sector data and classify each sector's rotation phase.

        Returns:
            Dict mapping sector name to SectorStrength.
            Empty dict if yfinance unavailable or all fetches fail.
        """
        try:
            import yfinance as yf
        except ImportError:
            logger.warning("yfinance not installed — sector analysis disabled")
            return {}

        # Step 1: Get NIFTY benchmark return
        nifty_return = self._get_1m_return(yf, "^NSEI", "NIFTY 50")
        if nifty_return is None:
            logger.warning("NIFTY benchmark fetch failed — sector analysis disabled")
            return {}

        # Step 2: Get each sector's return and compute relative strength
        results: dict[str, SectorStrength] = {}

        for name, symbol, sector_type in SECTOR_DEFINITIONS:
            sector_return = self._get_1m_return(yf, symbol, name)
            if sector_return is None:
                continue

            rs = sector_return - nifty_return

            # Classify phase based on relative strength
            if rs > 2.0:
                phase = "LEADING"
            elif rs > 0.0:
                phase = "IMPROVING"
            elif rs > -2.0:
                phase = "WEAKENING"
            else:
                phase = "LAGGING"

            results[name] = SectorStrength(
                name=name,
                symbol=symbol,
                sector_type=sector_type,
                return_1m=round(sector_return, 2),
                nifty_return_1m=round(nifty_return, 2),
                relative_strength=round(rs, 2),
                phase=phase,
            )

        # Log summary
        if results:
            leading = [s.name for s in results.values() if s.phase == "LEADING"]
            lagging = [s.name for s in results.values() if s.phase == "LAGGING"]
            logger.info(
                f"Sector analysis: {len(results)} sectors classified. "
                f"LEADING: {leading or 'none'}. LAGGING: {lagging or 'none'}."
            )

        return results

    def _get_1m_return(self, yf, symbol: str, name: str) -> float | None:
        """Fetch 2 months of daily data and compute 1-month return."""
        try:
            df = yf.download(symbol, period="2mo", interval="1d", progress=False, auto_adjust=True)
            if df is None or df.empty or len(df) < 20:
                logger.debug(f"Insufficient data for {name} ({symbol})")
                return None

            # Handle MultiIndex columns
            if hasattr(df.columns, 'levels') and len(df.columns.levels) > 1:
                df.columns = df.columns.get_level_values(0)

            close = df["Close"].dropna()
            if len(close) < 20:
                return None

            # 1-month return: compare latest close to close ~22 trading days ago
            current = float(close.iloc[-1])
            month_ago = float(close.iloc[-22]) if len(close) >= 22 else float(close.iloc[0])
            return ((current - month_ago) / month_ago) * 100

        except Exception as e:
            logger.debug(f"Sector fetch failed for {name}: {e}")
            return None

    @staticmethod
    def get_stock_sector(stock: str) -> str:
        """Look up sector for a stock symbol. Returns empty string if not mapped."""
        return STOCK_SECTOR_MAP.get(stock, "")
