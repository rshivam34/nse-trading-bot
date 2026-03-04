"""
Data Stream — Real-time Price Data via Angel One WebSocket
==========================================================
Uses SmartWebSocketV2 to receive live price ticks for all watchlist stocks.

How the WebSocket works:
- Angel One sends price data in "subscription modes":
  Mode 1 (LTP): Only last traded price — fast, minimal data
  Mode 2 (Quote): LTP + open/high/low + volume — what we need
  Mode 3 (Full): Everything including market depth — overkill for us

Important: Prices from the WebSocket are in PAISE (1/100 of a rupee).
So Rs.2450.75 comes as 245075. We divide by 100 to get rupees.

The WebSocket runs in its own thread. When a price tick arrives,
it calls our callback function which is handled by main.py → scanner.py.

Production upgrades:
- Before each reconnect attempt, refresh broker auth tokens so the
  new WebSocket connection uses valid credentials.
- After successful reconnect, call on_reconnect() so main.py can
  reconcile positions (check if anything was closed while offline).
"""

import logging
import threading
import time
from typing import Callable, Optional

from SmartApi.smartWebSocketV2 import SmartWebSocketV2  # Angel One WebSocket library

logger = logging.getLogger(__name__)

# Subscription mode 2 = full quote (LTP + OHLC + Volume)
SUBSCRIPTION_MODE = 2
NSE_EXCHANGE_TYPE = 1  # 1 = NSE, 2 = NFO, 3 = BSE


