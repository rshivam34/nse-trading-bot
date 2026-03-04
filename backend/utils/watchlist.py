"""
Watchlist — 200 Most Liquid NSE Stocks
=======================================
Covers: NIFTY 50 + NIFTY NEXT 50 + NIFTY MIDCAP 100

Token lookup:
- At startup, download the Angel One instrument master JSON
- Match each symbol to its NSE equity token
- Cache locally so restarts don't re-download unnecessarily

The instrument master JSON is from:
https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json
This file has all tradeable instruments across all exchanges.
We filter for: exch_seg=NSE, instrumenttype="" (equity), symbol ending in "-EQ".
"""

import json
import logging
import os
import time
from pathlib import Path
from typing import Optional

import requests

logger = logging.getLogger(__name__)

# Local cache file path (relative to backend/)
INSTRUMENT_CACHE_PATH = "logs/instrument_cache.json"
INSTRUMENT_CACHE_MAX_AGE_HOURS = 12  # Re-download if older than 12 hours
INSTRUMENT_MASTER_URL = (
    "https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json"
)

# ─────────────────────────────────────────────────────────────────────────────
# MASTER SYMBOL LIST — NIFTY 50 + NIFTY NEXT 50 + NIFTY MIDCAP 100
# Only symbols here; tokens are fetched dynamically from instrument master
# ─────────────────────────────────────────────────────────────────────────────

# NIFTY 50 (50 stocks)
NIFTY_50_SYMBOLS = [
    "RELIANCE", "TCS", "HDFCBANK", "INFY", "ICICIBANK",
    "HINDUNILVR", "SBIN", "BHARTIARTL", "ITC", "KOTAKBANK",
    "LT", "AXISBANK", "ASIANPAINT", "MARUTI", "TATAMOTORS",
    "SUNPHARMA", "TITAN", "BAJFINANCE", "WIPRO", "HCLTECH",
    "TATASTEEL", "NTPC", "POWERGRID", "ONGC", "JSWSTEEL",
    "ADANIENT", "TECHM", "ULTRACEMCO", "INDUSINDBK", "NESTLEIND",
    "HDFCLIFE", "SBILIFE", "BAJAJFINSV", "DIVISLAB", "CIPLA",
    "DRREDDY", "EICHERMOT", "M&M", "BPCL", "COALINDIA",
    "GRASIM", "HEROMOTOCO", "HINDALCO", "TATACONSUM", "ADANIPORTS",
    "UPL", "APOLLOHOSP", "LTIM", "BRITANNIA", "SHRIRAMFIN",
]

# NIFTY NEXT 50 (50 stocks)
NIFTY_NEXT_50_SYMBOLS = [
    "ABB", "AMBUJACEM", "ATGL", "AUBANK", "BANKBARODA",
    "BEL", "BERGEPAINT", "BOSCHLTD", "CANBK", "CHOLAFIN",
    "COLPAL", "CONCOR", "CUMMINSIND", "DLF", "DMART",
    "GAIL", "GODREJCP", "GODREJPROP", "HAL", "HAVELLS",
    "ICICIPRULI", "IDFCFIRSTB", "INDUSTOWER", "IRFC", "JINDALSTEL",
    "JUBLFOOD", "LTF", "LUPIN", "MCDOWELL-N", "MFSL",
    "MOTHERSON", "MPHASIS", "NAUKRI", "NHPC", "NMDC",
    "OBEROIRLTY", "OFSS", "PIDILITIND", "PIIND", "PNB",
    "RECLTD", "SAIL", "SIEMENS", "SRF", "SUNTV",
    "TATAPOWER", "TORNTPHARM", "TRENT", "UNIONBANK", "VBL",
]

# NIFTY MIDCAP 100 — top 100 by liquidity (selected subset of 100)
NIFTY_MIDCAP_100_SYMBOLS = [
    "AAVAS", "ABCAPITAL", "ABFRL", "ACC", "AIAENG",
    "AJANTPHARM", "ALKEM", "APLLTD", "ARE&M", "ASTRAL",
    "AUROPHARMA", "BALKRISHNA", "BANDHANBNK", "BATAINDIA", "BHARATFORG",
    "BHEL", "BIKAJI", "BLUEDART", "BRIGADE", "BSE",
    "CANFINHOME", "CARBORUNIV", "CDSL", "CESC", "CHAMBLFERT",
    "COFORGE", "CROMPTON", "CUB", "CYIENT", "DABUR",
    "DALBHARAT", "DATAPATTNS", "DEEPAKNTR", "DIXON", "ELECON",
    "EMAMILTD", "ENDURANCE", "ESCORTS", "EXIDEIND", "FEDERALBNK",
    "FINCABLES", "FINPIPE", "GLENMARK", "GNFC", "GODFRYPHLP",
    "GRINDWELL", "GSPL", "HFCL", "HINDPETRO", "HONAUT",
    "IBREALEST", "IDFC", "INDHOTEL", "INDIGO", "IOB",
    "IOLCP", "IPCALAB", "J&KBANK", "JKCEMENT", "JSL",
    "KAJARIACER", "KALPATPOWR", "KEI", "KPITTECH", "LALPATHLAB",
    "LAURUSLABS", "LICHSGFIN", "LTTS", "LUXIND", "MAHABANK",
    "MANAPPURAM", "MARICO", "MASTEK", "MCX", "METROPOLIS",
    "MINDTREE", "MGL", "MMTC", "MPHASIS", "MRPL",
    "NATIONALUM", "NAVINFLUOR", "NBCC", "NCC", "NILKAMAL",
    "NOCIL", "PCBL", "PERSISTENT", "PFIZER", "PHOENIXLTD",
    "POLYMED", "POWERINDIA", "PVRINOX", "RAJESHEXPO", "RAMCOCEM",
    "RATNAMANI", "RAYMOND", "RITES", "ROLEXRINGS", "ROUTE",
]

