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
class TradingConfig:
    """Core trading parameters."""

    # Capital
    initial_capital: float = float(os.getenv("INITIAL_CAPITAL", "1000"))

    # Risk management (SAFETY — do not increase these lightly)
    max_risk_per_trade_pct: float = 2.0      # Max 2% of capital per trade
    max_trades_per_day: int = 3               # Quality over quantity
    daily_loss_limit_pct: float = 3.0         # Stop bot if 3% daily loss
    risk_reward_ratio: float = 1.5            # Target = 1.5× the risk

    # Time rules
    market_open: time = time(9, 15)
    orb_end: time = time(9, 30)              # Opening range ends
    no_new_trades_after: time = time(14, 30)  # 2:30 PM
    force_exit_time: time = time(15, 15)      # 3:15 PM
    market_close: time = time(15, 30)

    # Opening Range Breakout settings
    orb_min_range_pct: float = 0.3           # Skip if range too narrow
    orb_max_range_pct: float = 2.0           # Skip if range too wide
    breakout_buffer_pct: float = 0.05        # Small buffer above/below range

    # Filters
    min_volume_threshold: int = 50000        # Minimum candle volume
    min_trade_value: float = 100             # Skip trades below ₹100 profit potential

    # Commissions (Angel One approximate)
    brokerage_per_order: float = 20          # ₹20 per order
    other_charges_pct: float = 0.05          # ~0.05% for STT, GST, etc.

    # Mode
    paper_trading: bool = True               # START IN PAPER MODE — flip to False for live
    suggest_only: bool = True                # If True, signals only — no auto-execution


@dataclass
class IndicatorConfig:
    """Technical indicator settings."""
    ema_fast: int = 9
    ema_slow: int = 21
    rsi_period: int = 14
    rsi_overbought: float = 70
    rsi_oversold: float = 30
    vwap_bounce_threshold_pct: float = 0.3   # Price within 0.3% of VWAP


@dataclass
class AppConfig:
    """Master config combining all sub-configs."""
    broker: BrokerConfig = field(default_factory=BrokerConfig)
    firebase: FirebaseConfig = field(default_factory=FirebaseConfig)
    trading: TradingConfig = field(default_factory=TradingConfig)
    indicators: IndicatorConfig = field(default_factory=IndicatorConfig)

    # Logging
    log_level: str = os.getenv("LOG_LEVEL", "INFO")
    log_file: str = "logs/trading_bot.log"


# Singleton config instance
config = AppConfig()
