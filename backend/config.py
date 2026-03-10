"""
Configuration for the trading bot.
All settings in one place. Reads secrets from .env file.
"""

import os
from dataclasses import dataclass, field
from datetime import time
from dotenv import load_dotenv

load_dotenv()


@dataclass
class BrokerConfig:
    """Angel One SmartAPI credentials."""
    api_key: str = os.getenv("ANGEL_API_KEY", "")
    client_id: str = os.getenv("ANGEL_CLIENT_ID", "")
    password: str = os.getenv("ANGEL_PASSWORD", "")
    totp_secret: str = os.getenv("ANGEL_TOTP_SECRET", "")


@dataclass
class FirebaseConfig:
    """Firebase connection settings."""
    credentials_path: str = os.getenv("FIREBASE_CREDENTIALS_PATH", "firebase-credentials.json")
    database_url: str = os.getenv("FIREBASE_DATABASE_URL", "")


@dataclass
class NewsConfig:
    """News sentiment API settings (Marketaux free tier: 100 req/day)."""
    api_key: str = os.getenv("NEWS_API_KEY", "")
    enabled: bool = bool(os.getenv("NEWS_API_KEY", ""))   # Auto-disable if no key
    # Fetch news for top N stocks only (to stay within 100 req/day limit)
    max_stocks_to_fetch: int = 20
    # Earnings/event keywords that trigger stock skip
    skip_keywords: tuple = ("results", "earnings", "quarterly", "dividend", "merger", "acquisition")