# All 200 symbols combined
ALL_200_SYMBOLS = NIFTY_50_SYMBOLS + NIFTY_NEXT_50_SYMBOLS + NIFTY_MIDCAP_100_SYMBOLS

# ─────────────────────────────────────────────────────────────────────────────
# INDEX TOKENS (for market context) — these are fixed and won't change
# ─────────────────────────────────────────────────────────────────────────────
INDEX_TOKENS = {
    "NIFTY_50":   {"symbol": "NIFTY 50",    "token": "99926000", "exchange": "NSE"},
    "NIFTY_BANK": {"symbol": "NIFTY BANK",  "token": "99926009", "exchange": "NSE"},
    "INDIA_VIX":  {"symbol": "India VIX",   "token": "99919000", "exchange": "NSE"},
}

# Fallback hardcoded tokens — used if instrument master download fails.
# These are confirmed Angel One NSE token IDs for NIFTY 50 stocks.
# Even if the instrument master can't be fetched, these 35 stocks will still trade.
FALLBACK_TOKENS = {
    # Top 10 by market cap
    "RELIANCE": "2885", "TCS": "11536", "HDFCBANK": "1333",
    "INFY": "1594", "ICICIBANK": "4963", "HINDUNILVR": "519",
    "SBIN": "3045", "BHARTIARTL": "10604", "ITC": "1660",
    "KOTAKBANK": "1922",
    # Next 15
    "LT": "11483", "AXISBANK": "5900", "ASIANPAINT": "236",
    "MARUTI": "10999", "TATAMOTORS": "3456", "SUNPHARMA": "3351",
    "TITAN": "3506", "BAJFINANCE": "317", "WIPRO": "3787",
    "HCLTECH": "7229", "TATASTEEL": "3499", "NTPC": "11630",
    "POWERGRID": "14977", "ONGC": "2475", "JSWSTEEL": "11723",
    # Remaining NIFTY 50
    "TECHM": "13538", "ULTRACEMCO": "2585", "INDUSINDBK": "5258",
    "NESTLEIND": "17963", "CIPLA": "694", "DRREDDY": "881",
    "M&M": "2031", "BPCL": "526", "GRASIM": "1232",
    "HEROMOTOCO": "1348",
}


def build_watchlist(use_dynamic: bool = True, max_size: int = 200) -> list[dict]:
    """
    Build the watchlist with tokens for up to max_size stocks.

    Steps:
    1. Try to load from local cache (if fresh enough)
    2. Try to download instrument master from Angel One
    3. Fall back to hardcoded tokens for known stocks

    Returns list of dicts: [{symbol, token, exchange, name}, ...]
    """
    symbol_list = ALL_200_SYMBOLS[:max_size]

    if use_dynamic:
        # Try to get tokens from instrument master
        token_map = _get_token_map_from_master()
    else:
        token_map = {}

    # Build watchlist items, falling back to hardcoded tokens
    watchlist = []
    missing = []

    for symbol in symbol_list:
        token = (
            token_map.get(symbol)
            or FALLBACK_TOKENS.get(symbol)
        )
        if token:
            watchlist.append({
                "symbol": symbol,
                "token": str(token),
                "exchange": "NSE",
                "name": symbol,  # Could enrich with full name from master
            })
        else:
            missing.append(symbol)

    if missing:
        logger.warning(
            f"No token found for {len(missing)} stocks: {missing[:10]}... "
            "These stocks will be skipped."
        )

    logger.info(
        f"Watchlist built: {len(watchlist)} stocks "
        f"(requested {len(symbol_list)}, {len(missing)} missing tokens)"
    )
    return watchlist


