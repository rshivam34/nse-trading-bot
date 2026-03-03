"""
Brokerage Calculator — All NSE Intraday Trading Charges
========================================================
This is CRITICAL for accurate P&L. Never skip charges.

NSE Intraday (MIS) charges breakdown:
- Brokerage: Rs.20 per order OR 0.03% of trade value, whichever is LESS × 2 orders
- STT (Securities Transaction Tax): 0.025% on sell-side value only
- Exchange transaction charges: 0.00345% of total turnover (buy + sell)
- GST (Goods & Services Tax): 18% on (brokerage + exchange charges)
- SEBI charges: 0.0001% of total turnover
- Stamp duty: 0.003% on buy-side value only

Why this matters at Rs.1000 capital:
- Each trade costs roughly Rs.2-4 in charges on a Rs.1000 position
- That's 0.2-0.4% per trade — significant at small capital
- We must verify expected profit > all charges before entering any trade
"""

import logging

logger = logging.getLogger(__name__)


def calculate_charges(
    entry_price: float,
    exit_price: float,
    quantity: int,
    direction: str,  # "LONG" or "SHORT"
    brokerage_flat: float = 20.0,
    brokerage_pct: float = 0.03,
) -> dict:
    """
    Calculate ALL charges for a round-trip intraday NSE trade.

    Args:
        entry_price: Price at which we entered the trade
        exit_price: Price at which we exited the trade
        quantity: Number of shares
        direction: "LONG" (buy first, sell later) or "SHORT" (sell first, buy later)
        brokerage_flat: Flat brokerage per order (default Rs.20 — Angel One)
        brokerage_pct: Percentage brokerage per order (default 0.03%)

    Returns:
        dict with keys:
        - brokerage: Total brokerage (both legs)
        - stt: Securities Transaction Tax
        - exchange_charges: Exchange transaction fees
        - gst: GST on brokerage + exchange charges
        - sebi_charges: SEBI regulatory fees
        - stamp_duty: Stamp duty on buy side
        - total_charges: Sum of all the above
        - gross_pnl: P&L before charges
        - net_pnl: P&L after all charges
        - effective_cost_pct: Total charges as % of trade value

    Example (LONG trade):
        Entry: Rs.1000, Exit: Rs.1015, Qty: 10
        Trade value: Rs.10,000 (buy side)
        Exit value: Rs.10,150 (sell side)
        Turnover: Rs.20,150

        Brokerage: min(Rs.20, 0.03% × 10000=Rs.3) = Rs.3 per leg → Rs.6 total
        STT: 0.025% × 10,150 = Rs.2.54
        Exchange: 0.00345% × 20,150 = Rs.0.70
        GST: 18% × (6 + 0.70) = Rs.1.21
        SEBI: 0.0001% × 20,150 = Rs.0.02
        Stamp: 0.003% × 10,000 = Rs.0.30
        Total: Rs.10.77
        Gross P&L: Rs.150
        Net P&L: Rs.139.23
    """
    if quantity <= 0 or entry_price <= 0:
        return _empty_charges()

    # Determine buy and sell values based on direction
    buy_value = entry_price * quantity   # Buy side
    sell_value = exit_price * quantity   # Sell side
    turnover = buy_value + sell_value    # Total round-trip

    # ── Brokerage ──────────────────────────────────────────────────────
    # Angel One: min(Rs.20, 0.03% of trade value) per leg
    brokerage_by_pct = buy_value * (brokerage_pct / 100)
    brokerage_per_leg = min(brokerage_flat, brokerage_by_pct)
    brokerage_total = brokerage_per_leg * 2  # Buy leg + Sell leg

    # ── STT (Securities Transaction Tax) ──────────────────────────────
    # Intraday: 0.025% on the SELL SIDE only
    stt = sell_value * 0.00025

    # ── Exchange Transaction Charges ──────────────────────────────────
    # 0.00345% of total turnover (NSE)
    exchange_charges = turnover * 0.0000345

    # ── GST ────────────────────────────────────────────────────────────
    # 18% on (brokerage + exchange charges) — government tax on services
    gst = (brokerage_total + exchange_charges) * 0.18

    # ── SEBI Charges ───────────────────────────────────────────────────
    # Rs.10 per crore of turnover = 0.0001% of turnover
    sebi_charges = turnover * 0.000001

    # ── Stamp Duty ─────────────────────────────────────────────────────
    # 0.003% of BUY side only (equity delivery is higher, but intraday is 0.003%)
    stamp_duty = buy_value * 0.00003

    # ── Total ───────────────────────────────────────────────────────────
    total_charges = (
        brokerage_total + stt + exchange_charges + gst + sebi_charges + stamp_duty
    )

    # ── P&L ─────────────────────────────────────────────────────────────
    if direction == "LONG":
        gross_pnl = (exit_price - entry_price) * quantity
    else:
        gross_pnl = (entry_price - exit_price) * quantity

    net_pnl = gross_pnl - total_charges

    # Cost as percentage of trade value (useful for benchmarking)
    effective_cost_pct = (total_charges / buy_value) * 100 if buy_value > 0 else 0

    return {
        "brokerage": round(brokerage_total, 4),
        "stt": round(stt, 4),
        "exchange_charges": round(exchange_charges, 4),
        "gst": round(gst, 4),
        "sebi_charges": round(sebi_charges, 6),
        "stamp_duty": round(stamp_duty, 4),
        "total_charges": round(total_charges, 4),
        "gross_pnl": round(gross_pnl, 4),
        "net_pnl": round(net_pnl, 4),
        "effective_cost_pct": round(effective_cost_pct, 4),
    }


