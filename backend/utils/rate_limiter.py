"""
Proper token bucket rate limiter for Angel One SmartAPI.

Official Angel One rate limits (from their forum):
- getCandleData (Historical): 3/sec, 180/min, 5000/hr
- getMarketData (Quote/LTP):  10/sec, 500/min, 5000/hr
- getLtpData:                  10/sec, 500/min, 5000/hr
- placeOrder:                  20/sec, 500/min, 1000/hr

We use CONSERVATIVE values (50-60% of official) because Angel One's
rate limiter is known to be stricter than documented. Multiple developers
on the SmartAPI forum report AB1004 errors even within stated limits.
"""

import time
import threading
import logging

logger = logging.getLogger(__name__)


class RateLimiter:
    """Thread-safe token bucket rate limiter with per-second and per-minute caps."""

    def __init__(self, name: str, requests_per_second: float, requests_per_minute: int):
        self.name = name
        self.min_interval = 1.0 / requests_per_second
        self.max_per_minute = requests_per_minute
        self.lock = threading.Lock()
        self.last_request_time = 0.0
        self.minute_timestamps: list[float] = []

    def wait(self):
        """Block until it's safe to make the next request. Call before every API request."""
        with self.lock:
            now = time.time()

            # Clean timestamps older than 60 seconds
            self.minute_timestamps = [t for t in self.minute_timestamps if now - t < 60]

            # Check per-minute limit
            if len(self.minute_timestamps) >= self.max_per_minute:
                wait_until = self.minute_timestamps[0] + 60.5  # 0.5s buffer
                sleep_time = wait_until - now
                if sleep_time > 0:
                    logger.info(f"[{self.name}] Per-minute limit reached. Waiting {sleep_time:.1f}s...")
                    time.sleep(sleep_time)
                    now = time.time()
                    self.minute_timestamps = [t for t in self.minute_timestamps if now - t < 60]

            # Check per-second limit
            elapsed = now - self.last_request_time
            if elapsed < self.min_interval:
                time.sleep(self.min_interval - elapsed)

            # Record this request
            now = time.time()
            self.last_request_time = now
            self.minute_timestamps.append(now)

    def get_stats(self) -> dict:
        """Return current usage stats."""
        with self.lock:
            now = time.time()
            recent = len([t for t in self.minute_timestamps if now - t < 60])
            return {
                "name": self.name,
                "requests_last_minute": recent,
                "max_per_minute": self.max_per_minute,
                "utilization_pct": round(recent / self.max_per_minute * 100, 1),
            }


# Pre-configured limiters for Angel One endpoints
# Using 50-60% of official limits for safety margin

HISTORICAL_LIMITER = RateLimiter(
    name="Historical",
    requests_per_second=1.0,    # Official: 3/sec
    requests_per_minute=55,     # Official: 180/min
)

LTP_LIMITER = RateLimiter(
    name="LTP/MarketData",
    requests_per_second=5.0,    # Official: 10/sec
    requests_per_minute=200,    # Official: 500/min
)

ORDER_LIMITER = RateLimiter(
    name="Orders",
    requests_per_second=10.0,   # Official: 20/sec
    requests_per_minute=250,    # Official: 500/min
)