@dataclass
class TradingConfig:
    """Core trading parameters."""

    # ── Capital ──────────────────────────────────────────────────────
    initial_capital: float = float(os.getenv("INITIAL_CAPITAL", "15000"))

    # ── Risk management (SAFETY — do not loosen these) ───────────────
    max_risk_per_trade_pct: float = 1.5      # Max 1.5% of capital at risk per trade (sniper mode)
    max_trades_per_day: int = 3              # HARD ceiling — sniper mode: only 3 best trades/day
    max_losses_per_day: int = 2              # 2 total losing trades = stop for the day (sniper mode)
    daily_loss_limit_pct: float = 3.0        # Bot stops for the day if hit (Rs. amount)
    max_capital_deployed_pct: float = 80.0   # Max 80% of broker margin deployed at once
    risk_reward_ratio: float = 2.5           # R-multiple target (2.5R reward-to-risk)

    # ── Market hours ─────────────────────────────────────────────────
    market_open: time = time(9, 15)
    orb_end: time = time(9, 30)             # Opening range observation ends
    no_new_trades_after: time = time(14, 30) # 2:30 PM hard cutoff
    force_exit_time: time = time(15, 15)    # 3:15 PM — force-exit all positions
    market_close: time = time(15, 30)

    # ── Time windows — only trade during high-probability periods ─────
    trading_window_1_start: time = time(9, 30)
    trading_window_1_end: time = time(11, 30)
    trading_window_2_start: time = time(13, 0)
    trading_window_2_end: time = time(14, 30)

    # ── Lunch block — NO new trades during 11:30-13:00 (relaxed from 11:00-13:30) ──
    lunch_block_start: time = time(11, 30)
    lunch_block_end: time = time(13, 0)

    # ── Signal scoring — only trade if score >= threshold ─────────────
    # Sniper mode: 80+ required. ~8 out of 11 scoring factors must confirm.
    # 80+ = excellent setup. 90+ = exceptional (allows single-strategy exception).
    min_score_to_trade: int = 80

    # ── ORB-specific settings ─────────────────────────────────────────
    orb_min_range_pct: float = 0.3          # Skip if opening range < 0.3%
    orb_max_range_pct: float = 2.0          # Skip if opening range > 2%
    breakout_buffer_pct: float = 0.05       # Confirmation buffer above/below range

    # ── Gap filter ───────────────────────────────────────────────────
    gap_filter_pct: float = 1.5

    # ── Previous day level proximity ─────────────────────────────────
    prev_day_proximity_pct: float = 0.3

    # ── Volume spike confirmation ─────────────────────────────────────
    volume_spike_multiplier: float = 3.0         # Hard gate: 3× avg (sniper mode)
    volume_spike_high_multiplier: float = 5.0    # "High confidence" spike level
    volume_lookback: int = 20

    # ── RSI filter ────────────────────────────────────────────────────
    rsi_overbought_entry: float = 75.0
    rsi_oversold_entry: float = 25.0

    # ── Spread filter ────────────────────────────────────────────────
    spread_max_pct: float = 0.10

    # ── Smart partial exit ────────────────────────────────────────────
    partial_exit_enabled: bool = True
    partial_exit_rr: float = 1.0            # First exit at 1x RR
    final_exit_rr: float = 2.5             # Final exit at 2.5x RR (sniper mode)

    # ── Multi-strategy confluence (sniper mode) ───────────────────────
    min_confluence_count: int = 2           # At least 2 strategies must agree
    single_strategy_exception_score: int = 85  # Allow 1 strategy if score >= 85 (was 90 — too strict, 57K signals but zero confluence on 2026-03-09)

    # ── VIX graduated response (sniper mode) ──────────────────────────
    vix_normal_threshold: float = 18.0      # VIX < 18 = normal
    vix_caution_threshold: float = 20.0     # VIX 18-20 = caution (50% size, wider SL)
    # VIX > 20 = DANGER: no new trades at all
    vix_caution_size_pct: float = 50.0      # Position size in caution mode (50%)
    vix_caution_risk_pct: float = 0.75      # Risk per trade in caution mode

    # ── Choppiness Index filter (sniper mode) ─────────────────────────
    chop_threshold: float = 61.8            # CHOP > 61.8 = choppy market, reject signal
    chop_period: int = 14                   # Choppiness Index lookback period

    # ── 15-minute trend filter (sniper mode) ──────────────────────────
    trend_15m_enabled: bool = False          # Disabled: tick-level data doesn't produce real 15-min candles. Re-enable after implementing time-based resampling.
    trend_15m_flat_threshold_pct: float = 0.05  # EMAs within 0.05% = flat/neutral = skip

    # ── ATR expansion check (sniper mode) ─────────────────────────────
    atr_expansion_lookback: int = 5         # Compare current ATR to N candles ago
    atr_compression_penalty: int = 10       # Score penalty if ATR is compressing

    # ── Trailing stop-loss (improved profit management) ───────────────
    # Step 1: At 1% profit → move SL to breakeven (entry + charges)
    # Step 2: At 1.5R profit → trail SL at 1× ATR below peak (longs) / above trough (shorts)
    trailing_sl_enabled: bool = True
    breakeven_profit_pct: float = 1.0       # Move SL to breakeven at 1% profit
    trailing_activation_pct: float = 2.0    # Fallback pct (overridden by R-multiple in sniper mode)
    trailing_activation_r: float = 1.5      # Start trailing at 1.5R profit (sniper mode)
    trailing_distance_pct: float = 1.0      # Fallback trail distance (overridden by ATR in sniper mode)
    trailing_sl_pct: float = 0.3           # Legacy — used as fallback
    trailing_sl_atr_multiplier: float = 1.0 # Trail at 1× ATR from peak/trough (sniper mode)

    # ── ATR-based dynamic stop-loss (sniper mode) ─────────────────────
    atr_sl_multiplier_normal: float = 1.5   # SL = 1.5× ATR from entry (VIX < 18)
    atr_sl_multiplier_caution: float = 2.0  # SL = 2.0× ATR from entry (VIX 18-20)
    atr_sl_floor_pct: float = 0.5           # SL never tighter than 0.5% from entry
    atr_sl_ceiling_pct: float = 3.0         # SL never wider than 3% from entry
    adopted_sl_fallback_pct: float = 2.5    # Fallback SL for adopted positions (if no ATR data)

    # ── Win zone exit (70% of target reversal protection) ──────────────
    win_zone_target_pct: float = 0.70       # 70% of target = "win zone"
    win_zone_reversal_pct: float = 0.5      # Exit if reverses 0.5% from peak in win zone

    # ── Time-based exit rules ──────────────────────────────────────────
    late_session_sl_pct: float = 1.0        # Tighten SL to 1% after 2:30 PM
    profit_exit_time: time = time(15, 0)    # Exit any in-profit position after 3:00 PM

    # ── Re-entry prevention ────────────────────────────────────────────
    reentry_cooldown_minutes: int = 30      # Block re-entry for 30 min after exiting a stock

    # ── Broker-side SL orders ──────────────────────────────────────────
    sl_order_price_buffer: float = 0.50     # Rs. buffer between trigger and limit price

    # ── Consecutive loss circuit breaker ─────────────────────────────
    consecutive_loss_limit: int = 2
    consecutive_loss_cooldown_minutes: int = 60  # Pause trading for 60 min

    # ── Filters ──────────────────────────────────────────────────────
    min_volume_threshold: int = 50000      # Minimum volume for a valid tick
    min_trade_value: float = 100           # Skip if expected profit < Rs.100

    # ── Brokerage (Angel One intraday MIS) ───────────────────────────
    # Actual formula: max(Rs.5, min(Rs.20, 0.1% of trade value)) per order × 2 legs
    # e.g., Rs.1000 trade → Rs.5/leg, Rs.15000 trade → Rs.15/leg, Rs.25000+ → Rs.20/leg
    brokerage_flat_per_order: float = 20.0     # Rs.20 cap per order
    brokerage_min_per_order: float = 5.0       # Rs.5 floor per order
    brokerage_pct_per_order: float = 0.1       # 0.1% of trade value
    brokerage_per_order: float = 0             # Legacy field — kept for compat

    # NSE intraday charges (both legs combined):
    stt_pct: float = 0.025          # STT: 0.025% of sell-side value
    exchange_charges_pct: float = 0.00345  # Exchange charges: 0.00345% of turnover
    gst_pct: float = 18.0           # GST: 18% on (brokerage + exchange charges)
    sebi_charges_pct: float = 0.0001  # SEBI: 0.0001% of turnover
    stamp_duty_pct: float = 0.003   # Stamp duty: 0.003% on buy-side value

    # Skip trades where expected net profit (after all charges) < this.
    # Set to Rs.15 because minimum round-trip cost is Rs.12-15 (Angel One floor).
    min_expected_net_profit: float = 15.0

    # ── Mode — controlled from .env ──────────────────────────────────
    paper_trading: bool = os.getenv("PAPER_TRADING", "True").strip() == "True"
    suggest_only: bool = os.getenv("SUGGEST_ONLY", "True").strip() == "True"

    # ── Live trading confirmation window ─────────────────────────────
    # If True: when a signal scores 70+, push to dashboard with 30-second countdown.
    # User can reject within 30 seconds. If no rejection → auto-execute.
    use_confirmation_window: bool = os.getenv("USE_CONFIRMATION", "False").strip() == "True"
    confirmation_timeout_secs: int = 30

    # ── API retry settings ───────────────────────────────────────────
    api_max_retries: int = 3
    api_retry_delay: float = 1.0            # Base delay in seconds (doubles each attempt)

    # ── Duplicate order prevention ────────────────────────────────────
    # Cancel a PENDING order if it hasn't filled in this many seconds.
    pending_order_timeout_secs: float = 30.0

    # ── Market regime settings ────────────────────────────────────────
    regime_determination_time: time = time(10, 30)  # Decide regime at 10:30 AM
    gap_day_nifty_threshold_pct: float = 0.7     # >0.7% gap = gap day
    trending_nifty_move_pct: float = 0.5         # >0.5% move = trending
    range_bound_nifty_pct: float = 0.3           # <0.3% move = range bound
    volatile_vix_threshold: float = 18.0         # VIX > 18 = volatile
    volatile_nifty_range_pct: float = 1.5        # NIFTY range > 1.5% = volatile
    gap_day_wait_until: time = time(10, 0)       # On gap day, wait until 10 AM

    # ── Watchlist ────────────────────────────────────────────────────
    # True = download from Angel One instrument master at startup
    # False = use hardcoded DEFAULT_WATCHLIST in watchlist.py
    use_dynamic_watchlist: bool = True
    watchlist_max_size: int = 200

    # ── Analytics & Logging ──────────────────────────────────────────
    save_csv_log: bool = True
    csv_log_path: str = "logs/trades.csv"

    # ── Pre-market ───────────────────────────────────────────────────
    premarket_time: time = time(9, 0)            # Run pre-market checks at 9 AM
    check_trading_holiday: bool = True           # Skip if today is NSE holiday
    min_margin_pct_required: float = 0.5         # Must have 50% of capital available

    # ── Rate limiting (conservative: 50-60% of Angel One official limits) ──
    historical_rate_per_sec: float = float(os.getenv("HISTORICAL_RATE_PER_SEC", "1.0"))
    historical_rate_per_min: int = int(os.getenv("HISTORICAL_RATE_PER_MIN", "55"))
    ltp_rate_per_sec: float = float(os.getenv("LTP_RATE_PER_SEC", "5.0"))
    ltp_rate_per_min: int = int(os.getenv("LTP_RATE_PER_MIN", "200"))

    # ── Capital filter ─────────────────────────────────────────────────────
    min_net_profit: float = float(os.getenv("MIN_NET_PROFIT", "10.0"))
    max_required_move_pct: float = float(os.getenv("MAX_REQUIRED_MOVE_PCT", "3.0"))

    # ── OHLC fetch ─────────────────────────────────────────────────────────
    ohlc_batch_size: int = int(os.getenv("OHLC_BATCH_SIZE", "5"))
    ohlc_batch_gap: float = float(os.getenv("OHLC_BATCH_GAP", "2.0"))
    ohlc_max_retries: int = int(os.getenv("OHLC_MAX_RETRIES", "2"))

    def __post_init__(self):
        """Validate config values to catch misconfiguration early."""
        assert self.max_trades_per_day > 0, "max_trades_per_day must be > 0"
        assert self.max_losses_per_day > 0, "max_losses_per_day must be > 0"
        assert self.atr_sl_floor_pct < self.atr_sl_ceiling_pct, "ATR SL floor must be < ceiling"
        assert 0 < self.max_risk_per_trade_pct <= 5, "risk per trade must be 0-5%"
        assert self.lunch_block_start < self.lunch_block_end, "lunch block start must be before end"


@dataclass
class IndicatorConfig:
    """Technical indicator settings."""
    ema_fast: int = 9
    ema_slow: int = 21
    rsi_period: int = 14
    rsi_overbought: float = 70
    rsi_oversold: float = 30
    vwap_bounce_threshold_pct: float = 0.2   # Tightened from 0.3 to 0.2
    vwap_trend_min_ticks: int = 60           # Must be above VWAP for 60+ ticks (~30 min)
    atr_period: int = 14
    sr_lookback_days: int = 5                # S/R levels from last 5 days' candles


@dataclass
class AppConfig:
    """Master config combining all sub-configs."""
    broker: BrokerConfig = field(default_factory=BrokerConfig)
    firebase: FirebaseConfig = field(default_factory=FirebaseConfig)
    trading: TradingConfig = field(default_factory=TradingConfig)
    indicators: IndicatorConfig = field(default_factory=IndicatorConfig)
    news: NewsConfig = field(default_factory=NewsConfig)

    # Logging
    log_level: str = os.getenv("LOG_LEVEL", "INFO")
    log_file: str = "logs/trading_bot.log"


# Singleton config instance — imported everywhere in the codebase
config = AppConfig()