def expected_net_profit(
    entry_price: float,
    target_price: float,
    quantity: int,
    direction: str,
) -> float:
    """
    Calculate expected net profit at target price, after ALL charges.

    Used before placing a trade to verify it's worth it.
    If this returns < config.min_expected_net_profit (Rs.5), skip the trade.

    Args:
        entry_price: Our planned entry price
        target_price: Our planned target (exit) price
        quantity: Planned position size
        direction: "LONG" or "SHORT"

    Returns:
        Expected net profit in Rs. (negative = net loss even at target)
    """
    result = calculate_charges(entry_price, target_price, quantity, direction)
    return result["net_pnl"]


def is_trade_viable(
    entry_price: float,
    target_price: float,
    quantity: int,
    direction: str,
    min_profit: float = 5.0,
) -> tuple[bool, float]:
    """
    Check if a trade is worth executing after charges.

    Returns:
        (is_viable, expected_net_profit)
        is_viable = True if expected net profit >= min_profit
    """
    net = expected_net_profit(entry_price, target_price, quantity, direction)
    return net >= min_profit, round(net, 2)


def format_charges_summary(charges: dict) -> str:
    """Format charges dict as a human-readable string for logging."""
    return (
        f"Charges: Rs.{charges['total_charges']:.2f} | "
        f"Brokerage: Rs.{charges['brokerage']:.2f}, "
        f"STT: Rs.{charges['stt']:.2f}, "
        f"Exchange: Rs.{charges['exchange_charges']:.2f}, "
        f"GST: Rs.{charges['gst']:.2f}, "
        f"Stamp: Rs.{charges['stamp_duty']:.2f} | "
        f"Gross: Rs.{charges['gross_pnl']:.2f}, "
        f"Net: Rs.{charges['net_pnl']:.2f}"
    )


def _empty_charges() -> dict:
    """Return zeroed charges dict for invalid inputs."""
    return {
        "brokerage": 0.0, "stt": 0.0, "exchange_charges": 0.0,
        "gst": 0.0, "sebi_charges": 0.0, "stamp_duty": 0.0,
        "total_charges": 0.0, "gross_pnl": 0.0, "net_pnl": 0.0,
        "effective_cost_pct": 0.0,
    }
