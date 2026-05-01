"""
Angel One Historical Data Fetcher — 12 months of 5-min bars
=============================================================
One-time pull: NIFTY + BANKNIFTY + 30 NIFTY 50 stocks × 12 months × 5-min bars.

Why this exists:
  yfinance limits 5-min data to last 60 days. To backtest the intraday
  bot over 12 months (covering both war/crisis AND normal-VIX months),
  we need Angel One's historical API which goes back ~10 years.

Angel One historical API limits:
  - 5-min candles: max 30 days per request
  - Rate limit: 3/sec (we use 1/sec to be safe)
  - Auth: TOTP-based, ~24-hour token

Strategy:
  - Loop through 12 calendar months × 32 symbols = 384 API calls
  - 1 sec between calls = ~7 minutes total
  - Save each symbol's full 12-month dataframe to logs/historical_5min/{SYMBOL}.pkl
  - Re-runs check existing cache; only fetch missing pieces

Usage:
  cd C:\\Users\\rshiv\\nse-trading-bot\\backend
  python fetch_angel_historical.py

Pre-requisites:
  - .env has ANGEL_API_KEY, ANGEL_CLIENT_ID, ANGEL_PASSWORD, ANGEL_TOTP_SECRET
  - Internet + Angel One service up
  - Run during non-market hours to avoid load on broker
"""

import json
import logging
import os
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import pyotp

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(message)s")
logger = logging.getLogger(__name__)
for noisy in ["smartapi", "urllib3", "websocket"]:
    logging.getLogger(noisy).setLevel(logging.WARNING)

# Add backend/ to path so we can import existing modules
sys.path.insert(0, str(Path(__file__).parent))
from config import config
from SmartApi import SmartConnect
from utils.watchlist import lookup_token_for_symbol

# ===================== Settings =====================
CACHE_DIR = Path("logs/historical_5min")
CACHE_DIR.mkdir(parents=True, exist_ok=True)

# 12-month window (today back 1 year)
END_DATE = datetime.now().date()  # today
START_DATE = END_DATE - timedelta(days=380)  # ~12.5 months back to ensure full year

# Chunk size — Angel One 5-min API limit is 30 days
CHUNK_DAYS = 28
RATE_LIMIT_DELAY = 1.0  # seconds between API calls (well under 3/sec limit)

# Stocks to fetch — top 30 NIFTY 50 by liquidity
STOCKS = [
    "RELIANCE", "TCS", "HDFCBANK", "INFY", "ICICIBANK",
    "HINDUNILVR", "SBIN", "BHARTIARTL", "ITC", "KOTAKBANK",
    "LT", "AXISBANK", "ASIANPAINT", "MARUTI", "TATAMOTORS",
    "SUNPHARMA", "TITAN", "BAJFINANCE", "WIPRO", "HCLTECH",
    "TATASTEEL", "NTPC", "POWERGRID", "ONGC", "JSWSTEEL",
    "TECHM", "ULTRACEMCO", "NESTLEIND", "M&M", "BPCL",
]

# Indices for F&O backtest
INDICES = [
    {"symbol": "NIFTY", "token": "99926000", "exchange": "NSE"},
    {"symbol": "BANKNIFTY", "token": "99926009", "exchange": "NSE"},
]


def authenticate() -> SmartConnect:
    """Authenticate with Angel One using TOTP from .env."""
    cfg = config.broker
    if not all([cfg.api_key, cfg.client_id, cfg.password, cfg.totp_secret]):
        raise RuntimeError("Missing Angel One credentials in .env")

    api = SmartConnect(api_key=cfg.api_key, timeout=30)
    totp = pyotp.TOTP(cfg.totp_secret).now()
    response = api.generateSession(
        clientCode=cfg.client_id,
        password=cfg.password,
        totp=totp,
    )

    if not response or not response.get("status"):
        msg = response.get("message", "Unknown") if response else "No response"
        raise RuntimeError(f"Authentication failed: {msg}")

    logger.info(f"Authenticated as {cfg.client_id}")
    return api


def fetch_chunk(api: SmartConnect, token: str, exchange: str, from_date: datetime,
                to_date: datetime, max_retries: int = 2) -> list:
    """
    Fetch one chunk (max 30 days) of 5-min candles.
    Returns list of [timestamp_str, open, high, low, close, volume] arrays.
    """
    params = {
        "exchange": exchange,
        "symboltoken": str(token),
        "interval": "FIVE_MINUTE",
        "fromdate": from_date.strftime("%Y-%m-%d %H:%M"),
        "todate": to_date.strftime("%Y-%m-%d %H:%M"),
    }

    for attempt in range(max_retries + 1):
        try:
            response = api.getCandleData(params)
            if response and response.get("status"):
                return response.get("data", []) or []

            # Check for rate limit
            err = str(response.get("message", "")).upper() if response else ""
            if "AB1004" in err or "TOO MANY" in err or "RATE LIMIT" in err:
                if attempt < max_retries:
                    delay = (attempt + 1) * 5  # 5s, 10s
                    logger.warning(f"  Rate limited, waiting {delay}s...")
                    time.sleep(delay)
                    continue
            else:
                logger.debug(f"  Non-rate-limit error: {err}")
                return []
        except Exception as e:
            if attempt < max_retries:
                delay = (attempt + 1) * 3
                logger.warning(f"  Exception: {e}. Retrying in {delay}s...")
                time.sleep(delay)
            else:
                logger.error(f"  Failed after {max_retries+1} attempts: {e}")
                return []

    return []


