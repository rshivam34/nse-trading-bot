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


def choppiness_index(highs: pd.Series, lows: pd.Series, closes: pd.Series, period: int = 14) -> pd.Series:
    """
    Choppiness Index — measures whether market is trending or chopping sideways.

    Scale 0-100:
    - CHOP > 61.8 → market is choppy/sideways → DON'T trade breakouts
    - CHOP < 38.2 → market is trending → good for breakouts
    - 38.2-61.8 → transitional

    Formula:
        CHOP = 100 × LOG10(SUM(ATR(1), period) / (MaxHigh - MinLow)) / LOG10(period)
    """
    # ATR(1) is just the True Range for each bar
    tr1 = highs - lows
    tr2 = abs(highs - closes.shift())
    tr3 = abs(lows - closes.shift())
    true_range = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

    atr_sum = true_range.rolling(window=period).sum()
    max_high = highs.rolling(window=period).max()
    min_low = lows.rolling(window=period).min()

    high_low_range = max_high - min_low
    # Avoid division by zero
    high_low_range = high_low_range.replace(0, np.nan)

    chop = 100 * np.log10(atr_sum / high_low_range) / np.log10(period)
    return chop


def resample_to_15min(ohlc_5min: pd.DataFrame) -> pd.DataFrame:
    """
    Resample 5-minute OHLCV candles to 15-minute candles.

    Input DataFrame must have columns: Open, High, Low, Close, Volume.
    Groups every 3 consecutive 5-min candles into one 15-min candle.

    Returns a new DataFrame with 15-min OHLCV data (roughly 1/3 the rows).
    """
    if len(ohlc_5min) < 3:
        return pd.DataFrame()

    # Group every 3 rows into a 15-min candle
    n_groups = len(ohlc_5min) // 3
    if n_groups == 0:
        return pd.DataFrame()

    # Trim to exact multiple of 3 (drop oldest partial group)
    trimmed = ohlc_5min.iloc[-(n_groups * 3):]

    groups = np.arange(len(trimmed)) // 3
    result = trimmed.groupby(groups).agg({
        "Open": "first",
        "High": "max",
        "Low": "min",
        "Close": "last",
        "Volume": "sum",
    }).reset_index(drop=True)

    return result


def candle_price_confirmation(
    open_price: float,
    high_price: float,
    low_price: float,
    close_price: float,
    min_move_pct: float = 0.3,
    min_body_ratio: float = 0.60,
) -> bool:
    """
    Check if a candle shows real directional conviction.

    Two conditions must be met:
    1. Price moved at least min_move_pct in one direction (|close - open| / open >= 0.3%)
    2. Body-to-range ratio >= min_body_ratio (body is >= 60% of total range)
       A high body ratio means the candle closed near its extreme — strong conviction.
       A low body ratio (long wicks) means indecision — not a clean move.

    Returns True if candle passes both conditions, False otherwise.
    """
    if open_price <= 0 or high_price <= low_price:
        return False

    # Condition 1: minimum price move
    move_pct = abs(close_price - open_price) / open_price * 100
    if move_pct < min_move_pct:
        return False

    # Condition 2: body-to-range ratio (candle body / total range)
    body = abs(close_price - open_price)
    candle_range = high_price - low_price
    if candle_range <= 0:
        return False

    body_ratio = body / candle_range
    return body_ratio >= min_body_ratio


def is_atr_expanding(candles: pd.DataFrame, atr_period: int = 14, lookback: int = 5) -> bool:
    """
    Check if ATR is expanding (current ATR > ATR from 'lookback' candles ago).

    Used to confirm breakout momentum — compressing ATR means breakouts
    are less likely to follow through.

    Returns True if ATR is expanding, False if compressing.
    Returns True if insufficient data (give benefit of the doubt).
    """
    if len(candles) < atr_period + lookback + 1:
        return True  # Not enough data — don't penalize

    atr = calculate_atr(candles["High"], candles["Low"], candles["Close"], period=atr_period)
    current_atr = atr.iloc[-1]
    past_atr = atr.iloc[-(lookback + 1)]

    if np.isnan(current_atr) or np.isnan(past_atr):
        return True

    return current_atr > past_atr


def get_current_atr(candles: pd.DataFrame, period: int = 14) -> float:
    """
    Get the current ATR value from candle data.
    Returns 0.0 if insufficient data.
    """
    if len(candles) < period + 1:
        return 0.0

    atr = calculate_atr(candles["High"], candles["Low"], candles["Close"], period=period)
    val = atr.iloc[-1]
    return float(val) if not np.isnan(val) else 0.0


def get_current_choppiness(candles: pd.DataFrame, period: int = 14) -> float:
    """
    Get the current Choppiness Index value from candle data.
    Returns 50.0 (neutral — don't block) if insufficient data.
    Other filters (volume, score, confluence) still protect during early session.
    """
    if len(candles) < period + 1:
        return 50.0

    chop = choppiness_index(candles["High"], candles["Low"], candles["Close"], period=period)
    val = chop.iloc[-1]
    return round(float(val), 1) if not np.isnan(val) else 50.0


def get_15min_trend(candles_5min: pd.DataFrame, flat_threshold_pct: float = 0.05) -> str:
    """
    Determine 15-minute trend using 9 EMA and 21 EMA on resampled candles.

    Returns:
        "BULLISH" if 9 EMA > 21 EMA (by more than flat_threshold_pct)
        "BEARISH" if 9 EMA < 21 EMA (by more than flat_threshold_pct)
        "NEUTRAL" if EMAs are flat/intertwined (within flat_threshold_pct)
        "NEUTRAL" if insufficient data
    """
    candles_15m = resample_to_15min(candles_5min)
    if len(candles_15m) < 22:
        return "NEUTRAL"

    closes = candles_15m["Close"]
    ema9 = float(closes.ewm(span=9, adjust=False).mean().iloc[-1])
    ema21 = float(closes.ewm(span=21, adjust=False).mean().iloc[-1])

    if ema21 == 0:
        return "NEUTRAL"

    diff_pct = abs(ema9 - ema21) / ema21 * 100

    if diff_pct < flat_threshold_pct:
        return "NEUTRAL"
    elif ema9 > ema21:
        return "BULLISH"
    else:
        return "BEARISH"
