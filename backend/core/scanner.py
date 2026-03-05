"""
Pattern Scanner — Sniper Mode V2
==================================
The scanner is the "brain" that coordinates pattern detection
across the watchlist using all active strategies.

Sniper Mode changes:
- Multi-strategy confluence: 2+ strategies must agree on same stock + direction
- Signal queue: collect all qualifying signals, rank by score, pick top 1
- Volume hard gate: 3× average minimum (reject below)
- Choppiness Index filter: CHOP > 61.8 = reject (market is choppy)
- 15-minute trend filter: only trade in direction of higher timeframe
- ATR expansion check: -10 score penalty if ATR compressing on breakouts
- Candle close confirmation: breakout strategies require candle close above level
- Lunch block: 11:00-13:30 fully blocked for new entries
- All signals logged with status tags: EXECUTED/QUEUED/SKIPPED-*

Flow:
1. During 9:15-9:30 (ORB period): track high/low for each stock
2. After 9:30: run ALL strategies on every incoming tick
3. Collect all raw signals per stock
4. Apply confluence filter: only keep signals where 2+ strategies agree
5. Apply sniper filters: choppiness, 15-min trend, volume gate, ATR check
6. Score surviving signals
7. Queue all qualifying signals, return top 1 per scan cycle
"""

import logging
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

    def get_all_signals_today(self) -> list[Signal]:
        """Return all signals generated today (including skipped) for Firebase."""
        return self._all_signals_today

    def scan(self, tick: dict) -> list[Signal]:
        """
        Sniper Mode V2 scan — multi-strategy confluence + signal queue.

        Steps:
        1. Run ALL strategies on this tick for this stock
        2. Check confluence: 2+ strategies must agree on direction
        3. Apply sniper filters: choppiness, 15-min trend, volume gate
        4. Score the confluent signal
        5. Apply ATR expansion check (penalty for breakouts)
        6. Return at most 1 signal (highest scoring)

        All signals (including skipped) are tracked for dashboard visibility.
        """
        token = tick["token"]
        stock = self.token_to_symbol.get(token, token)

        # One signal per stock per day
        if token in self.signals_today:
            return []

        # Build tick buffer
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

        # ── Step 2: Confluence check — group by direction ──────────────
        long_signals = [s for s in raw_signals if s.direction == "LONG"]
        short_signals = [s for s in raw_signals if s.direction == "SHORT"]

        confluent_signal = None
        confluence_count = 0
        confluence_strategies = []

        # Check LONG confluence
        if len(long_signals) >= self.trading_config.min_confluence_count:
            confluence_count = len(long_signals)
            confluence_strategies = [s.strategy_name for s in long_signals]
            # Use the signal with highest confidence as the base
            confluent_signal = max(long_signals, key=lambda s: s.confidence)

        # Check SHORT confluence (prefer whichever has more strategies)
        if len(short_signals) >= self.trading_config.min_confluence_count:
            if confluence_count == 0 or len(short_signals) > confluence_count:
                confluence_count = len(short_signals)
                confluence_strategies = [s.strategy_name for s in short_signals]
                confluent_signal = max(short_signals, key=lambda s: s.confidence)

        # If no confluence, check for exceptional single-strategy exception
        if confluent_signal is None:
            # Exception: allow single strategy if pre-scored signal would be >= 90 (EXCEPTIONAL)
            exception_score = self.trading_config.single_strategy_exception_score
            best_single = max(raw_signals, key=lambda s: s.confidence)
            temp_score, _ = self.scorer.score(
                signal=best_single,
                market_context=stock_context,
                news_sentiment=self.news_sentiment,
            )

            if temp_score >= exception_score:
                # Exceptional signal — allow through with single strategy
                confluent_signal = best_single
                confluence_count = 1
                confluence_strategies = [best_single.strategy_name]
                confluent_signal.confluence_count = 1
                confluent_signal.confluence_strategies = confluence_strategies
                logger.info(
                    f"EXCEPTIONAL single-strategy signal: {stock} {best_single.direction} "
                    f"from {best_single.strategy_name} — pre-score {temp_score} >= {exception_score}"
                )
            else:
                # Still rejected — log and return
                for s in raw_signals:
                    s.status = "SKIPPED-NO-CONFLUENCE"
                    s.skip_reason = (
                        f"Only {s.strategy_name} fired (need {self.trading_config.min_confluence_count}+ "
                        f"or score >= {exception_score}), pre-score={temp_score}"
                    )
                    self._all_signals_today.append(s)
                if raw_signals:
                    logger.info(
                        f"No confluence for {stock}: {[s.strategy_name for s in raw_signals]} "
                        f"(need {self.trading_config.min_confluence_count}+ or score >= {exception_score}, "
                        f"best pre-score={temp_score})"
                    )
                return []

        # Attach confluence info to the winning signal
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
        nifty_chop = self.market_context.get("nifty_choppiness", 50.0)
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

        # ── Step 3f: Volume hard gate (3× average) ────────────────────
        volume_ratio = stock_context.get("volume_ratio", 1.0)
        if volume_ratio < self.trading_config.volume_spike_multiplier:
            confluent_signal.status = "SKIPPED-LOW-VOLUME"
            confluent_signal.skip_reason = (
                f"Volume {volume_ratio:.1f}× < {self.trading_config.volume_spike_multiplier}× minimum"
            )
            self._all_signals_today.append(confluent_signal)
            logger.info(
                f"SKIPPED-LOW-VOLUME: {stock} — volume {volume_ratio:.1f}× "
                f"< {self.trading_config.volume_spike_multiplier}× required"
            )
            return []

        # ── Step 3g: Candle close confirmation (breakout strategies) ───
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

        # Attach score to signal
        confluent_signal.score = score
        confluent_signal.score_breakdown = breakdown
        confluent_signal.reason = (
            f"[Score: {score}/100] {confluent_signal.reason} | "
            f"Confluence: {' + '.join(confluence_strategies)} ({confluence_count}/4)"
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

        # ── Step 6: ATR-based SL and target recalculation ──────────────
        if atr_value > 0:
            self._apply_atr_based_sl_target(confluent_signal, atr_value, vix)

        # ── Signal passed all filters — mark for execution ─────────────
        confluent_signal.status = "QUALIFIED"
        self.signals_today.add(token)
        self._all_signals_today.append(confluent_signal)

        label = self.scorer.get_score_label(score)
        logger.info(
            f"{label} SNIPER signal: {confluent_signal.stock} "
            f"{confluent_signal.direction} @ Rs.{confluent_signal.entry_price:.2f} | "
            f"Score: {score}/100 | "
            f"Confluence: {' + '.join(confluence_strategies)} ({confluence_count}/4) | "
            f"ATR: {atr_value:.2f} | CHOP: {chop_value:.1f} | 15m: {trend_15m}"
        )

        return [confluent_signal]

    def _apply_atr_based_sl_target(self, signal: Signal, atr: float, vix: float):
        """
        Recalculate stop-loss and target using ATR-based dynamic sizing.

        SL = entry ± (ATR × multiplier), clamped to [0.5%, 3%] of entry.
        Target = entry ± (SL distance × 2.5R).
        """
        # Choose ATR multiplier based on VIX regime
        if vix > 0 and vix >= self.trading_config.vix_normal_threshold:
            atr_mult = self.trading_config.atr_sl_multiplier_caution
        else:
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

        # Volume ratio vs 20-candle average
        ctx["volume_ratio"] = self._calc_volume_ratio(candles)

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

    def _calc_volume_ratio(self, candles: pd.DataFrame, lookback: int = 20) -> float:
        """Volume ratio: current tick vs 20-candle average."""
        if len(candles) < lookback + 1:
            return 1.0
        vol = candles["Volume"]
        current = vol.iloc[-1]
        avg = vol.iloc[-(lookback + 1):-1].mean()
        if avg <= 0:
            return 1.0
        return round(current / avg, 2)

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
        """Convert raw ticks into OHLCV DataFrame with per-tick volume (diff)."""
        ticks = self.tick_buffer.get(token, [])
        if not ticks:
            return pd.DataFrame()

        recent = ticks[-200:]
        data = [{
            "Open": t.get("open", t["ltp"]),
            "High": t.get("high", t["ltp"]),
            "Low": t.get("low", t["ltp"]),
            "Close": t["ltp"],
            "Volume": t.get("volume", 0),
            "AvgPrice": t.get("avg_price", t["ltp"]),
        } for t in recent]

        df = pd.DataFrame(data)
        df["Volume"] = df["Volume"].diff().fillna(0).clip(lower=0)
        return df

    def update_market_context(self, nifty_tick: dict):
        """Update global NIFTY direction, VIX, and NIFTY choppiness from index ticks."""
        token = nifty_tick.get("token", "")

        # India VIX token is 99919000
        if token == "99919000":
            vix_value = nifty_tick.get("ltp", 0)
            self.market_context["vix"] = vix_value

            # Determine VIX regime
            if vix_value > self.trading_config.vix_caution_threshold:
                self.market_context["vix_regime"] = "DANGER"
            elif vix_value >= self.trading_config.vix_normal_threshold:
                self.market_context["vix_regime"] = "CAUTION"
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

        # Track NIFTY ticks for choppiness calculation
        self.nifty_tick_buffer.append(nifty_tick)
        if len(self.nifty_tick_buffer) > 500:
            self.nifty_tick_buffer.pop(0)

        # Compute NIFTY choppiness from buffered ticks (need enough data)
        if len(self.nifty_tick_buffer) >= 20:
            nifty_candles = self._build_nifty_candles()
            if len(nifty_candles) >= 15:
                nifty_chop = get_current_choppiness(
                    nifty_candles, period=self.trading_config.chop_period
                )
                self.market_context["nifty_choppiness"] = nifty_chop

    def _build_nifty_candles(self) -> pd.DataFrame:
        """Build candle DataFrame from NIFTY tick buffer."""
        if not self.nifty_tick_buffer:
            return pd.DataFrame()

        recent = self.nifty_tick_buffer[-200:]
        data = [{
            "Open": t.get("open", t.get("ltp", 0)),
            "High": t.get("high", t.get("ltp", 0)),
            "Low": t.get("low", t.get("ltp", 0)),
            "Close": t.get("ltp", 0),
            "Volume": t.get("volume", 0),
        } for t in recent]

        df = pd.DataFrame(data)
        df["Volume"] = df["Volume"].diff().fillna(0).clip(lower=0)
        return df

    def reset_daily(self):
        """Reset all state for a new trading day."""
        self.tick_buffer.clear()
        self.orb_highs.clear()
        self.orb_lows.clear()
        self.signals_today.clear()
        self.news_sentiment.clear()
        self.nifty_tick_buffer.clear()
        self._all_signals_today.clear()

        for strat in self.strategies:
            if isinstance(strat, ORBStrategy):
                strat.orb_ranges.clear()
            if hasattr(strat, "reset_daily"):
                strat.reset_daily()

        logger.info("Scanner reset for new trading day")