def _get_token_map_from_master() -> dict[str, str]:
    """
    Download (or load cached) Angel One instrument master.
    Returns {symbol: token} mapping for NSE equity stocks.
    """
    # Try local cache first
    cache_data = _load_cache()
    if cache_data:
        return cache_data

    # Download from Angel One
    logger.info("Downloading instrument master from Angel One...")
    try:
        response = requests.get(INSTRUMENT_MASTER_URL, timeout=30)
        response.raise_for_status()
        raw_data = response.json()
    except Exception as e:
        logger.warning(
            f"Instrument master download failed: {e}. "
            f"Falling back to {len(FALLBACK_TOKENS)} hardcoded NIFTY 50 tokens. "
            "Bot will trade with these stocks. Remaining watchlist stocks will be skipped."
        )
        return {}

    # Parse: each entry is [token, symbol, name, expiry, strike, lotsize,
    #                       instrumenttype, exch_seg, tick_size]
    # We want: exch_seg == "NSE" and symbol ends with "-EQ"
    token_map: dict[str, str] = {}
    count = 0

    for entry in raw_data:
        try:
            exch_seg = entry.get("exch_seg", "")
            symbol = entry.get("symbol", "")
            token = entry.get("token", "")

            if exch_seg == "NSE" and symbol.endswith("-EQ") and token:
                # Strip "-EQ" suffix to get base symbol
                base_symbol = symbol.replace("-EQ", "")
                token_map[base_symbol] = str(token)
                count += 1
        except Exception:
            continue

    logger.info(f"Parsed {count} NSE equity instruments from master")

    # Cache for next startup
    _save_cache(token_map)

    return token_map


def _load_cache() -> Optional[dict]:
    """Load token map from local cache if it's fresh enough.

    Cache is invalidated if:
    1. It's older than INSTRUMENT_CACHE_MAX_AGE_HOURS (12h), OR
    2. It's from a previous day (tokens can change when exchanges update)
    """
    try:
        cache_path = Path(INSTRUMENT_CACHE_PATH)
        if not cache_path.exists():
            return None

        # Check age
        age_hours = (time.time() - cache_path.stat().st_mtime) / 3600
        if age_hours > INSTRUMENT_CACHE_MAX_AGE_HOURS:
            logger.info(f"Instrument cache is {age_hours:.1f}h old — will re-download")
            return None

        # Check if cache is from a previous day (even if <12h old)
        from datetime import date as date_type
        cache_date = date_type.fromtimestamp(cache_path.stat().st_mtime)
        if cache_date < date_type.today():
            logger.info(
                f"Instrument cache is from {cache_date} (previous day) — "
                "will re-download for fresh tokens"
            )
            return None

        with open(cache_path) as f:
            data = json.load(f)
        logger.info(f"Loaded instrument token cache ({len(data)} symbols, {age_hours:.1f}h old)")
        return data

    except Exception as e:
        logger.debug(f"Cache load failed: {e}")
        return None


def _save_cache(token_map: dict):
    """Save token map to local cache file."""
    try:
        cache_path = Path(INSTRUMENT_CACHE_PATH)
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        with open(cache_path, "w") as f:
            json.dump(token_map, f)
        logger.debug(f"Instrument cache saved: {len(token_map)} symbols")
    except Exception as e:
        logger.debug(f"Cache save failed: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# Simple accessor functions (called from main.py / scanner)
# ─────────────────────────────────────────────────────────────────────────────

def get_watchlist(use_dynamic: bool = True, max_size: int = 200) -> list[dict]:
    """Return the active watchlist. Called at bot startup."""
    return build_watchlist(use_dynamic=use_dynamic, max_size=max_size)


def lookup_token_for_symbol(symbol: str) -> Optional[str]:
    """
    Look up the current token for a symbol from the instrument master.

    Called by broker.py before placing orders to ensure the token
    is fresh (not stale from a 12h-old cache). If the instrument
    master can't be loaded, falls back to FALLBACK_TOKENS.

    Returns the token string, or None if the symbol can't be found.
    """
    # Try instrument master first (cached or fresh download)
    token_map = _get_token_map_from_master()
    token = token_map.get(symbol)
    if token:
        return str(token)

    # Fall back to hardcoded tokens
    fallback = FALLBACK_TOKENS.get(symbol)
    if fallback:
        logger.debug(f"Using fallback token for {symbol}: {fallback}")
        return str(fallback)

    logger.warning(f"No token found for {symbol} in instrument master or fallbacks")
    return None


def get_nifty_token() -> dict:
    """Return NIFTY 50 token for market context tracking."""
    return INDEX_TOKENS["NIFTY_50"]


def get_banknifty_token() -> dict:
    """Return NIFTY BANK token."""
    return INDEX_TOKENS["NIFTY_BANK"]


def get_vix_token() -> dict:
    """Return India VIX token."""
    return INDEX_TOKENS["INDIA_VIX"]


# ─────────────────────────────────────────────────────────────────────────────
# Legacy support: original DEFAULT_WATCHLIST (used if dynamic fetch fails)
# ─────────────────────────────────────────────────────────────────────────────
DEFAULT_WATCHLIST = [
    {"symbol": s, "token": FALLBACK_TOKENS.get(s, ""), "exchange": "NSE", "name": s}
    for s in NIFTY_50_SYMBOLS[:25]
    if FALLBACK_TOKENS.get(s)
]

NIFTY_TOKEN = INDEX_TOKENS["NIFTY_50"]
