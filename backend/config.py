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
    initial_capital: float = float(os.getenv("INITIAL_CAPITAL", "1000"))

    # ── Risk management (SAFETY — do not loosen these) ───────────────
    max_risk_per_trade_pct: float = 2.0      # Max 2% of capital at risk per trade
    max_trades_per_day: int = 15             # Safety ceiling (capital deployment is the real limit)
    max_losses_per_day: int = 3              # 3 total losing trades = stop for the day
    daily_loss_limit_pct: float = 3.0        # Bot stops for the day if hit (Rs. amount)
    max_capital_deployed_pct: float = 80.0   # Max 80% of broker margin deployed at once
    risk_reward_ratio: float = 1.5           # Used by VWAP / EMA strategies

    # ── Market hours ─────────────────────────────────────────────────
    market_open: time = time(9, 15)
    orb_end: time = time(9, 30)             # Opening range observation ends
    no_new_trades_after: time = time(14, 30) # 2:30 PM hard cutoff
    force_exit_time: time = time(15, 15)    # 3:15 PM — force-exit all positions
    market_close: time = time(15, 30)

    # ── Time windows — only trade during high-probability periods ─────
    trading_window_1_start: time = time(9, 30)
    trading_window_1_end: time = time(11, 0)
    trading_window_2_start: time = time(13, 30)
    trading_window_2_end: time = time(14, 30)

    # ── Time-based position size scaling ─────────────────────────────
    # Different times of day have different momentum characteristics.
    # Window 1 (morning): full size. Lunch lull: 50%. Window 2 (afternoon): 75%.
    position_size_window_1_pct: float = 100.0   # 9:30-11:00 — morning momentum
    position_size_lunch_pct: float = 50.0        # 11:00-13:30 — lunch lull
    position_size_window_2_pct: float = 75.0     # 13:30-14:30 — afternoon

    # ── Signal scoring — only trade if score >= threshold ─────────────
    # The scorer evaluates 11 conditions (see core/signal_scorer.py).
    # 70+ = good setup. 80+ = excellent setup. 90+ = exceptional.
    min_score_to_trade: int = 70

    # ── ORB-specific settings ─────────────────────────────────────────
    orb_min_range_pct: float = 0.3          # Skip if opening range < 0.3%
    orb_max_range_pct: float = 2.0          # Skip if opening range > 2%
    breakout_buffer_pct: float = 0.05       # Confirmation buffer above/below range

    # ── Gap filter ───────────────────────────────────────────────────
    gap_filter_pct: float = 1.5

    # ── Previous day level proximity ─────────────────────────────────
    prev_day_proximity_pct: float = 0.3

    # ── Volume spike confirmation ─────────────────────────────────────
    volume_spike_multiplier: float = 2.0
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
    final_exit_rr: float = 2.0             # Final exit at 2x RR (ORB only)

    # ── Trailing stop-loss (improved profit management) ───────────────
    # Step 1: At 1% profit → move SL to breakeven (entry + charges)
    # Step 2: At 2% profit → trail SL at 1% below peak (longs) / above trough (shorts)
    trailing_sl_enabled: bool = True
    breakeven_profit_pct: float = 1.0       # Move SL to breakeven at 1% profit
    trailing_activation_pct: float = 2.0    # Start trailing at 2% unrealized profit
    trailing_distance_pct: float = 1.0      # Trail at 1% from peak/trough
    trailing_sl_pct: float = 0.3           # Legacy — used as fallback
    trailing_sl_atr_multiplier: float = 0.5

    # ── Win zone exit (70% of target reversal protection) ──────────────
    win_zone_target_pct: float = 0.70       # 70% of target = "win zone"
    win_zone_reversal_pct: float = 0.5      # Exit if reverses 0.5% from peak in win zone

    # ── Time-based exit rules ──────────────────────────────────────────
    late_session_sl_pct: float = 1.0        # Tighten SL to 1% after 2:30 PM
    profit_exit_time: time = time(15, 0)    # Exit any in-profit position after 3:00 PM
    late_session_start: time = time(14, 30) # When to start tightening SLs

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
