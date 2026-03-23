"""
Signal Scorer — 0-100 Confidence Score for Every Signal
=========================================================
Only signals scoring 80+ get executed (Sniper Mode V2 threshold).

Point breakdown (max 115 before cap at 100):
- ORB breakout:                +15 (strategy already identified a range breakout)
- VWAP aligned:                +15 (long above VWAP / short below)
- Volume spike (>2×):          +10 (real buying/selling pressure)
- Volume spike (>5×):          +20 (institutional-level volume — replaces 2× bonus)
- RSI confirmation:            +10 (not overbought entering long / not oversold entering short)
- NIFTY direction aligned:     +15 (market is moving with us, not against us)
- EMA alignment (9 above 21):  +10 (short-term trend confirmed by EMAs)
- Price vs prev day close:     +5  (above prev close for longs, below for shorts)
- News sentiment aligned:      +10 (positive news for longs, negative for shorts)
- Away from prev day levels:   +5  (not at known support/resistance)
- Time-of-day bonus:           +5  (in high-probability window 9:30-11:30 or 1:00-2:30)
- India VIX < 15:              +5  (low fear environment = cleaner trends)

Score zones:
- 80-89: Excellent — trade it (minimum threshold, Sniper Mode V2)
- 90-100: Exceptional — best setups of the day

This scoring ensures we only trade when multiple conditions align,
not just when one indicator fires a signal.
"""

import logging
from datetime import datetime, time
from typing import Optional

logger = logging.getLogger(__name__)


