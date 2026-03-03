"""
News Sentiment — Marketaux API Integration
==========================================
Fetches financial news at 9:00 AM before market opens.
Calculates sentiment scores per stock.

Marketaux free tier: 100 API requests per day
API docs: https://api.marketaux.com/v1/news/all

How it works:
1. Fetch general market news (India/NSE focused)
2. Fetch targeted news for top N stocks
3. Score each article: positive/negative/neutral
4. If a stock has earnings/results news → mark as "skip" (too volatile)
5. Aggregate scores per stock — passed to scanner → signal scorer

Key behaviors:
- If NEWS_API_KEY is missing → all stocks get "neutral" sentiment
- If API call fails → log warning, continue with neutral sentiment
- If stock has "earnings" in news → set skip_today=True in result
- On major events (RBI policy, budget) → set reduce_size=True globally

Usage:
    fetcher = NewsSentimentFetcher(config.news)
    sentiment = fetcher.fetch_all(watchlist_symbols)
    # sentiment = {"RELIANCE": {"sentiment": "positive", "score": 0.7, "skip_today": False}}
"""

import logging
import os
from datetime import datetime, timedelta
from typing import Optional

import requests

logger = logging.getLogger(__name__)

# Keywords that suggest earnings/event day → skip stock
SKIP_KEYWORDS = (
    "results", "earnings", "quarterly", "q1", "q2", "q3", "q4",
    "dividend", "merger", "acquisition", "delisted", "fpo", "ipo",
    "board meeting", "rights issue", "buyback",
)

# Global event keywords — if found, reduce all position sizes
GLOBAL_RISK_KEYWORDS = (
    "rbi policy", "rbi rate", "repo rate", "budget", "union budget",
    "fed rate", "federal reserve", "geopolitical", "war", "sanctions",
)

# Positive sentiment keywords
POSITIVE_WORDS = (
    "profit", "growth", "beat", "surge", "record", "strong", "rally",
    "upgrade", "outperform", "expansion", "deal", "contract", "win",
    "positive", "bullish", "up", "rise", "gain", "high", "exceeded",
)

# Negative sentiment keywords
NEGATIVE_WORDS = (
    "loss", "decline", "miss", "fall", "drop", "weak", "downgrade",
    "underperform", "cut", "reduce", "shutdown", "default", "fraud",
    "negative", "bearish", "down", "slump", "low", "below",
)