def parse_candles_to_df(raw_candles: list) -> pd.DataFrame:
    """Convert Angel One candle array to pandas DataFrame."""
    if not raw_candles:
        return pd.DataFrame()

    rows = []
    for c in raw_candles:
        try:
            # Angel One timestamp: "2026-04-25T15:25:00+05:30"
            ts_str = c[0]
            if "+" in ts_str:
                ts_clean = ts_str.rsplit("+", 1)[0]
            elif ts_str.endswith("Z"):
                ts_clean = ts_str[:-1]
            else:
                ts_clean = ts_str
            ts = datetime.strptime(ts_clean, "%Y-%m-%dT%H:%M:%S")
            rows.append({
                "timestamp": ts,
                "Open": float(c[1]),
                "High": float(c[2]),
                "Low": float(c[3]),
                "Close": float(c[4]),
                "Volume": int(c[5]),
            })
        except (IndexError, ValueError, TypeError):
            continue

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows)
    df.set_index("timestamp", inplace=True)
    df.sort_index(inplace=True)
    df = df[~df.index.duplicated(keep="last")]
    return df


def fetch_symbol_full_year(api: SmartConnect, symbol: str, token: str,
                           exchange: str, start: datetime, end: datetime) -> pd.DataFrame:
    """Fetch 12 months of 5-min data for one symbol via 28-day chunks."""
    all_chunks = []
    chunk_start = start

    while chunk_start < end:
        chunk_end = min(chunk_start + timedelta(days=CHUNK_DAYS), end)
        # Add market hours bounds
        chunk_from = chunk_start.replace(hour=9, minute=15)
        chunk_to = chunk_end.replace(hour=15, minute=30)

        raw = fetch_chunk(api, token, exchange, chunk_from, chunk_to)
        if raw:
            df_chunk = parse_candles_to_df(raw)
            if not df_chunk.empty:
                all_chunks.append(df_chunk)

        time.sleep(RATE_LIMIT_DELAY)
        chunk_start = chunk_end

    if not all_chunks:
        return pd.DataFrame()

    combined = pd.concat(all_chunks)
    combined = combined[~combined.index.duplicated(keep="last")]
    combined.sort_index(inplace=True)
    return combined


def fetch_all(force_refresh: bool = False) -> dict[str, pd.DataFrame]:
    """Main entry — fetch all stocks + indices, cache to disk."""
    api = authenticate()

    # Build full list to fetch: indices + stocks
    targets = []
    for idx in INDICES:
        targets.append((idx["symbol"], idx["token"], idx["exchange"]))

    logger.info(f"Looking up tokens for {len(STOCKS)} stocks...")
    for symbol in STOCKS:
        token = lookup_token_for_symbol(symbol)
        if not token:
            logger.warning(f"  Token not found for {symbol}, skipping")
            continue
        targets.append((symbol, token, "NSE"))

    logger.info(f"Total to fetch: {len(targets)} symbols")
    logger.info(f"Date range: {START_DATE} to {END_DATE}")
    logger.info(f"Chunk size: {CHUNK_DAYS} days, expected ~{12 * len(targets) * RATE_LIMIT_DELAY / 60:.1f} min")
    logger.info("")

    results = {}
    total = len(targets)
    for i, (symbol, token, exchange) in enumerate(targets, 1):
        cache_path = CACHE_DIR / f"{symbol}_5min.pkl"

        if cache_path.exists() and not force_refresh:
            try:
                df = pd.read_pickle(cache_path)
                if not df.empty and len(df) > 100:
                    logger.info(f"[{i:>3}/{total}] {symbol:<14} cached ({len(df)} bars)")
                    results[symbol] = df
                    continue
            except Exception:
                pass

        logger.info(f"[{i:>3}/{total}] {symbol:<14} fetching...")
        start_time = time.time()
        df = fetch_symbol_full_year(
            api, symbol, token, exchange,
            datetime.combine(START_DATE, datetime.min.time()),
            datetime.combine(END_DATE, datetime.min.time()),
        )

        if df.empty:
            logger.warning(f"             {symbol} returned no data!")
            continue

        df.to_pickle(cache_path)
        elapsed = time.time() - start_time
        logger.info(f"             {symbol} -> {len(df)} bars in {elapsed:.1f}s")
        results[symbol] = df

    # Logout
    try:
        api.terminateSession(config.broker.client_id)
    except Exception:
        pass

    logger.info("")
    logger.info(f"Fetch complete: {len(results)}/{total} symbols cached")
    logger.info(f"Cache dir: {CACHE_DIR.absolute()}")
    return results


def main():
    force = "--force" in sys.argv
    if force:
        logger.info("FORCE refresh requested — re-downloading all symbols")

    results = fetch_all(force_refresh=force)

    # Print summary
    logger.info("")
    logger.info("=" * 60)
    logger.info("CACHE SUMMARY")
    logger.info("=" * 60)
    for symbol, df in sorted(results.items()):
        if df.empty:
            logger.info(f"  {symbol:<14} EMPTY")
        else:
            logger.info(
                f"  {symbol:<14} {len(df):>6} bars | "
                f"{df.index.min().strftime('%Y-%m-%d')} -> {df.index.max().strftime('%Y-%m-%d')}"
            )


if __name__ == "__main__":
    main()
