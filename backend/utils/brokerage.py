"""
Brokerage Calculator — All NSE Intraday Trading Charges
========================================================
This is CRITICAL for accurate P&L. Never skip charges.

NSE Intraday (MIS) charges breakdown:
- Brokerage: max(Rs.5, min(Rs.20, 0.1% of trade value)) per order × 2 orders
  (Angel One actual formula: 0.1% of trade value, minimum Rs.5, maximum Rs.20)
- STT (Securities Transaction Tax): 0.025% on sell-side value only
- Exchange transaction charges: 0.00345% of total turnover (buy + sell)
- GST (Goods & Services Tax): 18% on (brokerage + exchange charges)
- SEBI charges: 0.0001% of total turnover
- Stamp duty: 0.003% on buy-side value only

Why this matters at Rs.1000 capital:
- Minimum brokerage is Rs.5/order → Rs.10 per round trip (both legs)
- Add STT, exchange, GST: total charges ≈ Rs.12-15 per round trip
- That's 1.2-1.5% on a Rs.1000 position — significant at small capital
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
    brokerage_pct: float = 0.1,
    brokerage_min: float = 5.0,
) -> dict:
    """
    Calculate ALL charges for a round-trip intraday NSE trade.

    Args:
        entry_price: Price at which we entered the trade
        exit_price: Price at which we exited the trade
        quantity: Number of shares
        direction: "LONG" (buy first, sell later) or "SHORT" (sell first, buy later)
        brokerage_flat: Maximum brokerage per order (default Rs.20 — Angel One cap)
        brokerage_pct: Percentage brokerage per order (default 0.1% = Angel One rate)
        brokerage_min: Minimum brokerage per order (default Rs.5 — Angel One floor)

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
        Entry: Rs.500, Exit: Rs.510, Qty: 10
        Trade value: Rs.5,000 (buy side)
        Exit value: Rs.5,100 (sell side)
        Turnover: Rs.10,100

        Brokerage: max(Rs.5, min(Rs.20, 0.1% × 5000=Rs.5)) = Rs.5 per leg → Rs.10 total
        STT: 0.025% × 5,100 = Rs.1.28
        Exchange: 0.00345% × 10,100 = Rs.0.35
        GST: 18% × (10 + 0.35) = Rs.1.86
        SEBI: 0.0001% × 10,100 = Rs.0.01
        Stamp: 0.003% × 5,000 = Rs.0.15
        Total: Rs.13.65
        Gross P&L: Rs.100
        Net P&L: Rs.86.35
    """
    if quantity <= 0 or entry_price <= 0:
        return _empty_charges()

    # Determine buy and sell values based on direction
    buy_value = entry_price * quantity   # Buy side
    sell_value = exit_price * quantity   # Sell side
    turnover = buy_value + sell_value    # Total round-trip

    # ── Brokerage ──────────────────────────────────────────────────────
    # Angel One intraday: max(Rs.5, min(Rs.20, 0.1% of trade value)) per order
    # Examples: Rs.1000 trade → 0.1%=Rs.1 → max(5, 1) = Rs.5/leg
    #           Rs.5000 trade → 0.1%=Rs.5 → max(5, 5) = Rs.5/leg
    #           Rs.15000 trade → 0.1%=Rs.15 → max(5, min(20,15)) = Rs.15/leg
    #           Rs.25000 trade → 0.1%=Rs.25 → max(5, min(20,25)) = Rs.20/leg (capped)
    brokerage_by_pct = buy_value * (brokerage_pct / 100)
    brokerage_per_leg = max(brokerage_min, min(brokerage_flat, brokerage_by_pct))
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
    min_profit: float = 15.0,
) -> tuple[bool, float]:
    """
    Check if a trade is worth executing after charges.

    min_profit default raised to Rs.15 because with Angel One's actual formula
    (min Rs.5/order), the minimum round-trip charge is Rs.10 brokerage + Rs.2-3
    STT/exchange/GST = Rs.12-15 total. Any trade that nets < Rs.15 at target
    is not worth the risk.

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
