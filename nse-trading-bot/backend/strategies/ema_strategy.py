"""
EMA Crossover Strategy (Phase 2)
=================================
Trades when fast EMA crosses slow EMA.

Logic:
1. 9 EMA crosses above 21 EMA → LONG
2. 9 EMA crosses below 21 EMA → SHORT
3. SL: Below recent swing low (for LONG)
4. Target: 2× risk

TODO: Implement in Phase 2 after ORB is working.
"""

from strategies.base_strategy import BaseStrategy, Signal
from typing import Optional
import pandas as pd


class EMACrossoverStrategy(BaseStrategy):
    def __init__(self, trading_config, indicator_config):
        super().__init__(name="EMA_CROSS")
        self.config = trading_config
        self.indicators = indicator_config

    def check_signal(self, stock, token, candles, current_tick, market_context) -> Optional[Signal]:
        # TODO: Implement EMA crossover detection
        return None
