"""
Technical Indicators — Common calculations used by strategies.
==============================================================
Uses pandas-ta library for standard indicators.
"""

import pandas as pd
import numpy as np


def calculate_ema(data: pd.Series, period: int) -> pd.Series:
    """Exponential Moving Average."""
    return data.ewm(span=period, adjust=False).mean()


def calculate_rsi(data: pd.Series, period: int = 14) -> pd.Series:
    """Relative Strength Index (0-100)."""
    delta = data.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))


def calculate_vwap(high: pd.Series, low: pd.Series, close: pd.Series, volume: pd.Series) -> pd.Series:
    """Volume Weighted Average Price."""
    typical_price = (high + low + close) / 3
    cumulative_tp_vol = (typical_price * volume).cumsum()
    cumulative_vol = volume.cumsum()
    return cumulative_tp_vol / cumulative_vol


def calculate_atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    """Average True Range — measures volatility."""
    tr1 = high - low
    tr2 = abs(high - close.shift())
    tr3 = abs(low - close.shift())
    true_range = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    return true_range.rolling(window=period).mean()


def detect_support_resistance(highs: pd.Series, lows: pd.Series, lookback: int = 20) -> dict:
    """Find recent support and resistance levels."""
    recent_high = highs.rolling(lookback).max().iloc[-1]
    recent_low = lows.rolling(lookback).min().iloc[-1]
    return {"resistance": recent_high, "support": recent_low}
