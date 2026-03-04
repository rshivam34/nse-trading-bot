"""
Local file cache for previous-day OHLC data.
Eliminates all historical API calls on mid-day restart.
Cache is date-stamped — auto-invalidates next trading day.
"""

import json
import logging
from pathlib import Path
from datetime import date

logger = logging.getLogger(__name__)

CACHE_FILE = Path(__file__).parent.parent / "logs" / "ohlc_cache.json"


def load_cached_ohlc() -> dict | None:
    """Load cached OHLC data if it's from today.

    Returns:
        dict: {symbol: ohlc_data} if cache is fresh, None otherwise
    """
    try:
        if CACHE_FILE.exists():
            cache = json.loads(CACHE_FILE.read_text())
            if cache.get("date") == str(date.today()):
                data = cache.get("data", {})
                logger.info(f"Loaded OHLC cache: {len(data)} stocks (from today)")
                return data
            else:
                logger.info(
                    f"OHLC cache expired (from {cache.get('date')}, today is {date.today()})"
                )
    except Exception as e:
        logger.warning(f"OHLC cache load failed: {e}")
    return None


def save_ohlc_cache(ohlc_data: dict):
    """Save OHLC data with today's date stamp.

    Args:
        ohlc_data: dict of {symbol: ohlc_data}
    """
    try:
        CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        CACHE_FILE.write_text(json.dumps({
            "date": str(date.today()),
            "stock_count": len(ohlc_data),
            "data": ohlc_data,
        }, indent=2))
        logger.info(f"Saved OHLC cache: {len(ohlc_data)} stocks")
    except Exception as e:
        logger.warning(f"OHLC cache save failed: {e}")


def clear_cache():
    """Delete cache file."""
    try:
        if CACHE_FILE.exists():
            CACHE_FILE.unlink()
            logger.info("OHLC cache cleared")
    except Exception as e:
        logger.warning(f"OHLC cache clear failed: {e}")