class SignalScorer:
    """
    Evaluates any Signal against current market conditions.
    Returns a score (0-100) and a detailed breakdown dict.
    """

    def score(
        self,
        signal,                  # Signal dataclass from base_strategy.py
        market_context: dict,    # Enriched context from scanner._build_stock_context()
        news_sentiment: dict,    # {symbol: {sentiment, score, skip_today}}
        macro_data=None,         # MacroData from macro_analysis.py (optional)
        sector_data=None,        # {sector_name: SectorStrength} (optional)
        fundamental_data=None,   # {stock: StockFundamentals} (optional)
    ) -> tuple[int, dict]:
        """
        Score a signal from 0-100.

        Args:
            signal: The Signal to evaluate
            market_context: Per-stock enriched context (VWAP, RSI, VIX, regime, etc.)
            news_sentiment: News sentiment cache from NewsSentimentFetcher.fetch_all()

        Returns:
            (total_score, breakdown_dict)
            breakdown_dict shows which factors contributed and how many points
        """
        breakdown: dict[str, int] = {}
        direction = signal.direction

        # ── ORB BREAKOUT ────────────────────────────────────────────────
        if signal.strategy_name == "ORB":
            breakdown["orb_breakout"] = 15
        else:
            breakdown["orb_breakout"] = 0

        # ── VWAP ALIGNMENT ──────────────────────────────────────────────
        vwap = market_context.get("vwap", 0)
        ltp = signal.entry_price
        if vwap > 0:
            above_vwap = ltp > vwap
            if (direction == "LONG" and above_vwap) or (direction == "SHORT" and not above_vwap):
                breakdown["vwap_aligned"] = 15
            else:
                breakdown["vwap_aligned"] = 0
        else:
            breakdown["vwap_aligned"] = 5  # No VWAP data — partial credit

        # ── VOLUME SPIKE ────────────────────────────────────────────────
        vol_ratio = market_context.get("volume_ratio", 1.0)
        if vol_ratio >= 5.0:
            breakdown["volume_spike"] = 20  # Institutional-level volume
        elif vol_ratio >= 2.0:
            breakdown["volume_spike"] = 10  # Above-average volume
        else:
            breakdown["volume_spike"] = 0   # Weak volume — no bonus

        # ── RSI CONFIRMATION ────────────────────────────────────────────
        rsi = market_context.get("rsi", 50.0)
        if direction == "LONG":
            # Don't enter long if RSI is already overbought (above 70)
            if 30 <= rsi <= 70:
                breakdown["rsi_confirm"] = 10
            elif rsi < 30:
                breakdown["rsi_confirm"] = 5   # Oversold long = contrarian risk
            else:
                breakdown["rsi_confirm"] = 0   # Overbought = already extended
        else:  # SHORT
            if 30 <= rsi <= 70:
                breakdown["rsi_confirm"] = 10
            elif rsi > 70:
                breakdown["rsi_confirm"] = 5   # Overbought short = contrarian play
            else:
                breakdown["rsi_confirm"] = 0   # Oversold = too extended

        # ── NIFTY DIRECTION ALIGNMENT ────────────────────────────────────
        nifty_dir = market_context.get("nifty_direction", "NEUTRAL")
        if (direction == "LONG" and nifty_dir == "BULLISH") or (
            direction == "SHORT" and nifty_dir == "BEARISH"
        ):
            breakdown["nifty_aligned"] = 15
        elif nifty_dir == "NEUTRAL":
            breakdown["nifty_aligned"] = 8    # Neutral is acceptable
        else:
            breakdown["nifty_aligned"] = 0    # Against market direction

        # ── EMA ALIGNMENT ───────────────────────────────────────────────
        # True if EMA9 > EMA21 for longs, EMA9 < EMA21 for shorts
        ema_aligned = market_context.get("ema_aligned", None)
        if ema_aligned is None:
            breakdown["ema_aligned"] = 5   # No data — partial credit
        elif (direction == "LONG" and ema_aligned is True) or \
             (direction == "SHORT" and ema_aligned is False):
            breakdown["ema_aligned"] = 10  # EMAs confirm trade direction
        else:
            breakdown["ema_aligned"] = 0   # EMAs against trade direction

        # ── PRICE vs PREV DAY CLOSE ──────────────────────────────────────
        prev_day = market_context.get("prev_day", {})
        prev_close = prev_day.get("prev_close", 0)
        if prev_close > 0:
            if (direction == "LONG" and ltp > prev_close) or (
                direction == "SHORT" and ltp < prev_close
            ):
                breakdown["prev_close_direction"] = 5
            else:
                breakdown["prev_close_direction"] = 0
        else:
            breakdown["prev_close_direction"] = 3   # No data — minor credit

        # ── NEWS SENTIMENT ───────────────────────────────────────────────
        stock_news = news_sentiment.get(signal.stock, {})
        sentiment = stock_news.get("sentiment", "neutral")
        if (direction == "LONG" and sentiment == "positive") or (
            direction == "SHORT" and sentiment == "negative"
        ):
            breakdown["news_sentiment"] = 10
        elif sentiment == "neutral":
            breakdown["news_sentiment"] = 4   # Neutral = no risk, minor credit
        else:
            # Opposing sentiment: negative news for long, positive for short
            breakdown["news_sentiment"] = 0

        # ── AWAY FROM PREV DAY KEY LEVELS ────────────────────────────────
        # market_context has "near_prev_levels" = True if within 0.3% of prev H/L/C
        near_levels = market_context.get("near_prev_levels", False)
        breakdown["away_from_levels"] = 0 if near_levels else 5

        # ── TIME-OF-DAY BONUS ────────────────────────────────────────────
        now = datetime.now().time()
        in_window_1 = time(9, 30) <= now <= time(11, 30)
        in_window_2 = time(13, 0) <= now <= time(14, 30)
        breakdown["time_bonus"] = 5 if (in_window_1 or in_window_2) else 0

        # ── INDIA VIX BONUS ──────────────────────────────────────────────
        vix = market_context.get("vix", 20.0)
        # VIX=0 means no data (not real) — give partial credit (3 pts) instead of 0
        if vix > 0 and vix < 15.0:
            breakdown["vix_low"] = 5
        elif vix == 0:
            breakdown["vix_low"] = 3  # No VIX data — assume normal, partial credit
        else:
            breakdown["vix_low"] = 0

        # ── MACRO ALIGNMENT (NIFTY DMA trend) ─────────────────────────────
        # +10 if signal direction aligns with NIFTY macro trend, -10 if against
        if macro_data is not None and hasattr(macro_data, 'nifty_trend'):
            nifty_trend = macro_data.nifty_trend
            if (direction == "LONG" and nifty_trend == "BULLISH") or \
               (direction == "SHORT" and nifty_trend == "BEARISH"):
                breakdown["macro_aligned"] = 10
            elif nifty_trend == "NEUTRAL":
                breakdown["macro_aligned"] = 0
            else:
                breakdown["macro_aligned"] = -10
        else:
            breakdown["macro_aligned"] = 0

        # ── SECTOR ALIGNMENT ──────────────────────────────────────────────
        # +5 for LEADING/IMPROVING sectors, -5 for WEAKENING/LAGGING
        if sector_data:
            from utils.sector_analysis import STOCK_SECTOR_MAP
            sector_name = STOCK_SECTOR_MAP.get(signal.stock, "")
            if sector_name and sector_name in sector_data:
                phase = sector_data[sector_name].phase
                if phase in ("LEADING", "IMPROVING"):
                    breakdown["sector_aligned"] = 5
                elif phase in ("WEAKENING", "LAGGING"):
                    breakdown["sector_aligned"] = -5
                else:
                    breakdown["sector_aligned"] = 0
            else:
                breakdown["sector_aligned"] = 0
        else:
            breakdown["sector_aligned"] = 0

        # ── FUNDAMENTAL QUALITY (red flags + fair value) ──────────────────
        # -10 for red flags (ROE<10%, D/E>2, EPS<0), ±5 for PE vs sector avg
        if fundamental_data:
            stock_fund = fundamental_data.get(signal.stock)
            if stock_fund:
                fund_score = 0
                if stock_fund.has_red_flag:
                    fund_score -= 10
                fund_score += stock_fund.fair_value_modifier
                breakdown["fundamental_quality"] = fund_score
            else:
                breakdown["fundamental_quality"] = 0
        else:
            breakdown["fundamental_quality"] = 0

        # ── COMPUTE TOTAL ─────────────────────────────────────────────────
        total = sum(breakdown.values())
        total = min(100, total)  # Cap at 100

        logger.debug(
            f"Signal score for {signal.stock} {direction}: {total}/100 | "
            f"{', '.join(f'{k}:{v}' for k, v in breakdown.items() if v > 0)}"
        )

        return total, breakdown

    def get_score_label(self, score: int) -> str:
        """Human-readable score quality label."""
        if score >= 90:
            return "EXCEPTIONAL"
        elif score >= 80:
            return "EXCELLENT"
        elif score >= 70:
            return "GOOD"
        elif score >= 60:
            return "MODERATE"
        else:
            return "WEAK"

    def get_score_color(self, score: int) -> str:
        """CSS color class for dashboard display."""
        if score >= 90:
            return "text-emerald-400"    # Bright green
        elif score >= 80:
            return "text-green-400"       # Green
        elif score >= 70:
            return "text-yellow-400"      # Yellow
        else:
            return "text-gray-400"        # Gray (shouldn't be shown, below threshold)