class DataStream:
    """
    Manages the real-time price stream from Angel One WebSocket.

    Flow:
    1. subscribe() is called with a list of stock tokens
    2. We connect to Angel One's WebSocket server
    3. On connection open, we subscribe to all tokens
    4. Every price tick calls our callback (which goes to the scanner)
    5. If connection drops, we refresh auth tokens and auto-reconnect
    6. After successful reconnect, on_reconnect callback is invoked
    """

    def __init__(self, broker):
        # broker is the BrokerConnection — we need its auth tokens
        self.broker = broker
        self.is_streaming = False
        self.callback: Optional[Callable] = None

        # on_reconnect: set this from main.py to run position reconciliation
        # after a WebSocket reconnect (in case positions closed while offline).
        # Signature: on_reconnect() → None
        self.on_reconnect: Optional[Callable] = None

        # Internal WebSocket object
        self._sws: Optional[SmartWebSocketV2] = None
        self._thread: Optional[threading.Thread] = None

        # Token list for re-subscription on reconnect
        self._subscribed_tokens: list = []

        # Correlation ID: a unique string for this subscription session
        self._correlation_id = "trading_bot_stream"

        # Reconnect settings
        self._reconnect_delay = 5    # Seconds between reconnect attempts
        self._max_reconnects = 10    # Give up after this many failed attempts
        self._reconnect_count = 0    # Current consecutive failure count

        # Track if this is a reconnect (not the first connection)
        self._is_reconnect = False

        # Price cache: latest tick data for every token, updated on every WebSocket tick.
        # Used by order_manager to check SL/target without making API calls.
        # Key = token string (e.g. "2885"), Value = tick dict with ltp, open, high, low, etc.
        self.price_cache: dict[str, dict] = {}

    # ──────────────────────────────────────────────────────────
    # Public API
    # ──────────────────────────────────────────────────────────

    def subscribe(self, tokens: list, callback: Callable):
        """
        Start streaming price data for the given instrument tokens.

        Args:
            tokens: List of Angel One instrument token strings (e.g., ["2885", "1594"])
            callback: Function to call for each tick.
                      Receives a dict: {token, ltp, open, high, low, close, volume}
        """
        if not self.broker.auth_token or not self.broker.feed_token:
            logger.error("Cannot stream: broker not authenticated. Call broker.connect() first.")
            return

        self.callback = callback
        self._subscribed_tokens = tokens
        self.is_streaming = True

        logger.info(f"Starting WebSocket stream for {len(tokens)} stocks...")

        # Launch the WebSocket in its own background thread
        # (WebSocket blocks, so it needs its own thread to not freeze the main bot)
        self._thread = threading.Thread(
            target=self._run_websocket,
            name="DataStreamThread",
            daemon=True,  # Daemon = thread dies when main program exits
        )
        self._thread.start()

    def get_ltp(self, token: str) -> float:
        """
        Get last traded price from WebSocket cache. Zero API calls.

        Returns 0.0 if the token has no cached data yet (WebSocket
        hasn't sent a tick for it). Callers should handle 0.0 gracefully.
        """
        tick = self.price_cache.get(token)
        if tick:
            return tick.get("ltp", 0.0)
        return 0.0

    def disconnect(self):
        """Stop streaming and close the WebSocket."""
        self.is_streaming = False
        if self._sws:
            try:
                self._sws.close_connection()
            except Exception as e:
                logger.debug(f"WebSocket close error: {e}")
        logger.info("Data stream disconnected")

    # ──────────────────────────────────────────────────────────
    # WebSocket Lifecycle
    # ──────────────────────────────────────────────────────────

    def _run_websocket(self):
        """
        Creates and runs the WebSocket connection.
        Handles reconnection with token refresh if the connection drops.

        Key production behavior:
        - Before each reconnect, call broker.refresh_session() to get fresh tokens.
          Angel One's JWT tokens can expire. A reconnect with stale tokens will
          immediately fail, creating an infinite loop.
        - After successful reconnect (_is_reconnect=True), _on_open() calls
          on_reconnect() so main.py can reconcile positions.
        """
        while self.is_streaming and self._reconnect_count < self._max_reconnects:
            try:
                # Before reconnecting: refresh auth tokens
                # (no-op on first connection, important on subsequent reconnects)
                if self._is_reconnect:
                    logger.info("Refreshing auth tokens before reconnect...")
                    refreshed = self.broker.refresh_session()
                    if not refreshed:
                        logger.error(
                            "Token refresh failed before reconnect — "
                            "WebSocket may reject the connection"
                        )
                    else:
                        logger.info("Auth tokens refreshed successfully")

                # Create a fresh WebSocket object (always — can't reuse after close)
                self._sws = SmartWebSocketV2(
                    auth_token=self.broker.auth_token,
                    api_key=self.broker.config.api_key,
                    client_code=self.broker.config.client_id,
                    feed_token=self.broker.feed_token,
                )

                # Wire up event handlers
                self._sws.on_open = self._on_open
                self._sws.on_data = self._on_data
                self._sws.on_error = self._on_error
                self._sws.on_close = self._on_close

                logger.info("Connecting to Angel One WebSocket...")
                self._sws.connect()  # This blocks until connection closes

            except Exception as e:
                logger.error(f"WebSocket error: {e}")

            # If we reach here, the connection was lost or an exception occurred
            if not self.is_streaming:
                break  # Intentional disconnect — stop

            self._reconnect_count += 1
            self._is_reconnect = True  # Flag future iterations as reconnects
            logger.warning(
                f"WebSocket disconnected. Reconnecting in {self._reconnect_delay}s "
                f"(attempt {self._reconnect_count}/{self._max_reconnects})..."
            )
            time.sleep(self._reconnect_delay)

        if self._reconnect_count >= self._max_reconnects:
            logger.error(
                "Max reconnection attempts reached. Data stream stopped. "
                "Restart the bot manually."
            )
            self.is_streaming = False

    def _on_open(self, wsapp):
        """
        Called when WebSocket connection is established.
        This is where we tell Angel One which stocks to stream.
        After a reconnect, we also call on_reconnect() to reconcile positions.
        """
        logger.info("WebSocket connected! Subscribing to price feeds...")
        self._reconnect_count = 0  # Reset failure counter on success

        # Format tokens for Angel One's subscription format
        # Angel One wants: [{"exchangeType": 1, "tokens": ["2885", "1594", ...]}]
        token_list = [{"exchangeType": NSE_EXCHANGE_TYPE, "tokens": self._subscribed_tokens}]

        try:
            self._sws.subscribe(
                correlation_id=self._correlation_id,
                mode=SUBSCRIPTION_MODE,
                token_list=token_list,
            )
            logger.info(f"Subscribed to {len(self._subscribed_tokens)} instruments")
        except Exception as e:
            logger.error(f"Subscription error: {e}")
            return

        # After a reconnect, notify main.py to reconcile positions
        # (verify our open positions still match what the broker shows)
        if self._is_reconnect and self.on_reconnect is not None:
            try:
                logger.info("Triggering post-reconnect position reconciliation...")
                self.on_reconnect()
            except Exception as e:
                logger.error(f"on_reconnect callback error: {e}")

    def _on_data(self, wsapp, message):
        """
        Called every time a new price tick arrives from Angel One.

        The message is a Python dict (already parsed from binary/JSON).
        We convert it to our standard tick format and call the scanner callback.

        IMPORTANT: Angel One sends prices in PAISE (1 rupee = 100 paise).
        We must divide by 100 to get rupees.

        This handler is fully wrapped in try/except — a bad tick MUST NOT
        crash the WebSocket thread. We log and skip bad ticks silently.
        """
        try:
            tick = self._parse_tick(message)
            if tick:
                # Update price cache (zero-cost — just a dict write)
                self.price_cache[tick["token"]] = tick
                if self.callback:
                    self.callback(tick)
        except Exception as e:
            # Log bad tick at WARNING so it's visible but doesn't stop trading.
            # Include token if available so we can identify the problematic instrument.
            token = ""
            try:
                token = str(message.get("token", "")) if isinstance(message, dict) else ""
            except Exception:
                pass
            logger.warning(
                f"Bad tick skipped (token={token or '?'}): {type(e).__name__}: {e}"
            )

    def _on_error(self, wsapp, error):
        """Called when a WebSocket error occurs."""
        logger.error(f"WebSocket error: {error}")

    def _on_close(self, wsapp, *args, **kwargs):
        """Called when the WebSocket connection closes."""
        logger.warning("WebSocket connection closed")

    # ──────────────────────────────────────────────────────────
    # Tick Parsing
    # ──────────────────────────────────────────────────────────

    def _parse_tick(self, raw: dict) -> Optional[dict]:
        """
        Convert Angel One's raw WebSocket message into our standard tick format.

        Angel One raw tick (Mode 2 — Quote):
        {
            "subscription_mode": 2,
            "exchange_type": 1,
            "token": "2885",
            "last_traded_price": 245075,       <- in PAISE
            "last_traded_quantity": 10,
            "average_traded_price": 244500,    <- in PAISE
            "volume_trade_for_the_day": 123456,
            "open_price_of_the_day": 244000,   <- in PAISE
            "high_price_of_the_day": 246000,   <- in PAISE
            "low_price_of_the_day": 243000,    <- in PAISE
            "closed_price": 243500,            <- previous day close, in PAISE
        }

        Our standard tick format:
        {
            "token": "2885",
            "ltp": 2450.75,         <- in RUPEES
            "open": 2440.0,
            "high": 2460.0,
            "low": 2430.0,
            "close": 2435.0,
            "volume": 123456,
            "avg_price": 2445.0,
        }
        """
        if not raw or not isinstance(raw, dict):
            return None

        token = str(raw.get("token", ""))
        if not token:
            return None

        def paise_to_rupees(paise: int) -> float:
            """Convert paise to rupees (divide by 100)."""
            return round(paise / 100, 2) if paise else 0.0

        ltp = paise_to_rupees(raw.get("last_traded_price", 0))
        open_price = paise_to_rupees(raw.get("open_price_of_the_day", 0))
        high_price = paise_to_rupees(raw.get("high_price_of_the_day", 0))
        low_price = paise_to_rupees(raw.get("low_price_of_the_day", 0))
        close_price = paise_to_rupees(raw.get("closed_price", 0))
        volume = raw.get("volume_trade_for_the_day", 0)
        avg_price = paise_to_rupees(raw.get("average_traded_price", 0))

        if ltp == 0:
            return None  # Invalid tick

        return {
            "token": token,
            "ltp": ltp,
            "open": open_price or ltp,
            "high": high_price or ltp,
            "low": low_price or ltp,
            "close": close_price or ltp,
            "volume": volume,
            "avg_price": avg_price,
        }
