"""
VWAP Mean Reversion Strategy (Phase 2)
=======================================
Trades pullbacks to VWAP in trending stocks.

Logic:
1. Stock is trending (above/below VWAP for >30 min)
2. Price pulls back to within 0.3% of VWAP
3. A green candle forms (bounce confirmation)
4. Entry: at the close of the bounce candle
5. SL: Below VWAP by 0.3%
6. Target: Previous swing high

TODO: Implement in Phase 2 after ORB is working.
"""

from strategies.base_strategy import BaseStrategy, Signal
from typing import Optional
import pandas as pd


class VWAPStrategy(BaseStrategy):
    def __init__(self, trading_config, indicator_config):
        super().__init__(name="VWAP")
        self.config = trading_config
        self.indicators = indicator_config

    def check_signal(self, stock, token, candles, current_tick, market_context) -> Optional[Signal]:
        # TODO: Implement VWAP bounce detection
        return None
