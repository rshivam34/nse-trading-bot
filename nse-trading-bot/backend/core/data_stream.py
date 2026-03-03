"""
Data Stream — Real-time Price Data via WebSocket
=================================================
Connects to Angel One's WebSocket feed and receives live price ticks.

TODO (Phase 2): Implement with real SmartAPI WebSocket.
Currently provides mock tick generation for development.
"""

import logging
import threading
import time
import random

logger = logging.getLogger(__name__)


class DataStream:
    """Handles real-time price streaming from Angel One."""

    def __init__(self, broker):
        self.broker = broker
        self.is_streaming = False
        self.callback = None
        self._thread = None

    def subscribe(self, tokens: list, callback: callable):
        """
        Start streaming price data for given tokens.
        
        Args:
            tokens: List of Angel One instrument tokens
            callback: Function to call with each tick {stock, ltp, open, high, low, close, volume}
        
        TODO: Replace with real WebSocket:
            from SmartApi.smartWebSocketV2 import SmartWebSocketV2
            
            sws = SmartWebSocketV2(auth_token, api_key, client_code, feed_token)
            sws.on_data = callback
            sws.subscribe(correlation_id, mode, [{"exchangeType": 1, "tokens": tokens}])
            sws.connect()
        """
        self.callback = callback
        self.is_streaming = True
        logger.info(f"📡 [MOCK] Subscribed to {len(tokens)} tokens")

        # Mock: generate ticks in background thread
        self._thread = threading.Thread(target=self._mock_stream, args=(tokens,), daemon=True)
        self._thread.start()

    def _mock_stream(self, tokens: list):
        """Generate mock price ticks for development."""
        base_prices = {t: random.uniform(200, 3000) for t in tokens}

        while self.is_streaming:
            for token in tokens:
                base = base_prices[token]
                change = random.gauss(0, base * 0.002)
                ltp = base + change
                base_prices[token] = ltp

                tick = {
                    "token": token,
                    "ltp": round(ltp, 2),
                    "open": round(base, 2),
                    "high": round(ltp + abs(random.gauss(0, base * 0.001)), 2),
                    "low": round(ltp - abs(random.gauss(0, base * 0.001)), 2),
                    "close": round(ltp, 2),
                    "volume": random.randint(10000, 100000),
                }

                if self.callback:
                    self.callback(tick)

            time.sleep(1)  # Simulate ~1 tick per second

    def disconnect(self):
        """Stop streaming."""
        self.is_streaming = False
        logger.info("📡 Data stream disconnected")
