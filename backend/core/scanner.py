"""
Pattern Scanner — Scans all 200 stocks, runs all strategies.
=============================================================
The scanner is the "brain" that coordinates pattern detection
across the watchlist using all active strategies.

Flow:
1. During 9:15-9:30 (ORB period): track high/low for each stock
2. After 9:30: run each strategy on every incoming tick
3. Enriched stock context (VWAP, RSI, EMA alignment, VIX, regime, volume ratio)
   is passed to each strategy for multi-confirmation checks
4. Signal scorer evaluates each signal (0-100)
5. Only signals with score >= min_score_to_trade are returned

All 4 strategies are wired:
- ORB (Opening Range Breakout)  — primary strategy
- VWAP_BOUNCE (VWAP mean reversion) — secondary
- EMA_CROSS (EMA crossover momentum) — secondary
- SR_BREAKOUT (Support/Resistance level break) — secondary
"""

import logging
from typing import Optional

import pandas as pd

from strategies.base_strategy import Signal
from strategies.orb_strategy import ORBStrategy
from strategies.vwap_strategy import VWAPBounceStrategy
from strategies.ema_strategy import EMACrossoverStrategy
from strategies.sr_breakout_strategy import SRBreakoutStrategy

logger = logging.getLogger(__name__)


class PatternScanner:
    """Scans watchlist stocks for trading patterns with scoring and regime awareness."""

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
        }

        # Per-stock prev day levels (loaded at startup)
        self.prev_day_levels: dict[str, dict] = {}

        # Already signaled today (one signal per stock per day)
        self.signals_today: set = set()

        # News sentiment cache (populated at 9 AM)
        self.news_sentiment: dict[str, dict] = {}

        # Signal scorer
        from core.signal_scorer import SignalScorer
        self.scorer = SignalScorer()

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

    def scan(self, tick: dict) -> list[Signal]:
        """
        Scan a single price tick against all active strategies.

        Returns list of Signal objects — usually empty or 1 signal.
        Each signal has already been scored; only 70+ are returned.

        The enriched stock_context includes:
        - NIFTY direction, NIFTY LTP
        - India VIX (via update_market_context)
        - Per-stock VWAP
        - EMA9 / EMA21 alignment flag
        - RSI(14) value
        - Volume ratio vs 20-candle average
        - Gap % from prev close
        - Spread proxy
        - Prev day OHLC
        - Near prev day levels flag
        - News sentiment for this stock
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

        signals = []
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

                if not signal:
                    continue

                # Score the signal
                score, breakdown = self.scorer.score(
                    signal=signal,
                    market_context=stock_context,
                    news_sentiment=self.news_sentiment,
                )

                # Attach score to signal (stored in reason string + new field)
                signal.score = score
                signal.score_breakdown = breakdown
                signal.reason = (
                    f"[Score: {score}/100] {signal.reason}"
                )

                # Only keep signals above the minimum score threshold
                min_score = self.trading_config.min_score_to_trade
                if score < min_score:
                    logger.info(
                        f"Signal filtered (score {score} < {min_score}): "
                        f"{stock} {signal.direction} | "
                        f"Missing: {self._get_missing_factors(breakdown)}"
                    )
                    continue

                signals.append(signal)
                self.signals_today.add(token)
                label = self.scorer.get_score_label(score)
                logger.info(
                    f"{label} signal: {signal.stock} {signal.direction} "
                    f"@ Rs.{signal.entry_price:.2f} | Score: {score}/100 | "
                    f"{strategy.name}"
                )
                break  # One signal per stock per tick

            except Exception as e:
                logger.error(f"Strategy error ({strategy.name}) for {stock}: {e}", exc_info=True)

        return signals

    def _build_stock_context(self, token: str, tick: dict, candles: pd.DataFrame) -> dict:
        """
        Build per-stock enriched context dict passed to strategies and scorer.

        New fields vs previous version:
        - rsi: current RSI(14) — scorer and strategies use this
        - ema_aligned: bool — EMA9 above EMA21 for longs, below for shorts
        - volume_ratio: current / 20-candle avg — scorer uses this
        - vix: from global market_context (updated via update_vix)
        - near_prev_levels: bool — within 0.3% of prev H/L/C
        """
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
        """Update global NIFTY direction and VIX from index ticks."""
        # Check if this is NIFTY 50, BANKNIFTY, or VIX
        token = nifty_tick.get("token", "")

        # India VIX token is 99919000
        if token == "99919000":
            vix_value = nifty_tick.get("ltp", 0)
            self.market_context["vix"] = vix_value
            return

        # NIFTY 50 and BANKNIFTY — compute direction
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

    def reset_daily(self):
        """Reset all state for a new trading day."""
        self.tick_buffer.clear()
        self.orb_highs.clear()
        self.orb_lows.clear()
        self.signals_today.clear()
        self.news_sentiment.clear()

        for strat in self.strategies:
            if isinstance(strat, ORBStrategy):
                strat.orb_ranges.clear()
            if hasattr(strat, "reset_daily"):
                strat.reset_daily()

        logger.info("Scanner reset for new trading day")
