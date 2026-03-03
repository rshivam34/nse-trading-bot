"""
Broker Connection — Angel One SmartAPI Wrapper
===============================================
Handles authentication with Angel One using TOTP,
places/cancels orders, and queries positions/prices.

How authentication works:
- Angel One uses API Key + Client ID + Password + TOTP (like Google Authenticator)
- TOTP rotates every 30 seconds, so we generate it fresh on each login
- After login, we get a JWT token used for all API calls

Production features:
- _api_with_retry(): wraps every API call with exponential backoff (1s → 2s → 4s)
- get_prev_day_ohlc(): fetches yesterday's OHLC for gap and level checks
- get_filled_quantity(): detects partial fills so we never assume full fill
"""

import logging
import time as time_module
from datetime import datetime, timedelta
from typing import Any, Callable, Optional

import pyotp  # Generates Time-based One-Time Passwords (like Google Authenticator)
from SmartApi import SmartConnect  # Angel One's official Python SDK

logger = logging.getLogger(__name__)


class BrokerConnection:
    """
    Wrapper around Angel One SmartAPI.

    Think of this as the "bank teller window" — every trade,
    price check, and position query goes through here.
    """

    def __init__(self, broker_config, trading_config=None):
        self.config = broker_config
        # trading_config provides api_max_retries and api_retry_delay
        self.trading_config = trading_config
        self.session: Optional[SmartConnect] = None
        self.auth_token: Optional[str] = None   # JWT for REST API calls
        self.feed_token: Optional[str] = None   # Separate token for WebSocket
        self.refresh_token_str: Optional[str] = None  # For token refresh
        self.is_connected = False

    # ──────────────────────────────────────────────────────────
    # Authentication
    # ──────────────────────────────────────────────────────────

    def connect(self) -> bool:
        """
        Authenticate with Angel One.

        Steps:
        1. Create SmartConnect session with API key
        2. Generate TOTP (rotates every 30 seconds)
        3. Call generateSession with credentials + TOTP
        4. Store auth_token and feed_token for later use

        Returns True on success, False on failure.
        """
        try:
            # Validate credentials are loaded
            if not self.config.api_key:
                logger.error("ANGEL_API_KEY is missing from .env file")
                return False
            if not self.config.client_id:
                logger.error("ANGEL_CLIENT_ID is missing from .env file")
                return False
            if not self.config.totp_secret:
                logger.error("ANGEL_TOTP_SECRET is missing from .env file")
                return False

            # Step 1: Create the SmartConnect session object
            self.session = SmartConnect(api_key=self.config.api_key)

            # Step 2: Generate TOTP (6-digit rotating code, like Google Authenticator)
            totp = pyotp.TOTP(self.config.totp_secret).now()

            # Step 3: Authenticate
            response = self.session.generateSession(
                clientCode=self.config.client_id,
                password=self.config.password,
                totp=totp,
            )

            # Step 4: Validate response
            if not response or response.get("status") is False:
                error_msg = response.get("message", "Unknown error") if response else "No response"
                logger.error(f"Authentication failed: {error_msg}")
                return False

            # Store tokens for later use
            data = response.get("data", {})
            self.auth_token = data.get("jwtToken", "")
            self.refresh_token_str = data.get("refreshToken", "")
            self.feed_token = self.session.getfeedToken()
            self.is_connected = True

            logger.info(f"Authenticated with Angel One (Client: {self.config.client_id})")
            return True

        except Exception as e:
            logger.error(f"Connection error: {e}", exc_info=True)
            return False

    def refresh_session(self) -> bool:
        """
        Refresh the auth token before it expires.
        Angel One tokens expire after ~24 hours.
        Called automatically by data_stream.py on reconnect.
        """
        try:
            if not self.session:
                return self.connect()

            # Try the token refresh endpoint first (no TOTP needed)
            if self.refresh_token_str:
                response = self.session.generateToken(self.refresh_token_str)
                if response and response.get("status"):
                    data = response.get("data", {})
                    self.auth_token = data.get("jwtToken", "")
                    self.refresh_token_str = data.get("refreshToken", self.refresh_token_str)
                    logger.info("Session token refreshed via refresh token")
                    return True

        except Exception as e:
            logger.warning(f"Token refresh failed, re-authenticating: {e}")

        # Fall back to full re-authentication with TOTP
        return self.connect()

    def disconnect(self):
        """Log out from Angel One and clean up."""
        try:
            if self.session and self.is_connected:
                self.session.terminateSession(self.config.client_id)
                logger.info("Logged out from Angel One")
        except Exception as e:
            logger.warning(f"Error during logout: {e}")
        finally:
            self.is_connected = False
            self.session = None

    def retry_connect(self, max_attempts: int = 3) -> bool:
        """Try to connect multiple times with 5-second delay between attempts."""
        for attempt in range(1, max_attempts + 1):
            logger.info(f"Connection attempt {attempt}/{max_attempts}...")
            if self.connect():
                return True
            if attempt < max_attempts:
                time_module.sleep(5)
        return False

    # ──────────────────────────────────────────────────────────
    # Retry Wrapper — used by all API methods below
    # ──────────────────────────────────────────────────────────

    def _api_with_retry(self, func: Callable, *args, **kwargs) -> Any:
        """
        Call an API function with exponential backoff on failure.

        How it works:
        - Attempt 1: call immediately
        - Attempt 2: wait 1 second, retry
        - Attempt 3: wait 2 seconds, retry
        (delay doubles each attempt — called "exponential backoff")

        Why: Broker APIs can return transient errors (network blip, server busy).
        Retrying 3x catches most of these without user intervention.

        Returns the API response, or None if all attempts fail.
        """
        max_retries = 3
        base_delay = 1.0
        if self.trading_config:
            max_retries = self.trading_config.api_max_retries
            base_delay = self.trading_config.api_retry_delay

        last_error = None
        for attempt in range(1, max_retries + 1):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                last_error = e
                if attempt < max_retries:
                    delay = base_delay * (2 ** (attempt - 1))  # 1s, 2s, 4s...
                    logger.warning(
                        f"API call failed (attempt {attempt}/{max_retries}): {e}. "
                        f"Retrying in {delay:.0f}s..."
                    )
                    time_module.sleep(delay)
                else:
                    logger.error(
                        f"API call failed after {max_retries} attempts: {last_error}"
                    )
        return None

    # ──────────────────────────────────────────────────────────
    # Order Management
    # ──────────────────────────────────────────────────────────

    def place_order(
        self,
        stock: str,
        token: str,
        direction: str,       # "LONG" or "SHORT"
        quantity: int,
        price: float,
        order_type: str = "LIMIT",
    ) -> Optional[str]:
        """
        Place an order with Angel One.

        Angel One transaction types:
        - "BUY" for going long
        - "SELL" for going short (intraday sell)

        Returns the order_id (string) on success, None on failure.
        """
        if not self._check_connected():
            return None

        transaction_type = "BUY" if direction == "LONG" else "SELL"

        order_params = {
            "variety": "NORMAL",
            "tradingsymbol": stock,
            "symboltoken": token,
            "transactiontype": transaction_type,
            "exchange": "NSE",
            "ordertype": "LIMIT" if order_type == "LIMIT" else "MARKET",
            "producttype": "INTRADAY",
            "duration": "DAY",
            "price": str(round(price, 2)),
            "squareoff": "0",
            "stoploss": "0",
            "quantity": str(quantity),
        }

        response = self._api_with_retry(self.session.placeOrder, order_params)

        if response and response.get("status"):
            order_id = response.get("data", {}).get("orderid", "")
            logger.info(
                f"Order placed: {transaction_type} {quantity}x {stock} "
                f"@ Rs.{price:.2f} | Order ID: {order_id}"
            )
            return order_id
        else:
            error = response.get("message", "Unknown") if response else "No response after retries"
            logger.error(f"Order placement failed: {error}")
            return None

    def cancel_order(self, order_id: str, variety: str = "NORMAL") -> bool:
        """Cancel a pending order."""
        if not self._check_connected():
            return False

        response = self._api_with_retry(self.session.cancelOrder, order_id, variety)
        if response and response.get("status"):
            logger.info(f"Order cancelled: {order_id}")
            return True
        else:
            error = response.get("message", "Unknown") if response else "No response"
            logger.error(f"Cancel failed ({order_id}): {error}")
            return False

    def place_exit_order(self, stock: str, token: str, direction: str, quantity: int) -> Optional[str]:
        """
        Place a MARKET order to exit a position.
        Used for force-exit at 3:15 PM or when kill switch is hit.

        If we're LONG, we SELL to exit.
        If we're SHORT, we BUY to exit.
        """
        exit_direction = "SELL" if direction == "LONG" else "BUY"

        if not self._check_connected():
            return None

        order_params = {
            "variety": "NORMAL",
            "tradingsymbol": stock,
            "symboltoken": token,
            "transactiontype": exit_direction,
            "exchange": "NSE",
            "ordertype": "MARKET",   # Market order for guaranteed exit
            "producttype": "INTRADAY",
            "duration": "DAY",
            "price": "0",
            "squareoff": "0",
            "stoploss": "0",
            "quantity": str(quantity),
        }

        response = self._api_with_retry(self.session.placeOrder, order_params)
        if response and response.get("status"):
            order_id = response.get("data", {}).get("orderid", "")
            logger.info(f"Exit order placed: {exit_direction} {quantity}x {stock} | Order: {order_id}")
            return order_id

        logger.error(f"Exit order failed for {stock} after retries")
        return None

    # ──────────────────────────────────────────────────────────
    # Price & Position Queries
    # ──────────────────────────────────────────────────────────

    def get_ltp(self, token: str, exchange: str = "NSE", trading_symbol: str = "") -> float:
        """
        Get Last Traded Price for a stock.
        Returns 0.0 on failure.
        """
        if not self._check_connected():
            return 0.0

        response = self._api_with_retry(self.session.ltpData, exchange, trading_symbol, token)
        if response and response.get("status"):
            ltp = float(response.get("data", {}).get("ltp", 0))
            return ltp
        return 0.0

    def get_positions(self) -> list:
        """
        Get all open intraday positions from Angel One.
        Returns a list of position dicts.
        """
        if not self._check_connected():
            return []

        response = self._api_with_retry(self.session.position)
        if response and response.get("status"):
            positions = response.get("data") or []
            return [p for p in positions if int(p.get("netqty", 0)) != 0]
        return []

    def get_order_status(self, order_id: str) -> str:
        """
        Check order status.
        Returns one of: "complete", "rejected", "cancelled", "open", "pending"
        """
        if not self._check_connected():
            return "unknown"

        response = self._api_with_retry(self.session.orderBook)
        if response and response.get("status"):
            orders = response.get("data") or []
            for order in orders:
                if order.get("orderid") == order_id:
                    return order.get("status", "unknown").lower()
        return "unknown"

    def get_filled_quantity(self, order_id: str) -> int:
        """
        Get the actual filled quantity for an order.

        Why this matters: When you place an order for 10 shares, the broker
        might only fill 7 (partial fill) if liquidity is low. If we assume
        full fill and calculate P&L on 10 shares, we'll be wrong.

        Returns 0 if the order is not found or has no fills.
        """
        if not self._check_connected():
            return 0

        response = self._api_with_retry(self.session.orderBook)
        if response and response.get("status"):
            orders = response.get("data") or []
            for order in orders:
                if order.get("orderid") == order_id:
                    # "filledshares" is Angel One's field for filled quantity
                    filled = int(order.get("filledshares", 0))
                    total = int(order.get("quantity", 0))
                    status = order.get("status", "").lower()

                    if filled < total and status not in ("complete", "cancelled", "rejected"):
                        logger.warning(
                            f"Partial fill detected: order {order_id} filled {filled}/{total} shares"
                        )
                    return filled
        return 0

    def get_prev_day_ohlc(self, token: str, trading_symbol: str) -> dict:
        """
        Fetch yesterday's Open, High, Low, Close for a stock.

        Used by scanner.py to:
        1. Gap filter: skip ORB if today's open is >1.5% from prev_close
        2. Level proximity: skip entry if price is within 0.3% of prev H/L/C

        How it works:
        - Call getCandleData with interval=ONE_DAY for the last 2 trading days
        - The second-to-last candle is yesterday's OHLC
        - (We fetch 2 days so "yesterday" is always candles[-2], not candles[-1]
           which would be today's incomplete candle)

        Returns dict with keys: prev_open, prev_high, prev_low, prev_close
        Returns empty dict on failure (caller must handle gracefully).
        """
        if not self._check_connected():
            return {}

        # Fetch last 5 days to be safe (weekends, holidays can skip days)
        to_date = datetime.now()
        from_date = to_date - timedelta(days=7)

        params = {
            "exchange": "NSE",
            "symboltoken": token,
            "interval": "ONE_DAY",
            "fromdate": from_date.strftime("%Y-%m-%d %H:%M"),
            "todate": to_date.strftime("%Y-%m-%d %H:%M"),
        }

        try:
            response = self._api_with_retry(self.session.getCandleData, params)
            if not response or not response.get("status"):
                logger.warning(f"Could not fetch prev day OHLC for {trading_symbol}")
                return {}

            candles = response.get("data") or []
            # Each candle = [timestamp, open, high, low, close, volume]
            # We need at least 2 candles: yesterday (index -2) and today (index -1)
            if len(candles) < 2:
                logger.warning(f"Not enough candle history for {trading_symbol}")
                return {}

            # Second-to-last candle is the last COMPLETE trading day
            prev = candles[-2]
            return {
                "prev_open":  float(prev[1]),
                "prev_high":  float(prev[2]),
                "prev_low":   float(prev[3]),
                "prev_close": float(prev[4]),
            }

        except Exception as e:
            logger.error(f"Error fetching prev day OHLC for {trading_symbol}: {e}")
            return {}

    def get_profile(self) -> dict:
        """Get user profile — useful to verify connection."""
        try:
            response = self.session.getProfile(self.refresh_token_str or "")
            if response and response.get("status"):
                return response.get("data", {})
        except Exception as e:
            logger.debug(f"Profile fetch error: {e}")
        return {}

    # ──────────────────────────────────────────────────────────
    # Helpers
    # ──────────────────────────────────────────────────────────

    def _check_connected(self) -> bool:
        """Check if connected before making API calls."""
        if not self.is_connected or not self.session:
            logger.error("Not connected to broker. Call connect() first.")
            return False
        return True
