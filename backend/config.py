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
    initial_capital: float = float(os.getenv("INITIAL_CAPITAL", "30000"))

    # ── Risk management (SAFETY — do not loosen these) ───────────────
    max_risk_per_trade_pct: float = 1.5      # Max 1.5% of capital at risk per trade (sniper mode)
    max_trades_per_day: int = 5              # HARD ceiling — increased from 3 to get more opportunities
    max_losses_per_day: int = 3              # 3 total losing trades = stop for the day
    daily_loss_limit_pct: float = 3.0        # Bot stops for the day if hit (Rs. amount)
    max_capital_deployed_pct: float = 80.0   # Max 80% of broker margin deployed at once
    risk_reward_ratio: float = 1.5           # R-multiple target (2.0R = 2% move = full daily range on large caps = never hit. 1.5R = 1.5% move = achievable on trending days. Breakeven win rate = 40%)

    # ── Market hours ─────────────────────────────────────────────────
    market_open: time = time(9, 15)
    orb_end: time = time(9, 30)             # Opening range observation ends
    no_new_trades_after: time = time(13, 0)  # 1:00 PM hard cutoff (afternoon entries don't have enough time for 1.5R target before 3:15 force exit)
    force_exit_time: time = time(15, 15)    # 3:15 PM — force-exit all positions
    market_close: time = time(15, 30)

    # ── Time windows — only trade during high-probability periods ─────
    trading_window_1_start: time = time(9, 30)
    trading_window_1_end: time = time(11, 30)
    trading_window_2_start: time = time(13, 0)
    trading_window_2_end: time = time(13, 0)

    # ── Lunch block — NO new trades during 11:30-13:00 (relaxed from 11:00-13:30) ──
    lunch_block_start: time = time(11, 30)
    lunch_block_end: time = time(13, 0)

    # ── Signal scoring — only trade if score >= threshold ─────────────
    # 14 scoring factors (11 original + 3 new: macro, sector, fundamental).
    # New bonus factors (macro +10, sector +5, fundamental +5) inflate scores,
    # so threshold raised from 75 to 80 to compensate.
    # Score 80 = strong signal with good macro/sector alignment.
    min_score_to_trade: int = 80

    # ── ORB-specific settings ─────────────────────────────────────────
    orb_min_range_pct: float = 0.5          # Skip if opening range < 0.5% (was 0.3% — noise, just spread on Rs.1000 stock)
    orb_max_range_pct: float = 2.0          # Skip if opening range > 2%
    breakout_buffer_pct: float = 0.15       # Confirmation buffer above/below range (was 0.05% — caught tail-end reversals, not real breakouts)

    # ── Gap filter ───────────────────────────────────────────────────
    gap_filter_pct: float = 1.5

    # ── Previous day level proximity ─────────────────────────────────
    prev_day_proximity_pct: float = 0.3

    # ── Volume / RVOL (Relative Volume) ──────────────────────────────────
    # RVOL compares current candle volume to the 10-day TOD (time-of-day)
    # average for the same 5-min slot. Much better than comparing to recent
    # intraday candles because volume has a strong intraday pattern.
    rvol_tod_multiplier: float = 2.0             # RVOL gate when TOD data available (2x)
    rvol_session_multiplier: float = 2.0         # Fallback when < 5 days TOD data (was 3x — too strict, blocked 80% of signals on 2026-03-17)
    rvol_tod_min_days: int = 3                   # Minimum days of TOD data before using TOD comparison (was 5 — bot only had 3 days of data, TOD never activated)
    rvol_expiry_multiplier: float = 3.0          # RVOL gate on F&O expiry Thursdays (inflated rollover volumes)
    volume_spike_multiplier: float = 3.0         # Legacy: used by strategies internally (unchanged)
    volume_spike_high_multiplier: float = 5.0    # "High confidence" spike level (for scoring)
    volume_lookback: int = 20                    # Session average lookback (fallback)

    # ── ADV (Average Daily Volume) filter ─────────────────────────────────
    # Rejects illiquid stocks that can trap you with wide spreads and poor fills
    min_adv_shares: int = 500000                 # 5 lakh shares minimum 20-day ADV
    adv_lookback_days: int = 20                  # ADV calculation period

    # ── Price confirmation on triggering candle ────────────────────────────
    # The candle that triggers the signal must show real directional conviction
    price_confirm_move_pct: float = 0.3          # Candle must move at least 0.3% in one direction
    price_confirm_body_ratio: float = 0.60       # Body (|close-open|) must be >= 60% of range (high-low)

    # ── Minimum traded value per candle ─────────────────────────────────────
    # Ensures the candle represents real institutional interest, not just a few small orders
    min_candle_traded_value: float = 500000.0    # Rs. 5 lakh (price × volume)

    # ── NIFTY 50 volume spike (macro-driven flag) ──────────────────────────
    # If NIFTY itself shows elevated RVOL, the stock signal may be driven by
    # macro/index moves rather than stock-specific catalysts. Flagged, not rejected.
    nifty_volume_spike_multiplier: float = 2.0   # NIFTY RVOL >= 2x TOD avg = macro flag

    # ── Volume profile persistence ──────────────────────────────────────────
    volume_profile_path: str = "logs/volume_profiles.json"

    # ── RSI filter ────────────────────────────────────────────────────
    rsi_overbought_entry: float = 75.0
    rsi_oversold_entry: float = 25.0

    # ── Spread filter ────────────────────────────────────────────────
    spread_max_pct: float = 0.10

    # ── Smart partial exit ────────────────────────────────────────────
    partial_exit_enabled: bool = True
    partial_exit_rr: float = 1.0            # First exit at 1.0x RR
    final_exit_rr: float = 1.5             # Final exit at 1.5x RR (aligned with risk_reward_ratio)

    # ── Multi-strategy confluence (DEPRECATED — Option C removed this gate)
    # Kept for pre-flight check backwards compatibility. Not used as a filter.
    min_confluence_count: int = 1           # No longer enforced (was 2)
    single_strategy_exception_score: int = 75  # No longer used (score gate in min_score_to_trade)

    # ── VIX 3-zone response (Indian market calibrated) ────────────────
    # India VIX typical range: 10-25. Normal: 12-18. Median ~15.
    # NORMAL:  VIX < 18  → 100% size, 1.5× ATR SL. Standard conditions.
    # DANGER:  VIX >= 18 → 0% size, no new trades. ALL elevated VIX = sit out.
    # Why: VIX > 18 has only occurred during wars/tariffs/crises (Apr 2025, May 2025, Mar 2026).
    #       These are NOT normal conditions. The bot makes money in VIX 10-18 (90% of trading days).
    #       Trading during VIX 18+ adds risk without proportional reward.
    vix_normal_threshold: float = 18.0      # VIX < 18 = NORMAL (100% size)
    vix_elevated_threshold: float = 18.0    # Same as DANGER (no intermediate zone)
    vix_caution_threshold: float = 18.0     # VIX >= 18 = DANGER (all trades blocked — equity AND F&O)
    vix_elevated_size_pct: float = 0.0      # All zones above NORMAL = blocked (0% size)
    vix_elevated_risk_pct: float = 0.0      # No risk allowed above VIX 18
    vix_caution_size_pct: float = 0.0       # No trades above VIX 18
    vix_caution_risk_pct: float = 0.0       # No trades above VIX 18

    # ── Strategy-specific VIX adjustments ───────────────────────────
    # VWAP bounces depend on orderly institutional flow at VWAP.
    # In VIX > 22, price whipsaws through VWAP repeatedly — "bounces" are noise.
    vwap_bounce_vix_penalty_threshold: float = 18.0   # VIX above this → penalize VWAP_BOUNCE (aligns with VIX NORMAL/CAUTION boundary — VWAP bounces degrade above VIX 18 as directional strategies take over)
    vwap_bounce_vix_penalty: int = 15                  # Score penalty for VWAP_BOUNCE at high VIX

    # ── Choppiness Index filter (sniper mode) ─────────────────────────
    chop_threshold: float = 70.0            # CHOP > 70 = choppy market, reject signal (61.8 was for daily candles; 70 is appropriate for 5-min intraday candles where moderate trends show CHOP ~60-65)
    chop_period: int = 14                   # Choppiness Index lookback period

    # ── 15-minute trend filter (sniper mode) ──────────────────────────
    trend_15m_enabled: bool = False          # Disabled: tick-level data doesn't produce real 15-min candles. Re-enable after implementing time-based resampling.
    trend_15m_flat_threshold_pct: float = 0.05  # EMAs within 0.05% = flat/neutral = skip

    # ── ATR expansion check (sniper mode) ─────────────────────────────
    atr_expansion_lookback: int = 5         # Compare current ATR to N candles ago
    atr_compression_penalty: int = 10       # Score penalty if ATR is compressing

    # ── Trailing stop-loss (improved profit management) ───────────────
    # Step 1: At 0.7% profit → move SL to breakeven (entry price)
    # Step 2: At 1.0R → partial exit 50%, trail remaining at 1.5× ATR from peak/trough
    trailing_sl_enabled: bool = True
    breakeven_profit_pct: float = 0.5       # Move SL to breakeven at 0.5% profit
    trailing_activation_pct: float = 2.0    # Fallback pct (overridden by R-multiple in sniper mode)
    trailing_activation_r: float = 1.5      # Start trailing at 1.5R profit (safety net for non-partial path; partial exit at 1.0R activates trailing directly)
    trailing_distance_pct: float = 1.0      # Fallback trail distance (overridden by ATR in sniper mode)
    trailing_sl_pct: float = 0.3           # Legacy — used as fallback
    trailing_sl_atr_multiplier: float = 1.5 # Trail at 1.5× ATR from peak/trough (was 1×, too tight — winners stopped at 0.5R)

    # ── ATR-based dynamic stop-loss (sniper mode) ─────────────────────
    atr_sl_multiplier_normal: float = 1.5    # SL = 1.5× ATR (VIX < 18, NORMAL — 2.0× gave 2-3% SL which is too wide for intraday targets)
    atr_sl_multiplier_elevated: float = 2.0 # Same as CAUTION (ELEVATED zone disabled)
    atr_sl_multiplier_caution: float = 2.0  # SL = 2.0× ATR (VIX 18-25, CAUTION)
    atr_sl_floor_pct: float = 1.0           # SL never tighter than 1.0% from entry
    atr_sl_ceiling_pct: float = 1.5         # SL never wider than 1.5% from entry (was 3% — too wide for intraday. With 1.5R target, 3% SL = 4.5% target = impossible)
    adopted_sl_fallback_pct: float = 2.5    # Fallback SL for adopted positions (if no ATR data)

    # ── Win zone exit (70% of target reversal protection) ──────────────
    win_zone_target_pct: float = 0.70       # 70% of target = "win zone"
    win_zone_reversal_pct: float = 0.5      # Exit if reverses 0.5% from peak in win zone

    # ── Time-based exit rules ──────────────────────────────────────────
    late_session_sl_pct: float = 1.0        # Tighten SL to 1% after 2:30 PM
    profit_exit_time: time = time(15, 0)    # Exit any in-profit position after 3:00 PM

    # ── Entry spacing & re-entry prevention ─────────────────────────────
    min_entry_spacing_minutes: int = 10     # Minimum 10 min between ANY two entries (prevents correlated bets — e.g., 2 SHORTs in 19 seconds)
    reentry_cooldown_minutes: int = 15      # Cooldown after exiting a stock (was 5 — too short, catches same failing setup. 15 min lets the setup fully reset)

    # ── Broker-side SL orders ──────────────────────────────────────────
    sl_order_price_buffer: float = 0.50     # Rs. MINIMUM buffer between trigger and limit price
    sl_order_price_buffer_pct: float = 0.1  # 0.1% of price as buffer (used if > flat Rs.0.50 — protects expensive stocks like HAL Rs.3647 where Rs.0.50 = 0.014%)

    # ── Consecutive loss circuit breaker ─────────────────────────────
    consecutive_loss_limit: int = 2
    consecutive_loss_cooldown_minutes: int = 15  # Brief pause after consecutive losses (was 60 — arbitrary; max_losses_per_day already handles daily limits)

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
    exchange_charges_pct: float = 0.00297  # Exchange charges: 0.00297% of turnover (NSE equity, verified Mar 2026)
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
    volatile_vix_threshold: float = 18.0         # VIX > 18 = volatile regime (aligned with VIX zones: NORMAL < 18)
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

    # ── Intraday leverage ─────────────────────────────────────────────────
    # Angel One applies MIS leverage at order time (not as a balance).
    # When the RMS API returns availableintradaypayin=0 (common), we estimate
    # buying power as cash × this multiplier. Conservative 4x (most NIFTY 200
    # stocks get 4-5x). The broker will reject if actual margin is insufficient.
    intraday_leverage_multiplier: float = 4.0

    # ── Capital filter ─────────────────────────────────────────────────────
    min_net_profit: float = float(os.getenv("MIN_NET_PROFIT", "10.0"))
    max_required_move_pct: float = float(os.getenv("MAX_REQUIRED_MOVE_PCT", "3.0"))

    # ── OHLC fetch ─────────────────────────────────────────────────────────
    ohlc_batch_size: int = int(os.getenv("OHLC_BATCH_SIZE", "5"))
    ohlc_batch_gap: float = float(os.getenv("OHLC_BATCH_GAP", "2.0"))
    ohlc_max_retries: int = int(os.getenv("OHLC_MAX_RETRIES", "2"))

    # ── Macro Analysis (NIFTY DMA + Market Stance) ─────────────────────
    macro_analysis_enabled: bool = True
    macro_score_modifier: int = 10        # +10 if aligned with NIFTY DMA, -10 if against

    # ── Market Stance (controls max trades + sizing) ────────────────────
    stance_aggressive_max_trades: int = 5   # VIX < 18 + above both DMAs
    stance_moderate_max_trades: int = 3     # VIX < 18 + below 50 DMA but above 200
    stance_defensive_max_trades: int = 2    # VIX 18-25 OR below 200 DMA

    # ── Sector Analysis ─────────────────────────────────────────────────
    sector_analysis_enabled: bool = True
    sector_score_modifier: int = 5        # +5 for LEADING/IMPROVING, -5 for WEAKENING/LAGGING

    # ── Fundamental Filter ──────────────────────────────────────────────
    fundamental_filter_enabled: bool = True
    fundamental_cache_path: str = "logs/fundamental_cache.json"
    fundamental_cache_expiry_days: int = 7
    red_flag_penalty: int = 10            # -10 for any red flag (ROE<10%, D/E>2, EPS<0)
    fair_value_overvalued_penalty: int = 5   # -5 if PE > 2x sector average
    fair_value_undervalued_bonus: int = 5    # +5 if PE < 0.7x sector average
    earnings_skip_enabled: bool = True       # Hard skip stocks with earnings this week

    # ── F&O-ONLY MODE (FINAL DECISION 2026-05-02) ─────────────────────
    # Decision based on backtest comparison:
    #   - Equity intraday over 60-day war window: 1 trade, all -Rs.35 to -Rs.58 loss (consistent small drag)
    #   - F&O has asymmetric edge (+Rs.633 in 1 NIFTY trade in earlier test)
    #   - Decision: disable equity entirely, allocate full capital to F&O
    # To re-enable equity: set equity_enabled = True
    equity_enabled: bool = False             # F&O-ONLY MODE — equity scanner disabled
    options_capital_allocation: float = 30000.0  # Starting at Rs.30K initially (will scale up after live validation)
    equity_capital_allocation: float = 0.0       # Equity disabled

    # ── NIFTY/BANKNIFTY Options ─────────────────────────────────────
    options_enabled: bool = True
    options_max_trades_per_day: int = 4      # raised from hardcoded 2 — was the daily cap
    options_sl_pct: float = 30.0            # SL at 30% premium loss
    options_target_pct: float = 50.0        # Target at 50% premium gain
    options_exit_time: time = time(14, 0)   # Exit by 2 PM (theta decay)
    options_max_premium: float = 700.0      # Max premium per lot (Rs.) — raised from 500 to allow BANKNIFTY
    options_lots_per_trade: int = 1          # explicit — was implicit 1
    nifty_lot_size: int = 25
    banknifty_lot_size: int = 15

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
