"""
Pre-filters the watchlist by capital before any expensive historical API calls.

Uses the fast LTP/MarketData API (10 req/sec) to get current prices,
then filters out stocks that are:
1. Too expensive to buy even 1 share
2. Too expensive relative to capital for brokerage to make sense

This typically reduces 193 stocks -> 40-60 at Rs.1K capital,
saving 70%+ of historical API calls.
"""

import logging
import time

logger = logging.getLogger(__name__)


def calculate_trade_viability(
    stock_price: float,
    capital: float,
    min_net_profit: float = 10.0,
) -> tuple[bool, str, dict]:
    """Check if trading this stock can realistically profit after all charges.

    Angel One Intraday charges:
    - Brokerage: min(Rs.20, 0.1% of trade value) per order, minimum Rs.5/order
    - STT: 0.025% on sell side
    - Exchange txn: 0.00297% both sides
    - GST: 18% on (brokerage + exchange charges)
    - SEBI fee + stamp: ~0.003%

    Args:
        stock_price: Current LTP
        capital: Available trading capital
        min_net_profit: Minimum acceptable profit in Rs. (default Rs.10)

    Returns:
        tuple: (is_viable, reason, details)
    """
    if stock_price <= 0 or capital <= 0:
        return False, "invalid price or capital", {}

    # Buffer: don't use 100% of capital (price can move up before order fills)
    usable_capital = capital * 0.95

    if stock_price > usable_capital:
        return False, f"price Rs.{stock_price:.0f} > capital Rs.{usable_capital:.0f}", {}

    qty = int(usable_capital // stock_price)
    if qty < 1:
        return False, "cannot buy even 1 share", {}

    position_value = qty * stock_price

    # Brokerage per order: min(Rs.20, 0.1% of value), minimum Rs.5
    brokerage_per_order = max(5.0, min(20.0, position_value * 0.001))
    total_brokerage = brokerage_per_order * 2  # buy + sell

    # Other charges
    stt = position_value * 0.00025                      # 0.025% sell side
    exchange_txn = position_value * 0.0000297 * 2       # both sides
    gst = (total_brokerage + exchange_txn) * 0.18       # 18% GST
    stamp_duty = position_value * 0.00003                # 0.003% stamp duty

    total_charges = total_brokerage + stt + exchange_txn + gst + stamp_duty

    # Required price move to achieve min_net_profit
    required_profit = total_charges + min_net_profit
    required_move_pct = (required_profit / position_value) * 100

    details = {
        "qty": qty,
        "position_value": round(position_value, 2),
        "total_charges": round(total_charges, 2),
        "required_move_pct": round(required_move_pct, 2),
        "brokerage": round(total_brokerage, 2),
    }

    # Intraday stocks typically move 1-3%. If we need >3%, it's unrealistic.
    if required_move_pct > 3.0:
        return False, f"needs {required_move_pct:.1f}% move (charges Rs.{total_charges:.0f})", details

    return True, f"viable: {qty} shares, needs {required_move_pct:.1f}% move", details


def filter_stocks_by_capital(
    smart_api,
    watchlist: list[dict],
    capital: float,
    ltp_limiter,
) -> tuple[list[dict], list[tuple], dict]:
    """Filter watchlist to only stocks that are affordable AND profitable to trade.

    Uses getMarketData LTP mode (fast: 10 req/sec, 500/min).

    Args:
        smart_api: Authenticated SmartConnect instance
        watchlist: List of stock dicts with 'token' and 'symbol' keys
        capital: Available trading capital in Rs.
        ltp_limiter: RateLimiter instance for LTP API

    Returns:
        tuple: (affordable_stocks, skipped_stocks, ltp_cache)
            - affordable_stocks: filtered list of stock dicts
            - skipped_stocks: list of (symbol, price, reason) tuples
            - ltp_cache: dict of {symbol: ltp} for use later
    """
    affordable: list[dict] = []
    skipped: list[tuple] = []
    ltp_cache: dict[str, float] = {}

    logger.info(f"Filtering {len(watchlist)} stocks by capital Rs.{capital:,.0f}...")

    for i, stock in enumerate(watchlist):
        symbol = stock.get("symbol", "UNKNOWN")
        token = stock.get("token", "")

        try:
            ltp_limiter.wait()  # Rate limiter

            data = smart_api.getMarketData(
                mode="LTP",
                exchangeTokens={"NSE": [str(token)]},
            )

            if data and data.get("status") and data.get("data", {}).get("fetched"):
                ltp = float(data["data"]["fetched"][0]["ltp"])
                ltp_cache[symbol] = ltp

                viable, reason, details = calculate_trade_viability(ltp, capital)

                if viable:
                    stock["ltp"] = ltp
                    stock["trade_details"] = details
                    affordable.append(stock)
                else:
                    skipped.append((symbol, ltp, reason))
            else:
                # If LTP fetch fails, exclude stock (fail-closed — don't risk unaffordable stocks)
                logger.warning(f"LTP fetch returned no data for {symbol}, excluding")
                skipped.append((symbol, 0, "LTP fetch failed — no data"))

        except Exception as e:
            logger.warning(f"LTP fetch failed for {symbol}: {e}, excluding")
            skipped.append((symbol, 0, f"LTP fetch error: {e}"))
            time.sleep(2.0)  # extra pause on error

        # Progress log every 50 stocks
        if (i + 1) % 50 == 0:
            logger.info(
                f"Capital filter progress: {i + 1}/{len(watchlist)} "
                f"({len(affordable)} affordable so far)"
            )

    logger.info(
        f"Capital filter complete: {len(affordable)} affordable, "
        f"{len(skipped)} skipped out of {len(watchlist)} total"
    )

    # Log some example skipped stocks (first 10)
    if skipped:
        examples = skipped[:10]
        for sym, price, reason in examples:
            logger.info(f"  Skipped: {sym} @ Rs.{price:.0f} -- {reason}")
        if len(skipped) > 10:
            logger.info(f"  ... and {len(skipped) - 10} more")

    return affordable, skipped, ltp_cache
