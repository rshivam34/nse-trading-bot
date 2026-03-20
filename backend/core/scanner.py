"""
Pattern Scanner — Sniper Mode V2 + TOD Volume Profile
=======================================================
The scanner is the "brain" that coordinates pattern detection
across the watchlist using all active strategies.

Volume Analysis (upgraded):
- RVOL uses 10-day TOD (time-of-day) average instead of intraday rolling average
- Compares current candle volume to the SAME time slot over the last 10 days
- Falls back to session running average (3x gate) if < 5 days of TOD data
- Expiry day flag: raises RVOL gate from 2x to 3x on F&O Thursdays
- ADV filter: rejects stocks with < 5 lakh average daily volume (20-day)
- Price confirmation: triggering candle must show 0.3% move + 60% body ratio
- Min traded value: candle must have ≥ ₹5 lakh traded value (price × volume)
- NIFTY volume spike: flags signal as macro-driven if NIFTY RVOL >= 2x TOD

Other filters (unchanged):
- Choppiness Index: CHOP > 70 = reject (market is choppy)
- 15-minute trend: must align with signal direction
- ATR expansion: -10 score penalty if ATR compressing on breakouts
- Candle close confirmation: breakout strategies require candle close above level
- Lunch block: 11:30-13:00 fully blocked for new entries
- All signals logged with status tags: EXECUTED/QUEUED/SKIPPED-*

Flow:
1. During 9:15-9:30 (ORB period): track high/low for each stock
2. After 9:30: run ALL strategies on every incoming tick
3. Pick best signal (highest confidence) — no confluence gate
4. Apply sniper filters: lunch, VIX, choppiness, trend, ADV, RVOL,
   price confirmation, traded value, candle close
5. Score surviving signals, apply ATR expansion penalty
6. Check NIFTY volume spike (flag only, not reject)
7. Return at most 1 signal (highest scoring)
"""

import logging
import time
from datetime import datetime
from typing import Optional

import pandas as pd

from strategies.base_strategy import Signal
from strategies.orb_strategy import ORBStrategy
from strategies.vwap_strategy import VWAPBounceStrategy
from strategies.ema_strategy import EMACrossoverStrategy
from strategies.sr_breakout_strategy import SRBreakoutStrategy
from utils.indicators import (
    get_current_atr,
    get_current_choppiness,
    get_15min_trend,
    is_atr_expanding,
)
from utils.volume_profile import current_time_slot, is_expiry_day

logger = logging.getLogger(__name__)