class NewsSentimentFetcher:
    """
    Fetches and parses news sentiment for watchlist stocks.

    Design choices:
    - We batch stocks to minimize API calls (Marketaux allows comma-separated symbols)
    - We cache the result for the day (only fetch once at 9 AM)
    - All failures are caught — missing news never crashes the bot
    """

    def __init__(self, news_config):
        self.config = news_config
        self._cache: dict[str, dict] = {}   # symbol → sentiment result
        self._fetched_today = False
        self._global_risk = False           # True on RBI/budget days

    def fetch_all(self, symbols: list[str]) -> dict[str, dict]:
        """
        Fetch sentiment for all watchlist stocks.
        Returns dict: {symbol: {sentiment, score, skip_today, headlines}}

        Called once at 9:00 AM. Results cached for the day.
        """
        if self._fetched_today:
            return self._cache

        if not self.config.enabled or not self.config.api_key:
            logger.warning(
                "NEWS_API_KEY not set in .env — news sentiment disabled. "
                "All stocks will use neutral sentiment (score +0 instead of +10). "
                "Bot will continue normally. Get a free key at https://www.marketaux.com/"
            )
            self._cache = {s: _neutral_sentiment() for s in symbols}
            self._fetched_today = True
            return self._cache

        logger.info(f"Fetching news sentiment for {len(symbols)} stocks...")

        # Initialize all stocks with neutral sentiment
        result: dict[str, dict] = {s: _neutral_sentiment() for s in symbols}

        try:
            # Step 1: Fetch general India market news (1 API call)
            market_news = self._fetch_market_news()
            self._global_risk = self._check_global_risk(market_news)
            if self._global_risk:
                logger.warning(
                    "GLOBAL RISK EVENT detected in news — position sizes will be reduced by 50%"
                )

            # Step 2: Fetch targeted news for top N stocks (batch API calls)
            # We limit to max_stocks_to_fetch to stay within 100 req/day
            priority_symbols = symbols[:self.config.max_stocks_to_fetch]

            for symbol in priority_symbols:
                try:
                    articles = self._fetch_stock_news(symbol)
                    if articles:
                        result[symbol] = self._analyze_articles(articles)
                except Exception as e:
                    logger.debug(f"News fetch failed for {symbol}: {e}")
                    # Keep neutral sentiment for this stock

        except Exception as e:
            logger.warning(f"News sentiment fetch failed: {e}. Continuing with neutral sentiment.")

        self._cache = result
        self._fetched_today = True

        # Log summary
        positive = sum(1 for v in result.values() if v["sentiment"] == "positive")
        negative = sum(1 for v in result.values() if v["sentiment"] == "negative")
        skipped = sum(1 for v in result.values() if v["skip_today"])
        logger.info(
            f"News sentiment: {positive} positive, {negative} negative, "
            f"{skipped} stocks to skip today"
        )

        return result

    def get_sentiment(self, symbol: str) -> dict:
        """Get cached sentiment for a specific stock."""
        return self._cache.get(symbol, _neutral_sentiment())

    def is_global_risk_day(self) -> bool:
        """True on RBI policy days, budget days, major global events."""
        return self._global_risk

    def should_skip_stock(self, symbol: str) -> bool:
        """True if stock has earnings/event news → skip trading it today."""
        return self._cache.get(symbol, {}).get("skip_today", False)

    # ──────────────────────────────────────────────────────────
    # Private helpers
    # ──────────────────────────────────────────────────────────

    def _fetch_market_news(self) -> list[dict]:
        """Fetch general India market news (1 API call)."""
        url = "https://api.marketaux.com/v1/news/all"
        params = {
            "api_token": self.config.api_key,
            "countries": "in",
            "language": "en",
            "published_after": (datetime.now() - timedelta(hours=18)).strftime(
                "%Y-%m-%dT%H:%M"
            ),
            "limit": 10,
        }
        try:
            resp = requests.get(url, params=params, timeout=10)
            resp.raise_for_status()
            return resp.json().get("data", [])
        except Exception as e:
            logger.debug(f"Market news fetch failed: {e}")
            return []

    def _fetch_stock_news(self, symbol: str) -> list[dict]:
        """Fetch news for a specific NSE stock symbol (1 API call per stock)."""
        url = "https://api.marketaux.com/v1/news/all"
        # Marketaux uses NSE symbol format like "RELIANCE.NSE"
        params = {
            "api_token": self.config.api_key,
            "symbols": f"{symbol}.NSE",
            "language": "en",
            "published_after": (datetime.now() - timedelta(hours=18)).strftime(
                "%Y-%m-%dT%H:%M"
            ),
            "limit": 5,
        }
        try:
            resp = requests.get(url, params=params, timeout=10)
            resp.raise_for_status()
            return resp.json().get("data", [])
        except Exception:
            return []

    def _analyze_articles(self, articles: list[dict]) -> dict:
        """
        Score a list of news articles for a stock.

        Each article has: title, description, sentiment (from Marketaux API).
        We also do our own keyword-based scoring as a cross-check.

        Returns:
            {"sentiment": "positive"/"negative"/"neutral",
             "score": 0.0-1.0,
             "skip_today": bool,
             "headlines": [str]}
        """
        if not articles:
            return _neutral_sentiment()

        positive_count = 0
        negative_count = 0
        skip_today = False
        headlines = []

        for article in articles[:5]:  # Max 5 articles per stock
            title = (article.get("title") or "").lower()
            description = (article.get("description") or "").lower()
            text = f"{title} {description}"

            headlines.append(article.get("title", "")[:100])

            # Check if it's an earnings/event day
            if any(kw in text for kw in SKIP_KEYWORDS):
                skip_today = True
                logger.info(f"Earnings/event detected in news — marking stock to skip")

            # Use Marketaux's own sentiment if available
            api_sentiment = article.get("sentiment", None)
            if api_sentiment == "positive":
                positive_count += 1
            elif api_sentiment == "negative":
                negative_count += 1
            else:
                # Fall back to keyword matching
                pos_hits = sum(1 for w in POSITIVE_WORDS if w in text)
                neg_hits = sum(1 for w in NEGATIVE_WORDS if w in text)
                if pos_hits > neg_hits:
                    positive_count += 1
                elif neg_hits > pos_hits:
                    negative_count += 1

        # Aggregate sentiment
        total = len(articles)
        if positive_count > total * 0.5:
            sentiment = "positive"
            score = positive_count / total
        elif negative_count > total * 0.5:
            sentiment = "negative"
            score = negative_count / total
        else:
            sentiment = "neutral"
            score = 0.5

        return {
            "sentiment": sentiment,
            "score": round(score, 2),
            "skip_today": skip_today,
            "headlines": headlines[:3],
        }

    def _check_global_risk(self, articles: list[dict]) -> bool:
        """Check if general market news contains a major risk event."""
        for article in articles:
            text = (
                (article.get("title") or "") + " " + (article.get("description") or "")
            ).lower()
            if any(kw in text for kw in GLOBAL_RISK_KEYWORDS):
                return True
        return False


def _neutral_sentiment() -> dict:
    """Default neutral sentiment when no news data is available."""
    return {
        "sentiment": "neutral",
        "score": 0.5,
        "skip_today": False,
        "headlines": [],
    }
