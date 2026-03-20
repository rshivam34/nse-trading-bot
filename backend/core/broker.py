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

import requests  # For Yahoo Finance VIX fetch (already installed as dependency of smartapi)
import pyotp  # Generates Time-based One-Time Passwords (like Google Authenticator)
from SmartApi import SmartConnect  # Angel One's official Python SDK
from utils.watchlist import lookup_token_for_symbol

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

        Token refresh:
        - Re-looks up the symbol token from the instrument master before placing.
        - The cached token from startup may be stale (AB1019 mismatch error).
        - If lookup fails, falls back to the token passed in.

        Returns the order_id (string) on success, None on failure.
        """
        if not self._check_connected():
            return None

        # Re-lookup token from instrument master to avoid AB1019 stale token errors
        fresh_token = lookup_token_for_symbol(stock)
        if fresh_token:
            if fresh_token != token:
                logger.warning(
                    f"Token mismatch for {stock}: cached={token}, "
                    f"fresh={fresh_token}. Using fresh token."
                )
            token = fresh_token
        else:
            logger.warning(
                f"Could not refresh token for {stock}. "
                f"Using cached token: {token}"
            )

        transaction_type = "BUY" if direction == "LONG" else "SELL"

        # Angel One requires '-EQ' suffix for NSE equity stocks
        trading_symbol = stock if stock.endswith("-EQ") else f"{stock}-EQ"

        order_params = {
            "variety": "NORMAL",
            "tradingsymbol": trading_symbol,
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

        # SmartAPI may return a string (order ID) or a dict — handle both
        if isinstance(response, str) and response:
            logger.info(
                f"Order placed: {transaction_type} {quantity}x {trading_symbol} "
                f"@ Rs.{price:.2f} | Order ID: {response}"
            )
            return response
        elif isinstance(response, dict) and response.get("status"):
            order_id = response.get("data", {}).get("orderid", "")
            logger.info(
                f"Order placed: {transaction_type} {quantity}x {trading_symbol} "
                f"@ Rs.{price:.2f} | Order ID: {order_id}"
            )
            return order_id
        else:
            error = response.get("message", "Unknown") if isinstance(response, dict) else str(response or "No response")
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

    # ──────────────────────────────────────────────────────────
    # Broker-side Stop-Loss Orders (exchange-level protection)
    # ──────────────────────────────────────────────────────────

    def place_sl_order(
        self,
        stock: str,
        token: str,
        direction: str,       # Direction of the POSITION (LONG/SHORT)
        quantity: int,
        trigger_price: float,
        price_buffer: float = 0.50,
    ) -> Optional[str]:
        """
        Place a STOPLOSS-LIMIT order with Angel One.

        This is a safety net — even if the bot crashes, the exchange has
        a real SL order that triggers automatically.

        For a LONG position: places a SELL SL order (sells if price drops to trigger)
        For a SHORT position: places a BUY SL order (buys if price rises to trigger)

        Args:
            stock: Stock symbol (e.g., "RELIANCE")
            token: Instrument token
            direction: Direction of the open position (LONG or SHORT)
            quantity: Number of shares to exit
            trigger_price: The price at which the SL order activates
            price_buffer: Rs. buffer between trigger and limit price

        Returns:
            Order ID string on success, None on failure.
        """
        if not self._check_connected():
            return None

        # SL order exits the position: LONG → SELL, SHORT → BUY
        exit_type = "SELL" if direction == "LONG" else "BUY"

        # Limit price: slightly worse than trigger to ensure fill
        # For SELL: limit below trigger. For BUY: limit above trigger.
        if exit_type == "SELL":
            limit_price = round(trigger_price - price_buffer, 2)
        else:
            limit_price = round(trigger_price + price_buffer, 2)

        # Re-lookup token from instrument master
        fresh_token = lookup_token_for_symbol(stock)
        if fresh_token:
            token = fresh_token

        trading_symbol = stock if stock.endswith("-EQ") else f"{stock}-EQ"

        order_params = {
            "variety": "STOPLOSS",
            "tradingsymbol": trading_symbol,
            "symboltoken": token,
            "transactiontype": exit_type,
            "exchange": "NSE",
            "ordertype": "STOPLOSS_LIMIT",
            "producttype": "INTRADAY",
            "duration": "DAY",
            "price": str(limit_price),
            "triggerprice": str(round(trigger_price, 2)),
            "squareoff": "0",
            "stoploss": "0",
            "quantity": str(quantity),
        }

        response = self._api_with_retry(self.session.placeOrder, order_params)

        if isinstance(response, str) and response:
            logger.info(
                f"SL order placed: {exit_type} {quantity}x {trading_symbol} "
                f"trigger @ Rs.{trigger_price:.2f} | Order: {response}"
            )
            return response
        elif isinstance(response, dict) and response.get("status"):
            order_id = response.get("data", {}).get("orderid", "")
            logger.info(
                f"SL order placed: {exit_type} {quantity}x {trading_symbol} "
                f"trigger @ Rs.{trigger_price:.2f} | Order: {order_id}"
            )
            return order_id
        else:
            error = response.get("message", "Unknown") if isinstance(response, dict) else str(response or "No response")
            logger.error(f"SL order placement failed for {stock}: {error}")
            return None

    def modify_sl_order(
        self,
        order_id: str,
        stock: str,
        token: str,
        direction: str,
        quantity: int,
        new_trigger_price: float,
        price_buffer: float = 0.50,
    ) -> bool:
        """
        Modify an existing SL order's trigger and limit price.

        Called when trailing the stop-loss — updates the exchange-level SL
        to match the bot's new trailing SL price.

        Returns True on success, False on failure.
        """
        if not self._check_connected():
            return False

        exit_type = "SELL" if direction == "LONG" else "BUY"
        if exit_type == "SELL":
            new_limit = round(new_trigger_price - price_buffer, 2)
        else:
            new_limit = round(new_trigger_price + price_buffer, 2)

        fresh_token = lookup_token_for_symbol(stock)
        if fresh_token:
            token = fresh_token

        trading_symbol = stock if stock.endswith("-EQ") else f"{stock}-EQ"

        modify_params = {
            "variety": "STOPLOSS",
            "orderid": order_id,
            "ordertype": "STOPLOSS_LIMIT",
            "producttype": "INTRADAY",
            "duration": "DAY",
            "price": str(new_limit),
            "triggerprice": str(round(new_trigger_price, 2)),
            "quantity": str(quantity),
            "tradingsymbol": trading_symbol,
            "symboltoken": token,
            "exchange": "NSE",
        }

        response = self._api_with_retry(self.session.modifyOrder, modify_params)

        if response and (isinstance(response, str) or response.get("status")):
            logger.info(
                f"SL order modified: {stock} new trigger @ Rs.{new_trigger_price:.2f} "
                f"| Order: {order_id}"
            )
            return True
        else:
            error = response.get("message", "Unknown") if isinstance(response, dict) else str(response or "No response")
            logger.error(f"SL order modify failed for {stock}: {error}")
            return False

    def cancel_sl_order(self, order_id: str) -> bool:
        """Cancel a broker-side SL order (before placing a manual exit)."""
        return self.cancel_order(order_id, variety="STOPLOSS")

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

        # Re-lookup token from instrument master to avoid AB1019 stale token errors
        fresh_token = lookup_token_for_symbol(stock)
        if fresh_token:
            token = fresh_token
        else:
            logger.warning(
                f"Could not refresh token for exit order {stock}. "
                f"Using cached token: {token}"
            )

        # Angel One requires '-EQ' suffix for NSE equity stocks
        trading_symbol = stock if stock.endswith("-EQ") else f"{stock}-EQ"

        order_params = {
            "variety": "NORMAL",
            "tradingsymbol": trading_symbol,
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

        # SmartAPI may return a string (order ID) or a dict — handle both
        if isinstance(response, str) and response:
            logger.info(f"Exit order placed: {exit_direction} {quantity}x {trading_symbol} | Order: {response}")
            return response
        elif isinstance(response, dict) and response.get("status"):
            order_id = response.get("data", {}).get("orderid", "")
            logger.info(f"Exit order placed: {exit_direction} {quantity}x {trading_symbol} | Order: {order_id}")
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

    def get_vix(self) -> float:
        """
        Fetch India VIX value.

        Uses Yahoo Finance free API (no API key needed) because Angel One's
        SmartAPI does not support India VIX via ltpData endpoint (AB4006 error).

        Yahoo Finance URL returns JSON with regularMarketPrice for ^INDIAVIX.
        This is polled every 5 minutes from main.py — not per-tick.

        Returns VIX value (e.g., 14.5), or 0.0 on failure.
        """
        try:
            response = requests.get(
                "https://query1.finance.yahoo.com/v8/finance/chart/%5EINDIAVIX",
                params={"interval": "1d", "range": "1d"},
                headers={"User-Agent": "Mozilla/5.0"},
                timeout=10,
            )
            if response.status_code == 200:
                data = response.json()
                result = data.get("chart", {}).get("result", [])
                if result:
                    vix = float(result[0].get("meta", {}).get("regularMarketPrice", 0))
                    if vix > 0:
                        return vix
        except Exception as e:
            logger.debug(f"Yahoo Finance VIX fetch failed: {e}")

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

    def get_order_fill_details(self, order_id: str) -> tuple[int, float]:
        """
        Get filled quantity AND average fill price for an order in one API call.

        Why both at once: Avoids two separate orderBook calls. The broker knows
        the exact average price you paid (averageprice field), which may differ
        from the LIMIT price you requested.

        Returns:
            (filled_qty, avg_fill_price). Returns (0, 0.0) if not found.
        """
        if not self._check_connected():
            return 0, 0.0

        response = self._api_with_retry(self.session.orderBook)
        if response and response.get("status"):
            orders = response.get("data") or []
            for order in orders:
                if order.get("orderid") == order_id:
                    filled = int(order.get("filledshares", 0) or 0)
                    avg_price = float(order.get("averageprice", 0) or 0)
                    total = int(order.get("quantity", 0) or 0)
                    status = order.get("status", "").lower()

                    if filled > 0 and filled < total and status not in ("complete", "cancelled", "rejected"):
                        logger.warning(
                            f"Partial fill: order {order_id} filled {filled}/{total} shares "
                            f"@ avg Rs.{avg_price:.2f}"
                        )
                    return filled, avg_price
        return 0, 0.0

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

        Rate limit handling:
        - Angel One returns AB1004 (TooManyRequests) when API is hammered
        - On rate limit, retries up to 3 times with exponential backoff (5s, 10s, 15s)
        - This is separate from _api_with_retry() which handles transient errors

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

        # Exponential backoff delays for rate limit retries (5s, 10s, 15s)
        rate_limit_max_retries = 3
        rate_limit_delays = [5, 10, 15]

        for rate_attempt in range(rate_limit_max_retries + 1):
            try:
                response = self._api_with_retry(self.session.getCandleData, params)

                # Check for rate limit error in the response
                if response and self._is_rate_limit_error(response):
                    if rate_attempt < rate_limit_max_retries:
                        delay = rate_limit_delays[rate_attempt]
                        logger.warning(
                            f"Rate limited (AB1004) fetching {trading_symbol}. "
                            f"Backing off {delay}s "
                            f"(retry {rate_attempt + 1}/{rate_limit_max_retries})..."
                        )
                        time_module.sleep(delay)
                        continue  # Retry the request
                    else:
                        logger.error(
                            f"Rate limit persists for {trading_symbol} "
                            f"after {rate_limit_max_retries} retries. Skipping."
                        )
                        return {}

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

        return {}

    # ──────────────────────────────────────────────────────────
    # Batch OHLC Fetch with Rate Limiting + Capital Filter
    # ──────────────────────────────────────────────────────────

    def fetch_prev_day_ohlc(self, stock: dict, from_date: str, to_date: str) -> dict | None:
        """Fetch previous day OHLC for a single stock with rate limiting and smart backoff.

        Uses the token bucket rate limiter instead of sleep(2).
        On AB1004 errors, backs off with escalating delays (5s, 15s).

        Returns:
            dict with prev_open/high/low/close, or None if failed after retries
        """
        from utils.rate_limiter import HISTORICAL_LIMITER

        symbol = stock.get("symbol", "UNKNOWN")
        token = stock.get("token", "")
        max_retries = 2
        backoff_delays = [5, 15]  # seconds — escalating

        for attempt in range(max_retries + 1):
            try:
                HISTORICAL_LIMITER.wait()  # Token bucket rate limiter

                data = self.session.getCandleData({
                    "exchange": "NSE",
                    "symboltoken": str(token),
                    "interval": "ONE_DAY",
                    "fromdate": from_date,
                    "todate": to_date,
                })

                if data and data.get("status") and data.get("data"):
                    candles = data["data"]
                    if len(candles) >= 2:
                        prev = candles[-2]
                        # Extract daily volumes from all candles for ADV calculation
                        # Each candle: [timestamp, open, high, low, close, volume]
                        daily_volumes = []
                        for c in candles:
                            try:
                                if len(c) > 5:
                                    daily_volumes.append(int(c[5]))
                            except (ValueError, TypeError):
                                pass
                        return {
                            "prev_open": float(prev[1]),
                            "prev_high": float(prev[2]),
                            "prev_low": float(prev[3]),
                            "prev_close": float(prev[4]),
                            "daily_volumes": daily_volumes,
                        }
                    logger.debug(f"Not enough candle history for {symbol}")
                    return None

                # Check for rate limit error
                error_code = str(data.get("errorcode", "")) if data else ""
                error_msg = str(data.get("message", "")) if data else ""

                if error_code == "AB1004" or "TooManyRequests" in error_msg:
                    if attempt < max_retries:
                        delay = backoff_delays[attempt]
                        logger.warning(
                            f"Rate limited ({error_code}) fetching {symbol}. "
                            f"Backoff {delay}s (attempt {attempt + 1}/{max_retries + 1})"
                        )
                        time_module.sleep(delay)
                        continue
                    else:
                        logger.warning(
                            f"Giving up on {symbol} after {max_retries + 1} attempts (rate limited)"
                        )
                        return None

                # Non-rate-limit error — don't retry
                logger.debug(f"No data for {symbol}: {error_msg}")
                return None

            except Exception as e:
                if attempt < max_retries:
                    delay = backoff_delays[attempt]
                    logger.warning(f"Error fetching {symbol}: {e}. Retrying in {delay}s...")
                    time_module.sleep(delay)
                else:
                    logger.error(
                        f"Failed to fetch OHLC for {symbol} after {max_retries + 1} attempts: {e}"
                    )
                    return None

        return None

    def fetch_all_prev_day_ohlc(
        self,
        watchlist: list[dict],
        capital: float,
        from_date: str,
        to_date: str,
    ) -> tuple[dict, list[dict], dict]:
        """Master function: cache -> capital filter -> batch fetch -> cache results.

        This is the main entry point for pre-market OHLC loading.

        Args:
            watchlist: Full watchlist (all 193 stocks)
            capital: Available trading capital
            from_date: Start date string for historical data
            to_date: End date string for historical data

        Returns:
            tuple: (ohlc_results dict, affordable_stocks list, ltp_cache dict)
        """
        from utils.rate_limiter import LTP_LIMITER
        from utils.ohlc_cache import load_cached_ohlc, save_ohlc_cache
        from utils.capital_filter import filter_stocks_by_capital

        # STEP 1: Check local cache first (instant on mid-day restart)
        cached = load_cached_ohlc()
        if cached:
            logger.info(
                f"Using cached OHLC data ({len(cached)} stocks). Zero API calls needed!"
            )
            # Still need to filter by capital for the trading phase
            affordable, skipped, ltp_cache = filter_stocks_by_capital(
                self.session, watchlist, capital, LTP_LIMITER
            )
            return cached, affordable, ltp_cache

        # STEP 2: Capital-aware filter (uses fast LTP API: 5 req/sec)
        affordable, skipped, ltp_cache = filter_stocks_by_capital(
            self.session, watchlist, capital, LTP_LIMITER
        )

        if not affordable:
            logger.warning("No affordable stocks found! Consider increasing capital.")
            return {}, [], ltp_cache

        # STEP 3: Fetch OHLC only for affordable stocks (uses slow Historical API: 1 req/sec)
        logger.info(
            f"Fetching previous day OHLC for {len(affordable)} affordable stocks "
            f"(filtered from {len(watchlist)} total)..."
        )

        ohlc_results: dict = {}
        ok_count = 0
        fail_count = 0
        batch_size = 5
        batch_gap = 2.0  # extra seconds between batches

        for i in range(0, len(affordable), batch_size):
            batch = affordable[i:i + batch_size]

            for stock_item in batch:
                symbol = stock_item.get("symbol", "UNKNOWN")
                data = self.fetch_prev_day_ohlc(stock_item, from_date, to_date)

                if data:
                    ohlc_results[symbol] = data
                    ok_count += 1
                else:
                    fail_count += 1

            # Progress log after each batch
            done = min(i + batch_size, len(affordable))
            logger.info(
                f"OHLC fetch progress: {done}/{len(affordable)} "
                f"({ok_count} OK, {fail_count} failed)"
            )

            # Extra pause between batches (not after last batch)
            if i + batch_size < len(affordable):
                time_module.sleep(batch_gap)

        # STEP 3b: Retry failed stocks after a cool-down pause
        # Rate-limit errors (AB1019/AB1004) are transient — a second pass
        # after a longer pause recovers most of them.
        failed_stocks = [
            s for s in affordable
            if s.get("symbol", "UNKNOWN") not in ohlc_results
        ]
        if failed_stocks:
            logger.info(
                f"OHLC retry pass: {len(failed_stocks)} stocks failed on first attempt. "
                f"Waiting 10s then retrying with slower rate..."
            )
            time_module.sleep(10)  # Cool-down before retry pass

            retry_ok = 0
            for i, stock_item in enumerate(failed_stocks):
                symbol = stock_item.get("symbol", "UNKNOWN")
                # Extra 1s gap between each retry call (on top of rate limiter)
                if i > 0:
                    time_module.sleep(1)
                data = self.fetch_prev_day_ohlc(stock_item, from_date, to_date)
                if data:
                    ohlc_results[symbol] = data
                    ok_count += 1
                    fail_count -= 1
                    retry_ok += 1

            logger.info(
                f"OHLC retry pass recovered {retry_ok}/{len(failed_stocks)} stocks"
            )

        # STEP 4: Cache results for mid-day restarts
        save_ohlc_cache(ohlc_results)

        logger.info(
            f"OHLC fetch complete: {ok_count} OK, {fail_count} failed "
            f"out of {len(affordable)} affordable stocks"
        )

        return ohlc_results, affordable, ltp_cache

    # ──────────────────────────────────────────────────────────
    # Intraday Candle Fetch (pre-seed for instant strategy readiness)
    # ──────────────────────────────────────────────────────────

    def fetch_intraday_candles(self, token: str, exchange: str = "NSE") -> list[dict]:
        """
        Fetch today's completed 5-minute intraday candles from Angel One.

        Used at startup to pre-seed the scanner's candle store so that
        all strategies and indicators (ATR, Choppiness, EMA) are ready
        immediately instead of waiting 60-110 minutes for enough ticks.

        How it works:
        - Calls getCandleData with interval=FIVE_MINUTE from 9:15 AM to now
        - Parses each candle: [timestamp, open, high, low, close, volume]
        - Skips the last candle if it's still incomplete (current 5-min window)

        Args:
            token: Instrument token (e.g., "3045" for SBIN)
            exchange: Exchange name ("NSE" for stocks and indices)

        Returns:
            List of candle dicts: [{Open, High, Low, Close, Volume}, ...]
            Empty list on failure (caller falls back to building from ticks).
        """
        from utils.rate_limiter import HISTORICAL_LIMITER

        if not self._check_connected():
            return []

        now = datetime.now()
        from_date = now.replace(hour=9, minute=15, second=0, microsecond=0)

        # Don't fetch if market hasn't opened yet
        if now < from_date:
            return []

        params = {
            "exchange": exchange,
            "symboltoken": str(token),
            "interval": "FIVE_MINUTE",
            "fromdate": from_date.strftime("%Y-%m-%d %H:%M"),
            "todate": now.strftime("%Y-%m-%d %H:%M"),
        }

        max_retries = 2
        backoff_delays = [5, 15]

        for attempt in range(max_retries + 1):
            try:
                HISTORICAL_LIMITER.wait()

                response = self._api_with_retry(self.session.getCandleData, params)

                # Check for rate limit error
                if response and self._is_rate_limit_error(response):
                    if attempt < max_retries:
                        delay = backoff_delays[attempt]
                        logger.warning(
                            f"Rate limited fetching intraday candles for token {token}. "
                            f"Backoff {delay}s (attempt {attempt + 1}/{max_retries + 1})"
                        )
                        time_module.sleep(delay)
                        continue
                    else:
                        return []

                if not response or not response.get("status"):
                    return []

                raw_candles = response.get("data") or []
                if not raw_candles:
                    return []

                # Parse candles: [timestamp, open, high, low, close, volume]
                # Skip the last candle if it hasn't closed yet (incomplete)
                candles = []
                for c in raw_candles:
                    try:
                        ts_str = c[0]
                        # Strip timezone for parsing (Python 3.10 compat)
                        if "+" in ts_str:
                            ts_clean = ts_str.rsplit("+", 1)[0]
                        elif ts_str.endswith("Z"):
                            ts_clean = ts_str[:-1]
                        else:
                            ts_clean = ts_str

                        candle_start = datetime.strptime(ts_clean, "%Y-%m-%dT%H:%M:%S")
                        candle_end = candle_start + timedelta(minutes=5)

                        # Skip incomplete candle (current window still open)
                        if candle_end > now:
                            continue

                        candles.append({
                            "Open": float(c[1]),
                            "High": float(c[2]),
                            "Low": float(c[3]),
                            "Close": float(c[4]),
                            "Volume": int(c[5]),
                        })
                    except (IndexError, ValueError, TypeError) as e:
                        logger.debug(f"Skipping malformed candle for token {token}: {e}")
                        continue

                return candles

            except Exception as e:
                if attempt < max_retries:
                    delay = backoff_delays[attempt]
                    logger.warning(
                        f"Error fetching intraday candles for token {token}: {e}. "
                        f"Retrying in {delay}s..."
                    )
                    time_module.sleep(delay)
                else:
                    logger.error(
                        f"Failed to fetch intraday candles for token {token}: {e}"
                    )
                    return []

        return []

    def fetch_all_intraday_candles(
        self,
        tokens: list[dict],
        index_tokens: list[dict] | None = None,
    ) -> dict[str, list[dict]]:
        """
        Fetch today's 5-min intraday candles for multiple stocks and indices.

        Used at startup to pre-seed the scanner so all strategies and
        indicators are immediately ready instead of waiting for WebSocket ticks.

        Args:
            tokens: List of {token, symbol} dicts for stocks
            index_tokens: List of {token, symbol, exchange} dicts for NIFTY/BANKNIFTY

        Returns:
            Dict mapping token string -> list of candle dicts
        """
        results: dict[str, list[dict]] = {}
        total = len(tokens) + (len(index_tokens) if index_tokens else 0)

        if total == 0:
            return results

        logger.info(f"Fetching intraday 5-min candles for {total} instruments...")

        ok_count = 0
        fail_count = 0
        batch_size = 5
        batch_gap = 2.0  # extra seconds between batches

        # Fetch stock candles (exchange = NSE)
        for i in range(0, len(tokens), batch_size):
            batch = tokens[i:i + batch_size]
            for item in batch:
                token = item.get("token", "")
                candles = self.fetch_intraday_candles(token, exchange="NSE")
                if candles:
                    results[token] = candles
                    ok_count += 1
                else:
                    fail_count += 1

            done = min(i + batch_size, len(tokens))
            logger.info(
                f"Intraday candle fetch: {done}/{total} "
                f"({ok_count} OK, {fail_count} failed)"
            )

            if i + batch_size < len(tokens):
                time_module.sleep(batch_gap)

        # Fetch index candles (NIFTY, BANKNIFTY)
        if index_tokens:
            for item in index_tokens:
                token = item.get("token", "")
                exchange = item.get("exchange", "NSE")
                candles = self.fetch_intraday_candles(token, exchange=exchange)
                if candles:
                    results[token] = candles
                    ok_count += 1
                else:
                    fail_count += 1

        logger.info(
            f"Intraday candle fetch complete: {ok_count} OK, {fail_count} failed "
            f"out of {total} instruments"
        )
        return results

    def get_funds(self) -> dict:
        """
        Get available cash and intraday margin from Angel One RMS system.

        Returns dict with keys like:
        - availablecash: plain cash balance (Rs.)
        - availableintradaypayin: cash × leverage (what we can actually trade)
        - utilisedpayout: margin already used for open positions

        Returns empty dict on failure — callers must handle gracefully.
        Used in two places:
        1. Pre-market check: verify enough capital to trade
        2. Per-order: verify margin before placing each order
        """
        if not self._check_connected():
            return {}

        response = self._api_with_retry(self.session.rmsLimit)
        if response and response.get("status"):
            return response.get("data", {}) or {}
        logger.warning("Could not fetch funds/margin from Angel One")
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

    def _is_rate_limit_error(self, response: Any) -> bool:
        """
        Check if an API response indicates a rate limit error.

        Angel One returns AB1004 when you send too many requests.
        This checks the response message for known rate-limit indicators.
        """
        if not isinstance(response, dict):
            return False
        message = str(response.get("message", "")).upper()
        error_code = str(response.get("errorcode", "")).upper()
        return (
            "AB1004" in message
            or "AB1004" in error_code
            or "TOO MANY" in message
            or "RATE LIMIT" in message
        )

    def _check_connected(self) -> bool:
        """Check if connected before making API calls."""
        if not self.is_connected or not self.session:
            logger.error("Not connected to broker. Call connect() first.")
            return False
        return True