class PatternScanner:
    """Scans watchlist stocks for trading patterns — Sniper Mode V2."""

    def __init__(self, trading_config, indicator_config):
        self.trading_config = trading_config
        self.indicator_config = indicator_config

        # Token → symbol mappings
        self.token_to_symbol: dict[str, str] = {}
        self.token_to_trading_symbol: dict[str, str] = {}

        # All 4 active strategies
        self.strategies = [
            ORBStrategy(trading_config),
            VWAPBounceStrategy(trading_config, indicator_config),
            EMACrossoverStrategy(trading_config, indicator_config),
            SRBreakoutStrategy(trading_config, indicator_config),
        ]

        # Price data: token → list of ticks (ring buffer, last 500)
        self.tick_buffer: dict[str, list] = {}

        # Completed 5-minute candles per token (built from tick LTP data)
        self.candle_store: dict[str, list[dict]] = {}
        # Track current candle window start per token
        self._candle_window_start: dict[str, float] = {}
        # Ticks in the current (incomplete) 5-min window per token
        self._current_window_ticks: dict[str, list] = {}

        # Completed 5-minute NIFTY candles
        self.nifty_candle_store: list[dict] = []
        self._nifty_candle_window_start: float = 0.0
        self._nifty_current_window_ticks: list = []

        # ORB range tracking (high/low during 9:15-9:30)
        self.orb_highs: dict[str, float] = {}
        self.orb_lows: dict[str, float] = {}

        # Global market context (NIFTY + VIX, updated by update_market_context)
        self.market_context = {
            "nifty_direction": "NEUTRAL",
            "nifty_ltp": 0.0,
            "vix": 0.0,
            "nifty_choppiness": 50.0,
            "vix_regime": "NORMAL",
        }

        # NIFTY tick buffer for computing NIFTY choppiness
        self.nifty_tick_buffer: list[dict] = []

        # Per-stock prev day levels (loaded at startup)
        self.prev_day_levels: dict[str, dict] = {}

        # Already signaled today (one signal per stock per day)
        self.signals_today: set = set()

        # News sentiment cache (populated at 9 AM)
        self.news_sentiment: dict[str, dict] = {}

        # Signal scorer
        from core.signal_scorer import SignalScorer
        self.scorer = SignalScorer()

        # All signals generated this scan cycle (for queue/ranking)
        self._all_signals_today: list[Signal] = []

        # Volume profile manager (set via set_volume_profile)
        self.volume_profile = None

        # Track starting slot index per token for end-of-day profile save
        # 0 = candle_store starts from 09:15 (pre-seeded), higher for late starts
        self._candle_start_slot_index: dict[str, int] = {}
        self._nifty_start_slot_index: int = 0

        # Cache expiry day check (computed once per day)
        self._is_expiry_day: bool = is_expiry_day()

    def set_watchlist(self, watchlist: list[dict]):
        """Build token → symbol map from watchlist."""
        for item in watchlist:
            token = item["token"]
            symbol = item["symbol"]
            self.token_to_symbol[token] = symbol
            self.token_to_trading_symbol[token] = f"{symbol}-EQ"

        logger.info(f"Scanner loaded {len(self.token_to_symbol)} symbols")

    def set_prev_day_levels(self, prev_day_by_token: dict[str, dict]):
        """Load prev day OHLC for all stocks (called at startup)."""
        self.prev_day_levels = prev_day_by_token
        logger.info(f"Prev day levels loaded for {len(prev_day_by_token)} stocks")

    def set_news_sentiment(self, sentiment: dict[str, dict]):
        """Set news sentiment cache (called at 9 AM)."""
        self.news_sentiment = sentiment
        logger.info(f"News sentiment set for {len(sentiment)} stocks")

    def set_volume_profile(self, volume_profile):
        """Set volume profile manager for TOD RVOL calculations."""
        self.volume_profile = volume_profile
        logger.info("Volume profile manager connected to scanner")

    def seed_candles(self, token: str, candles: list[dict]):
        """
        Pre-seed candle history for a stock from historical API data.

        Called at startup to give strategies immediate access to enough
        candles for indicators (ATR needs 14, EMA needs 22, Choppiness needs 14).
        After seeding, the next WebSocket tick continues seamlessly —
        it starts a new 5-min window while the historical candles persist.

        Args:
            token: Instrument token string (e.g., "3045")
            candles: List of completed 5-min candle dicts
                     [{Open, High, Low, Close, Volume}, ...]
        """
        if not candles:
            return

        self.candle_store[token] = list(candles)
        # Set window start to now — next tick starts a fresh 5-min window
        self._candle_window_start[token] = time.time()
        self._current_window_ticks[token] = []
        # Pre-seeded candles start from 09:15 (slot index 0)
        self._candle_start_slot_index[token] = 0

    def seed_nifty_candles(self, candles: list[dict]):
        """
        Pre-seed NIFTY candle history for choppiness calculation.

        Without pre-seeding, NIFTY choppiness defaults to 50.0 until
        ~75 minutes of ticks accumulate (15 candles × 5 min each).
        With pre-seeding, it's accurate from the first NIFTY tick.

        Args:
            candles: List of completed 5-min NIFTY candle dicts
        """
        if not candles:
            return

        self.nifty_candle_store = list(candles)
        self._nifty_candle_window_start = time.time()
        self._nifty_current_window_ticks = []
        # Pre-seeded NIFTY candles start from 09:15
        self._nifty_start_slot_index = 0

    def update_orb_range(self, tick: dict):
        """Called during 9:15-9:30 to track the opening range."""
        token = tick["token"]
        ltp = tick["ltp"]

        if token not in self.orb_highs:
            self.orb_highs[token] = ltp
            self.orb_lows[token] = ltp
        else:
            self.orb_highs[token] = max(self.orb_highs[token], ltp)
            self.orb_lows[token] = min(self.orb_lows[token], ltp)

        stock = self.token_to_symbol.get(token, token)
        for strat in self.strategies:
            if isinstance(strat, ORBStrategy):
                strat.set_orb_range(
                    stock=stock,
                    high=self.orb_highs[token],
                    low=self.orb_lows[token],
                )

    def reconstruct_orb_ranges(self) -> int:
        """
        Reconstruct ORB ranges from pre-seeded historical candles.

        Called on late starts (after 9:30 AM) when the live ORB observation
        window was missed. Uses the first 3 candles in candle_store
        (= the 9:15-9:20, 9:20-9:25, 9:25-9:30 windows) to compute
        orb_high = max(High) and orb_low = min(Low), which is mathematically
        equivalent to tracking every tick during 9:15-9:30.

        Returns:
            Number of stocks with ORB ranges successfully reconstructed.
        """
        orb_strategy = None
        for strat in self.strategies:
            if isinstance(strat, ORBStrategy):
                orb_strategy = strat
                break

        if orb_strategy is None:
            logger.warning("ORB strategy not found — cannot reconstruct ranges")
            return 0

        count = 0
        skipped = 0
        for token, candles in self.candle_store.items():
            # Skip indices (NIFTY/BANKNIFTY) — they don't trade via ORB
            stock = self.token_to_symbol.get(token)
            if stock is None:
                continue

            # Need at least the first 3 candles (9:15-9:30 window)
            orb_candles = candles[:3]
            if len(orb_candles) < 3:
                skipped += 1
                continue

            orb_high = max(c["High"] for c in orb_candles)
            orb_low = min(c["Low"] for c in orb_candles)

            # Sanity check — skip invalid ranges
            if orb_high <= 0 or orb_low <= 0 or orb_high <= orb_low:
                skipped += 1
                continue

            # Update scanner tracking
            self.orb_highs[token] = orb_high
            self.orb_lows[token] = orb_low

            # Set range in ORB strategy (same path as live tracking)
            orb_strategy.set_orb_range(stock=stock, high=orb_high, low=orb_low)
            count += 1

        logger.info(
            f"ORB reconstruction: {count} stocks reconstructed, {skipped} skipped "
            f"(insufficient candles or invalid data)"
        )

        return count

    def get_all_signals_today(self) -> list[Signal]:
        """Return all signals generated today (including skipped) for Firebase."""
        return self._all_signals_today

    def scan(self, tick: dict) -> list[Signal]:
        """
        Sniper Mode V2 scan — signal filter pipeline (Option C: no confluence requirement).

        Steps:
        1. Run ALL strategies on this tick for this stock
        2. Pick the best signal (highest confidence) — no confluence gate
        3. Apply sniper filters: choppiness, 15-min trend, volume gate
        4. Score the signal
        5. Apply ATR expansion check (penalty for breakouts)
        6. Return at most 1 signal (highest scoring)

        All signals (including skipped) are tracked for dashboard visibility.
        """
        token = tick["token"]
        stock = self.token_to_symbol.get(token, token)

        # One signal per stock per day
        if token in self.signals_today:
            return []

        # Skip stocks flagged by news sentiment (earnings day, major events)
        stock_sentiment = self.news_sentiment.get(stock, {})
        if stock_sentiment.get("skip_today", False):
            return []

        # Build tick buffer (tag with arrival time for 5-min candle building)
        tick["_time"] = time.time()
        if token not in self.tick_buffer:
            self.tick_buffer[token] = []
        buf = self.tick_buffer[token]
        buf.append(tick)
        if len(buf) > 500:
            buf.pop(0)

        candles = self._build_candles(token)
        stock_context = self._build_stock_context(token, tick, candles)

        # ── Step 1: Run ALL strategies and collect raw signals ──────────
        raw_signals: list[Signal] = []
        for strategy in self.strategies:
            if not strategy.is_active:
                continue
            try:
                signal = strategy.check_signal(
                    stock=stock,
                    token=token,
                    candles=candles,
                    current_tick=tick,
                    market_context=stock_context,
                )
                if signal:
                    raw_signals.append(signal)
            except Exception as e:
                logger.error(f"Strategy error ({strategy.name}) for {stock}: {e}", exc_info=True)

        if not raw_signals:
            return []

        # ── Step 2: Pick best signal — no confluence requirement ──────────
        # Option C: Every single-strategy signal is a first-class candidate.
        # The 10+ downstream filters (choppiness, volume, trend, score >= 75,
        # candle close, ATR, pre-flight 17 checks) provide all the gating needed.
        # Confluence count is tracked for logging/analytics only.
        long_signals = [s for s in raw_signals if s.direction == "LONG"]
        short_signals = [s for s in raw_signals if s.direction == "SHORT"]

        best_long = max(long_signals, key=lambda s: s.confidence) if long_signals else None
        best_short = max(short_signals, key=lambda s: s.confidence) if short_signals else None

        # Choose direction: prefer higher confidence, then more strategies
        if best_long and best_short:
            if best_long.confidence > best_short.confidence:
                confluent_signal = best_long
            elif best_short.confidence > best_long.confidence:
                confluent_signal = best_short
            elif len(short_signals) > len(long_signals):
                confluent_signal = best_short
            else:
                confluent_signal = best_long
        elif best_long:
            confluent_signal = best_long
        else:
            confluent_signal = best_short

        # Attach confluence info (informational — not a gate)
        same_dir = [s for s in raw_signals if s.direction == confluent_signal.direction]
        confluence_count = len(same_dir)
        confluence_strategies = [s.strategy_name for s in same_dir]
        confluent_signal.confluence_count = confluence_count
        confluent_signal.confluence_strategies = confluence_strategies

        # ── Step 3: Compute sniper mode indicators ─────────────────────
        atr_value = get_current_atr(candles, period=self.indicator_config.atr_period)
        chop_value = get_current_choppiness(candles, period=self.trading_config.chop_period)
        trend_15m = get_15min_trend(
            candles, flat_threshold_pct=self.trading_config.trend_15m_flat_threshold_pct
        )

        confluent_signal.atr_value = atr_value
        confluent_signal.choppiness = chop_value
        confluent_signal.trend_15m = trend_15m

        # ── Step 3a: Lunch block check ─────────────────────────────────
        now = datetime.now().time()
        if self.trading_config.lunch_block_start <= now <= self.trading_config.lunch_block_end:
            confluent_signal.status = "SKIPPED-LUNCH-BLOCK"
            confluent_signal.skip_reason = (
                f"Lunch block {self.trading_config.lunch_block_start.strftime('%H:%M')}"
                f"-{self.trading_config.lunch_block_end.strftime('%H:%M')}"
            )
            self._all_signals_today.append(confluent_signal)
            logger.info(
                f"SKIPPED-LUNCH-BLOCK: {stock} {confluent_signal.direction} — "
                f"{' + '.join(confluence_strategies)} confluence ({confluence_count}/4), "
                f"blocked during {self.trading_config.lunch_block_start.strftime('%H:%M')}"
                f"-{self.trading_config.lunch_block_end.strftime('%H:%M')}"
            )
            return []

        # ── Step 3b: VIX gate ──────────────────────────────────────────
        vix = self.market_context.get("vix", 0)
        # Only gate on VIX if we have real data (VIX=0 means no data received yet)
        if vix > 0 and vix > self.trading_config.vix_caution_threshold:
            confluent_signal.status = "SKIPPED-VIX-GATE"
            confluent_signal.skip_reason = f"VIX {vix:.1f} > {self.trading_config.vix_caution_threshold} (DANGER zone)"
            self._all_signals_today.append(confluent_signal)
            logger.info(
                f"SKIPPED-VIX-GATE: {stock} — VIX {vix:.1f} > "
                f"{self.trading_config.vix_caution_threshold} (DANGER: no new trades)"
            )
            return []

        # ── Step 3c: Choppiness Index gate ─────────────────────────────
        if chop_value > self.trading_config.chop_threshold:
            confluent_signal.status = "SKIPPED-CHOPPY"
            confluent_signal.skip_reason = f"Choppiness Index {chop_value} > {self.trading_config.chop_threshold}"
            self._all_signals_today.append(confluent_signal)
            logger.info(
                f"SKIPPED-CHOPPY: {stock} — Choppiness Index {chop_value:.1f} > "
                f"{self.trading_config.chop_threshold} (market is choppy)"
            )
            return []

        # ── Step 3d: NIFTY choppiness gate ─────────────────────────────
        nifty_chop = self.market_context.get("nifty_choppiness", 100.0)
        if nifty_chop > self.trading_config.chop_threshold:
            confluent_signal.status = "SKIPPED-CHOPPY"
            confluent_signal.skip_reason = f"NIFTY Choppiness {nifty_chop} > {self.trading_config.chop_threshold}"
            self._all_signals_today.append(confluent_signal)
            logger.info(
                f"SKIPPED-CHOPPY: {stock} — NIFTY Choppiness {nifty_chop:.1f} > "
                f"{self.trading_config.chop_threshold} (entire market choppy)"
            )
            return []

        # ── Step 3e: 15-minute trend alignment ─────────────────────────
        if self.trading_config.trend_15m_enabled:
            if trend_15m == "NEUTRAL":
                confluent_signal.status = "SKIPPED-AGAINST-15M-TREND"
                confluent_signal.skip_reason = f"15-min trend NEUTRAL (EMAs flat)"
                self._all_signals_today.append(confluent_signal)
                logger.info(
                    f"SKIPPED-15M-TREND: {stock} — 15-min trend NEUTRAL (skip)"
                )
                return []

            direction = confluent_signal.direction
            if (direction == "LONG" and trend_15m == "BEARISH") or \
               (direction == "SHORT" and trend_15m == "BULLISH"):
                confluent_signal.status = "SKIPPED-AGAINST-15M-TREND"
                confluent_signal.skip_reason = f"{direction} rejected — 15-min trend {trend_15m}"
                self._all_signals_today.append(confluent_signal)
                logger.info(
                    f"SKIPPED-15M-TREND: {stock} {direction} rejected — "
                    f"15-min trend {trend_15m} (9EMA vs 21EMA)"
                )
                return []

        # ── Step 3f: ADV + RVOL + price confirm + traded value ────────
        # These are tracked for logging/analytics but NOT used as hard gates.
        # With Rs.15K capital trading NIFTY 200 stocks, all have sufficient
        # liquidity. RVOL is applied as a score modifier after scoring (Step 4b).
        adv_value = stock_context.get("adv", 0)
        rvol = stock_context.get("rvol", 1.0)
        rvol_source = stock_context.get("rvol_source", "SESSION")
        confluent_signal.rvol = rvol
        confluent_signal.adv = adv_value

        # ── Step 3j: Candle close confirmation (breakout strategies) ───
        is_breakout = confluent_signal.strategy_name in ("ORB", "SR_BREAKOUT")
        if is_breakout and len(candles) >= 2:
            prev_close = candles["Close"].iloc[-2]
            if confluent_signal.direction == "LONG":
                level = confluent_signal.entry_price
                if prev_close < level:
                    confluent_signal.status = "SKIPPED-NO-CANDLE-CLOSE"
                    confluent_signal.skip_reason = (
                        f"Prev candle close {prev_close:.2f} < breakout level {level:.2f}"
                    )
                    self._all_signals_today.append(confluent_signal)
                    logger.info(
                        f"SKIPPED-CANDLE-CLOSE: {stock} LONG — prev candle "
                        f"didn't close above {level:.2f}"
                    )
                    return []
            else:
                level = confluent_signal.entry_price
                if prev_close > level:
                    confluent_signal.status = "SKIPPED-NO-CANDLE-CLOSE"
                    confluent_signal.skip_reason = (
                        f"Prev candle close {prev_close:.2f} > breakout level {level:.2f}"
                    )
                    self._all_signals_today.append(confluent_signal)
                    logger.info(
                        f"SKIPPED-CANDLE-CLOSE: {stock} SHORT — prev candle "
                        f"didn't close below {level:.2f}"
                    )
                    return []

        # ── Step 4: Score the signal ───────────────────────────────────
        score, breakdown = self.scorer.score(
            signal=confluent_signal,
            market_context=stock_context,
            news_sentiment=self.news_sentiment,
        )

        # ── Step 4a: ATR expansion check (penalty for breakouts) ───────
        if is_breakout:
            atr_expanding = is_atr_expanding(
                candles,
                atr_period=self.indicator_config.atr_period,
                lookback=self.trading_config.atr_expansion_lookback,
            )
            if not atr_expanding:
                penalty = self.trading_config.atr_compression_penalty
                score -= penalty
                breakdown["atr_compression_penalty"] = -penalty
                logger.info(
                    f"{stock} {confluent_signal.strategy_name} — ATR compressing, "
                    f"-{penalty} penalty (score now {score})"
                )

        # ── Step 4b: RVOL score modifier (soft penalty/bonus) ──────────
        # Instead of killing signals with low RVOL, we adjust the score.
        # This lets volume matter without blocking every signal on normal days.
        if rvol < 1.0:
            rvol_adj = -10
            score += rvol_adj
            breakdown["rvol_penalty"] = rvol_adj
            logger.debug(f"{stock} — RVOL {rvol:.1f}× (low): {rvol_adj} score penalty")
        elif rvol < 2.0:
            rvol_adj = -5
            score += rvol_adj
            breakdown["rvol_penalty"] = rvol_adj
            logger.debug(f"{stock} — RVOL {rvol:.1f}× (moderate): {rvol_adj} score penalty")
        elif rvol >= 3.0:
            rvol_adj = 5
            score += rvol_adj
            breakdown["rvol_bonus"] = rvol_adj
            logger.debug(f"{stock} — RVOL {rvol:.1f}× (high): +{rvol_adj} score bonus")

        # Attach score to signal
        confluent_signal.score = score
        confluent_signal.score_breakdown = breakdown
        confluent_signal.reason = (
            f"[Score: {score}/100] {confluent_signal.reason} | "
            f"Confluence: {' + '.join(confluence_strategies)} ({confluence_count}/4) | "
            f"RVOL: {rvol:.1f}× ({rvol_source})"
        )

        # ── Step 5: Score threshold check ──────────────────────────────
        min_score = self.trading_config.min_score_to_trade
        if score < min_score:
            confluent_signal.status = "SKIPPED-LOW-SCORE"
            confluent_signal.skip_reason = f"Score {score} < {min_score}"
            self._all_signals_today.append(confluent_signal)
            logger.info(
                f"Signal filtered (score {score} < {min_score}): "
                f"{stock} {confluent_signal.direction} | "
                f"Missing: {self._get_missing_factors(breakdown)}"
            )
            return []

        # ── Step 5a: NIFTY volume spike flag (macro-driven) ───────────
        nifty_macro = stock_context.get("nifty_macro_driven", False)
        if nifty_macro:
            confluent_signal.macro_driven = True
            logger.info(
                f"{stock} — NIFTY volume spike detected at same time slot. "
                f"Flagging signal as MACRO-DRIVEN (not rejecting)"
            )

        # ── Step 6: ATR-based SL and target recalculation ──────────────
        if atr_value > 0:
            self._apply_atr_based_sl_target(confluent_signal, atr_value, vix)

        # ── Signal passed all filters — mark for execution ─────────────
        confluent_signal.status = "QUALIFIED"
        self.signals_today.add(token)
        self._all_signals_today.append(confluent_signal)

        label = self.scorer.get_score_label(score)
        macro_tag = " [MACRO-DRIVEN]" if confluent_signal.macro_driven else ""
        logger.info(
            f"{label} SNIPER signal: {confluent_signal.stock} "
            f"{confluent_signal.direction} @ Rs.{confluent_signal.entry_price:.2f} | "
            f"Score: {score}/100 | "
            f"Confluence: {' + '.join(confluence_strategies)} ({confluence_count}/4) | "
            f"RVOL: {rvol:.1f}× ({rvol_source}) | "
            f"ATR: {atr_value:.2f} | CHOP: {chop_value:.1f} | 15m: {trend_15m}"
            f"{macro_tag}"
        )

        return [confluent_signal]

    def _apply_atr_based_sl_target(self, signal: Signal, atr: float, vix: float):
        """
        Recalculate stop-loss and target using ATR-based dynamic sizing.

        SL = entry ± (ATR × multiplier), clamped to [0.5%, 3%] of entry.
        Target = entry ± (SL distance × 2.5R).
        """
        # Choose ATR multiplier based on VIX 4-zone regime
        if vix > 0 and vix >= self.trading_config.vix_caution_threshold:
            # CAUTION (30-35): widest SL
            atr_mult = self.trading_config.atr_sl_multiplier_caution
        elif vix > 0 and vix >= self.trading_config.vix_elevated_threshold:
            # ELEVATED (25-30): wider SL
            atr_mult = self.trading_config.atr_sl_multiplier_elevated
        else:
            # NORMAL (<25) or no VIX data: standard SL
            atr_mult = self.trading_config.atr_sl_multiplier_normal

        sl_distance = atr * atr_mult

        # Apply floor and ceiling
        floor_distance = signal.entry_price * (self.trading_config.atr_sl_floor_pct / 100)
        ceiling_distance = signal.entry_price * (self.trading_config.atr_sl_ceiling_pct / 100)
        sl_distance = max(sl_distance, floor_distance)
        sl_distance = min(sl_distance, ceiling_distance)

        # Calculate new SL and target
        rr_target = self.trading_config.risk_reward_ratio  # 2.5R
        if signal.direction == "LONG":
            signal.stop_loss = round(signal.entry_price - sl_distance, 2)
            signal.target = round(signal.entry_price + sl_distance * rr_target, 2)
        else:
            signal.stop_loss = round(signal.entry_price + sl_distance, 2)
            signal.target = round(signal.entry_price - sl_distance * rr_target, 2)

    def _build_stock_context(self, token: str, tick: dict, candles: pd.DataFrame) -> dict:
        """Build per-stock enriched context dict passed to strategies and scorer."""
        ctx = dict(self.market_context)  # Start with NIFTY + VIX
        stock = self.token_to_symbol.get(token, token)

        # VWAP for this stock
        vwap = self._calc_vwap_for(token)
        ctx["vwap"] = vwap
        ctx["is_above_vwap"] = tick["ltp"] > vwap if vwap > 0 else True

        # Previous day OHLC
        prev_day = self.prev_day_levels.get(token, {})
        ctx["prev_day"] = prev_day

        # Gap % from prev close
        ctx["gap_pct"] = self._calc_gap_pct(token, prev_day)

        # Spread proxy
        ctx["spread_pct"] = self._calc_spread_proxy(tick)

        # RSI(14) from candle data
        ctx["rsi"] = self._calc_rsi(candles) if len(candles) >= 15 else 50.0

        # EMA alignment flag
        ctx["ema_aligned"] = self._calc_ema_aligned(candles, token)

        # RVOL (Relative Volume) — TOD-based with session fallback
        rvol, rvol_source = self._calc_rvol(token, stock, candles)
        ctx["volume_ratio"] = rvol  # Keep volume_ratio key for scorer compatibility
        ctx["rvol"] = rvol
        ctx["rvol_source"] = rvol_source

        # ADV (Average Daily Volume) from volume profile
        ctx["adv"] = self._get_adv(stock)

        # Candle traded value (price × volume of last COMPLETED candle)
        # iloc[-1] is incomplete; iloc[-2] is the last completed candle
        if len(candles) >= 2:
            completed_price = float(candles["Close"].iloc[-2])
            completed_vol = float(candles["Volume"].iloc[-2])
            ctx["candle_traded_value"] = completed_price * completed_vol
        else:
            ctx["candle_traded_value"] = 0

        # NIFTY volume spike check (macro-driven flag)
        ctx["nifty_macro_driven"] = self._check_nifty_volume_spike()

        # Near prev day key levels flag (within 0.3%)
        ctx["near_prev_levels"] = self._near_prev_levels(
            tick["ltp"], prev_day
        )

        return ctx

    def _calc_vwap_for(self, token: str) -> float:
        """Cumulative VWAP from all ticks today."""
        ticks = self.tick_buffer.get(token, [])
        if len(ticks) < 5:
            return 0.0

        total_tp_vol = 0.0
        total_vol = 0.0
        for t in ticks:
            h = t.get("high", t["ltp"])
            l = t.get("low", t["ltp"])
            c = t["ltp"]
            v = t.get("volume", 0)
            if v <= 0:
                continue
            tp = (h + l + c) / 3
            total_tp_vol += tp * v
            total_vol += v

        return round(total_tp_vol / total_vol, 2) if total_vol > 0 else 0.0

    def _calc_gap_pct(self, token: str, prev_day: dict) -> float:
        """Gap from previous close to today's open."""
        prev_close = prev_day.get("prev_close", 0)
        if prev_close <= 0:
            return 0.0
        ticks = self.tick_buffer.get(token, [])
        if not ticks:
            return 0.0
        today_open = ticks[0].get("open", ticks[0]["ltp"])
        return round(((today_open - prev_close) / prev_close) * 100, 3)

    def _calc_spread_proxy(self, tick: dict) -> float:
        """Estimate bid-ask spread as |ltp - avg_price| / ltp × 100."""
        ltp = tick.get("ltp", 0)
        avg = tick.get("avg_price", ltp)
        if ltp <= 0:
            return 0.0
        return round(abs(ltp - avg) / ltp * 100, 4)

    def _calc_rsi(self, candles: pd.DataFrame, period: int = 14) -> float:
        """Calculate current RSI(14) from close prices."""
        if len(candles) < period + 1:
            return 50.0
        try:
            closes = candles["Close"]
            delta = closes.diff()
            gain = delta.clip(lower=0).rolling(period).mean()
            loss = (-delta.clip(upper=0)).rolling(period).mean()
            if loss.iloc[-1] == 0:
                return 100.0
            rs = gain.iloc[-1] / loss.iloc[-1]
            return round(100 - (100 / (1 + rs)), 1)
        except Exception:
            return 50.0

    def _calc_ema_aligned(self, candles: pd.DataFrame, token: str) -> Optional[bool]:
        """
        Returns True if EMA9 > EMA21 (bullish EMAs),
        False if EMA9 < EMA21 (bearish EMAs),
        None if not enough data.
        """
        if len(candles) < 22:
            return None
        try:
            closes = candles["Close"]
            ema9 = float(closes.ewm(span=9, adjust=False).mean().iloc[-1])
            ema21 = float(closes.ewm(span=21, adjust=False).mean().iloc[-1])
            return ema9 > ema21
        except Exception:
            return None

    def _calc_rvol(self, token: str, stock: str, candles: pd.DataFrame) -> tuple[float, str]:
        """
        Calculate RVOL (Relative Volume) using 10-day TOD average when available,
        falling back to session running average when insufficient TOD data.

        Uses the last COMPLETED candle (iloc[-2]), not the current incomplete one
        (iloc[-1]). The incomplete candle is always appended last by _build_candles()
        and has only a fraction of its final volume (e.g., 1 min into a 5-min window
        = ~20% volume), which would give artificially low RVOL values.

        Returns:
            (rvol_value, source) — source is "TOD" or "SESSION"
        """
        # Need at least 3 candles: 1+ completed history + 1 completed to measure + 1 incomplete
        if len(candles) < 3:
            return 1.0, "SESSION"

        # Use last COMPLETED candle (iloc[-2]); iloc[-1] is the current incomplete candle
        current_vol = float(candles["Volume"].iloc[-2])
        if current_vol <= 0:
            return 0.0, "SESSION"

        # Try TOD (time-of-day) comparison first
        if self.volume_profile is not None:
            # The completed candle belongs to the PREVIOUS 5-min slot, not current
            now = datetime.now()
            prev_slot_min = ((now.minute // 5) * 5) - 5
            prev_slot_hour = now.hour
            if prev_slot_min < 0:
                prev_slot_min += 60
                prev_slot_hour -= 1
            slot = f"{prev_slot_hour:02d}:{prev_slot_min:02d}"

            tod_days = self.volume_profile.get_tod_data_days(stock, slot)

            if tod_days >= self.trading_config.rvol_tod_min_days:
                tod_avg = self.volume_profile.get_tod_average(stock, slot)
                if tod_avg and tod_avg > 0:
                    return round(current_vol / tod_avg, 2), "TOD"

        # Fallback: session running average of completed candles only
        lookback = self.trading_config.volume_lookback
        # Available completed candles for averaging = everything before iloc[-2]
        available = len(candles) - 2
        actual_lookback = min(lookback, available)
        if actual_lookback < 2:
            return 1.0, "SESSION"

        # Average completed candles BEFORE the one we're measuring
        avg = float(candles["Volume"].iloc[-(actual_lookback + 2):-2].mean())
        if avg <= 0:
            return 1.0, "SESSION"
        return round(current_vol / avg, 2), "SESSION"

    def _get_adv(self, stock: str) -> float:
        """Get 20-day Average Daily Volume from volume profile. Returns 0 if no data."""
        if self.volume_profile is None:
            return 0.0
        return self.volume_profile.get_adv(stock)

    def _check_nifty_volume_spike(self) -> bool:
        """
        Check if NIFTY 50 has a volume spike at the current time slot.

        If NIFTY RVOL >= 2x its TOD average, the move is likely macro-driven
        (index event, FII flow, global news) rather than stock-specific.
        Returns True to flag, not to reject.
        """
        if self.volume_profile is None:
            return False

        # Get current NIFTY candle volume
        nifty_vol = 0
        if self._nifty_current_window_ticks:
            vols = [x.get("volume", 0) for x in self._nifty_current_window_ticks]
            if vols:
                nifty_vol = max(0, vols[-1] - vols[0])
        elif self.nifty_candle_store:
            nifty_vol = self.nifty_candle_store[-1].get("Volume", 0)

        if nifty_vol <= 0:
            return False

        slot = current_time_slot()
        nifty_tod_avg = self.volume_profile.get_nifty_tod_average(slot)
        if not nifty_tod_avg or nifty_tod_avg <= 0:
            return False

        nifty_rvol = nifty_vol / nifty_tod_avg
        return nifty_rvol >= self.trading_config.nifty_volume_spike_multiplier

    def _near_prev_levels(self, price: float, prev_day: dict) -> bool:
        """True if price is within 0.3% of prev day H/L/C."""
        proximity = self.trading_config.prev_day_proximity_pct / 100
        for key in ("prev_high", "prev_low", "prev_close"):
            level = prev_day.get(key, 0)
            if level > 0 and abs(price - level) / level < proximity:
                return True
        return False

    def _get_missing_factors(self, breakdown: dict) -> str:
        """Return comma-separated list of zero-scoring factors (for logging)."""
        missing = [k for k, v in breakdown.items() if v == 0]
        return ", ".join(missing[:5]) if missing else "none"

    def _build_candles(self, token: str) -> pd.DataFrame:
        """
        Build proper 5-minute OHLCV candles from tick LTP data (incremental).

        Each tick from Angel One carries the DAY's cumulative open/high/low,
        NOT per-candle values. So we build candles from LTP:
        - Open  = first LTP in the 5-min window
        - High  = max LTP in the 5-min window
        - Low   = min LTP in the 5-min window
        - Close = last LTP in the 5-min window
        - Volume = cumulative volume at end minus start of window

        Called on every tick — only processes the latest tick (O(1) per call).
        Completed candles persist in candle_store across calls.
        """
        ticks = self.tick_buffer.get(token, [])
        if not ticks:
            return pd.DataFrame()

        latest_tick = ticks[-1]
        tick_time = latest_tick.get("_time", 0)
        if tick_time == 0:
            return pd.DataFrame()

        candle_interval = 300  # 5 minutes in seconds

        # Initialize tracking for this token on first call
        if token not in self.candle_store:
            self.candle_store[token] = []
        if token not in self._candle_window_start:
            self._candle_window_start[token] = tick_time
        if token not in self._current_window_ticks:
            self._current_window_ticks[token] = []
        # Track starting slot for end-of-day volume profile save
        if token not in self._candle_start_slot_index:
            dt = datetime.fromtimestamp(tick_time)
            # Slot index: 0 = 09:15, 1 = 09:20, etc.
            mins_since_open = (dt.hour - 9) * 60 + (dt.minute - 15)
            self._candle_start_slot_index[token] = max(0, mins_since_open // 5)

        window_start = self._candle_window_start[token]

        # If latest tick crossed into a new 5-min window, close current window
        while tick_time >= window_start + candle_interval:
            cwt = self._current_window_ticks[token]
            if cwt:
                ltps = [x["ltp"] for x in cwt]
                vols = [x.get("volume", 0) for x in cwt]
                self.candle_store[token].append({
                    "Open": ltps[0],
                    "High": max(ltps),
                    "Low": min(ltps),
                    "Close": ltps[-1],
                    "Volume": max(0, vols[-1] - vols[0]),
                })
            self._current_window_ticks[token] = []
            window_start += candle_interval

        self._candle_window_start[token] = window_start

        # Add latest tick to current (incomplete) window
        self._current_window_ticks[token].append(latest_tick)

        # Keep at most 100 completed candles (enough for all indicators)
        if len(self.candle_store[token]) > 100:
            self.candle_store[token] = self.candle_store[token][-100:]

        # Build result: completed candles + current incomplete candle
        all_candle_data = list(self.candle_store[token])
        cwt = self._current_window_ticks[token]
        if cwt:
            ltps = [x["ltp"] for x in cwt]
            vols = [x.get("volume", 0) for x in cwt]
            all_candle_data.append({
                "Open": ltps[0],
                "High": max(ltps),
                "Low": min(ltps),
                "Close": ltps[-1],
                "Volume": max(0, vols[-1] - vols[0]),
            })

        if not all_candle_data:
            return pd.DataFrame()

        return pd.DataFrame(all_candle_data)

    def update_market_context(self, nifty_tick: dict):
        """Update global NIFTY direction, VIX, and NIFTY choppiness from index ticks."""
        token = nifty_tick.get("token", "")

        # India VIX token is 99919000
        if token == "99919000":
            vix_value = nifty_tick.get("ltp", 0)
            self.market_context["vix"] = vix_value

            # Determine VIX 4-zone regime
            if vix_value > self.trading_config.vix_caution_threshold:
                self.market_context["vix_regime"] = "DANGER"
            elif vix_value >= self.trading_config.vix_elevated_threshold:
                self.market_context["vix_regime"] = "CAUTION"
            elif vix_value >= self.trading_config.vix_normal_threshold:
                self.market_context["vix_regime"] = "ELEVATED"
            else:
                self.market_context["vix_regime"] = "NORMAL"
            return

        # NIFTY 50 and BANKNIFTY — compute direction + choppiness
        ltp = nifty_tick.get("ltp", 0)
        open_price = nifty_tick.get("open", 0)

        if ltp and open_price:
            change_pct = ((ltp - open_price) / open_price) * 100

            if change_pct > 0.2:
                self.market_context["nifty_direction"] = "BULLISH"
            elif change_pct < -0.2:
                self.market_context["nifty_direction"] = "BEARISH"
            else:
                self.market_context["nifty_direction"] = "NEUTRAL"

            self.market_context["nifty_ltp"] = ltp
            self.market_context["nifty_change_pct"] = round(change_pct, 2)

        # Track NIFTY ticks for choppiness calculation (tag with arrival time)
        nifty_tick["_time"] = time.time()
        self.nifty_tick_buffer.append(nifty_tick)
        if len(self.nifty_tick_buffer) > 500:
            self.nifty_tick_buffer.pop(0)

        # Compute NIFTY choppiness from candles (pre-seeded or built from ticks)
        if len(self.nifty_tick_buffer) >= 20 or len(self.nifty_candle_store) >= 15:
            nifty_candles = self._build_nifty_candles()
            if len(nifty_candles) >= 15:
                nifty_chop = get_current_choppiness(
                    nifty_candles, period=self.trading_config.chop_period
                )
                self.market_context["nifty_choppiness"] = nifty_chop

    def _build_nifty_candles(self) -> pd.DataFrame:
        """Build proper 5-minute candles from NIFTY tick buffer (incremental, same as stock candles)."""
        if not self.nifty_tick_buffer:
            return pd.DataFrame()

        latest_tick = self.nifty_tick_buffer[-1]
        tick_time = latest_tick.get("_time", 0)
        ltp = latest_tick.get("ltp", 0)
        if tick_time == 0 or ltp <= 0:
            return pd.DataFrame()

        candle_interval = 300  # 5 minutes

        if self._nifty_candle_window_start == 0:
            self._nifty_candle_window_start = tick_time
            # Track starting slot for NIFTY profile save
            dt = datetime.fromtimestamp(tick_time)
            mins_since_open = (dt.hour - 9) * 60 + (dt.minute - 15)
            self._nifty_start_slot_index = max(0, mins_since_open // 5)

        window_start = self._nifty_candle_window_start

        # If latest tick crossed into a new window, close current window
        while tick_time >= window_start + candle_interval:
            cwt = self._nifty_current_window_ticks
            if cwt:
                ltps = [x.get("ltp", 0) for x in cwt if x.get("ltp", 0) > 0]
                if ltps:
                    vols = [x.get("volume", 0) for x in cwt]
                    self.nifty_candle_store.append({
                        "Open": ltps[0],
                        "High": max(ltps),
                        "Low": min(ltps),
                        "Close": ltps[-1],
                        "Volume": max(0, vols[-1] - vols[0]),
                    })
            self._nifty_current_window_ticks = []
            window_start += candle_interval

        self._nifty_candle_window_start = window_start

        # Add latest tick to current window
        self._nifty_current_window_ticks.append(latest_tick)

        # Keep at most 100 completed candles
        if len(self.nifty_candle_store) > 100:
            self.nifty_candle_store = self.nifty_candle_store[-100:]

        # Completed candles + current incomplete
        all_candle_data = list(self.nifty_candle_store)
        cwt = self._nifty_current_window_ticks
        if cwt:
            ltps = [x.get("ltp", 0) for x in cwt if x.get("ltp", 0) > 0]
            if ltps:
                vols = [x.get("volume", 0) for x in cwt]
                all_candle_data.append({
                    "Open": ltps[0],
                    "High": max(ltps),
                    "Low": min(ltps),
                    "Close": ltps[-1],
                    "Volume": max(0, vols[-1] - vols[0]),
                })

        if not all_candle_data:
            return pd.DataFrame()

        return pd.DataFrame(all_candle_data)

    def reset_daily(self):
        """Reset all state for a new trading day."""
        self.tick_buffer.clear()
        self.candle_store.clear()
        self._candle_window_start.clear()
        self._current_window_ticks.clear()
        self.nifty_candle_store.clear()
        self._nifty_candle_window_start = 0.0
        self._nifty_current_window_ticks.clear()
        self.orb_highs.clear()
        self.orb_lows.clear()
        self.signals_today.clear()
        self.news_sentiment.clear()
        self.nifty_tick_buffer.clear()
        self._all_signals_today.clear()
        self._candle_start_slot_index.clear()
        self._nifty_start_slot_index = 0
        self._is_expiry_day = is_expiry_day()

        for strat in self.strategies:
            if isinstance(strat, ORBStrategy):
                strat.orb_ranges.clear()
            if hasattr(strat, "reset_daily"):
                strat.reset_daily()

        logger.info("Scanner reset for new trading day")
