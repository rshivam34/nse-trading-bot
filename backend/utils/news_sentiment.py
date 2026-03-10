"""
News Sentiment — Marketaux API Integration
==========================================
Fetches financial news at 9:00 AM before market opens.
Calculates sentiment scores per stock.

Marketaux free tier: 100 API requests per day
API docs: https://api.marketaux.com/v1/news/all

How it works:
1. Fetch general market news (India/NSE focused) + global geopolitical news
2. Fetch targeted news for top N stocks
3. Score each article using Marketaux entity sentiment_score (numeric -1 to +1)
4. Fall back to keyword matching if entity sentiment unavailable
5. If a stock has earnings/results news → mark as "skip" (too volatile)
6. Aggregate scores per stock — passed to scanner → signal scorer

Key behaviors:
- If NEWS_API_KEY is missing → all stocks get "neutral" sentiment
- If API call fails → log warning, continue with neutral sentiment
- If stock has "earnings" in news → set skip_today=True in result
- On major events (RBI policy, budget, geopolitical) → set global_risk=True
- Cache resets automatically on new calendar day

Usage:
    fetcher = NewsSentimentFetcher(config.news)
    sentiment = fetcher.fetch_all(watchlist_symbols)
    # sentiment = {"RELIANCE": {"sentiment": "positive", "score": 0.7, "skip_today": False}}
"""

import logging
import re
from datetime import datetime, date, timedelta
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
# Covers: Indian policy, US Fed, geopolitical conflicts, oil shocks, trade wars
GLOBAL_RISK_KEYWORDS = (
    # Indian policy events
    "rbi policy", "rbi rate", "repo rate", "budget", "union budget",
    # US/global monetary policy
    "fed rate", "federal reserve", "interest rate hike", "rate cut",
    # Geopolitical conflicts (broad)
    "geopolitical", "war", "sanctions", "conflict", "tensions",
    "military", "missile", "strike", "airstrike", "escalation",
    "invasion", "ceasefire", "nuclear",
    # Specific hotspots (update as needed)
    "iran", "israel", "russia", "ukraine", "taiwan", "china",
    "north korea", "middle east", "red sea", "houthi",
    # Commodity shocks that hit Indian markets
    "crude oil surge", "oil price spike", "opec cut", "oil embargo",
    "brent crude", "commodity shock",
    # Trade/economic shocks
    "trade war", "tariff", "default", "debt crisis", "recession",
    "banking crisis", "currency crisis",
)

# Positive sentiment keywords — use word-boundary regex to avoid false matches
# (e.g., "up" must not match "update", "high" must not match "highlight")
POSITIVE_PATTERNS = [
    re.compile(r'\b' + word + r'\b')
    for word in (
        "profit", "growth", "beat", "surge", "record", "strong", "rally",
        "upgrade", "outperform", "expansion", "deal", "contract won",
        "positive", "bullish", "rises", "risen", "gains", "gained",
        "exceeded", "soars", "soared", "jumps", "jumped", "climbs",
    )
]

# Negative sentiment keywords — word-boundary regex
NEGATIVE_PATTERNS = [
    re.compile(r'\b' + word + r'\b')
    for word in (
        "loss", "decline", "miss", "falls", "fallen", "drops", "dropped",
        "weak", "downgrade", "underperform", "cuts", "reduce", "shutdown",
        "fraud", "negative", "bearish", "slump", "slumps", "plunges",
        "plunged", "sinks", "crashed", "tumbles",
    )
]


class NewsSentimentFetcher:
    """
    Fetches and parses news sentiment for watchlist stocks.

    Design choices:
    - We batch stocks to minimize API calls (Marketaux allows comma-separated symbols)
    - We cache the result for the day (only fetch once at 9 AM)
    - Cache auto-resets on new calendar day (no stale data if process stays alive)
    - All failures are caught — missing news never crashes the bot
    """

    def __init__(self, news_config):
        self.config = news_config
        self._cache: dict[str, dict] = {}   # symbol → sentiment result
        self._fetch_date: Optional[date] = None  # Date when cache was populated
        self._global_risk = False           # True on RBI/budget/geopolitical days

    def fetch_all(self, symbols: list[str]) -> dict[str, dict]:
        """
        Fetch sentiment for all watchlist stocks.
        Returns dict: {symbol: {sentiment, score, skip_today, headlines}}

        Called once at 9:00 AM. Results cached for the day.
        Auto-resets if called on a new calendar day.
        """
        # Reset cache if it's from a previous day (handles overnight process)
        today = date.today()
        if self._fetch_date is not None and self._fetch_date != today:
            logger.info("New day detected — resetting news sentiment cache")
            self._fetch_date = None
            self._cache.clear()
            self._global_risk = False

        if self._fetch_date is not None:
            return self._cache

        if not self.config.enabled or not self.config.api_key:
            logger.warning(
                "NEWS_API_KEY not set in .env — news sentiment disabled. "
                "All stocks will use neutral sentiment (score +0 instead of +10). "
                "Bot will continue normally. Get a free key at https://www.marketaux.com/"
            )
            self._cache = {s: _neutral_sentiment() for s in symbols}
            self._fetch_date = today
            return self._cache

        logger.info(f"Fetching news sentiment for {len(symbols)} stocks...")

        # Initialize all stocks with neutral sentiment
        result: dict[str, dict] = {s: _neutral_sentiment() for s in symbols}

        try:
            # Step 1: Fetch India market news + global geopolitical news (2 API calls)
            market_news = self._fetch_market_news()
            global_news = self._fetch_global_news()
            # Combine both for global risk check — geopolitical events often
            # don't appear in India-filtered news but still impact NSE heavily
            all_market_news = market_news + global_news
            self._global_risk = self._check_global_risk(all_market_news)
            if self._global_risk:
                logger.warning(
                    "GLOBAL RISK EVENT detected in news — position sizes will be reduced by 50%"
                )

            # Step 2: Fetch targeted news for top N stocks (batch API calls)
            # We limit to max_stocks_to_fetch to stay within 100 req/day
            priority_symbols = symbols[:self.config.max_stocks_to_fetch]
            quota_exhausted = False

            for symbol in priority_symbols:
                if quota_exhausted:
                    break  # Stop wasting time on API calls that will fail
                try:
                    articles = self._fetch_stock_news(symbol)
                    if articles:
                        result[symbol] = self._analyze_articles(articles, symbol)
                except requests.exceptions.HTTPError as he:
                    if he.response is not None and he.response.status_code in (402, 429):
                        logger.warning(
                            f"Marketaux API quota exhausted (HTTP {he.response.status_code}). "
                            f"Skipping remaining {len(priority_symbols)} stock news fetches. "
                            f"All stocks will use neutral sentiment."
                        )
                        quota_exhausted = True
                    else:
                        logger.warning(f"News fetch failed for {symbol}: {he}")
                except Exception as e:
                    logger.warning(f"News fetch failed for {symbol}: {e}")
                    # Keep neutral sentiment for this stock

        except Exception as e:
            logger.warning(f"News sentiment fetch failed: {e}. Continuing with neutral sentiment.")

        self._cache = result
        self._fetch_date = today

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
            articles = resp.json().get("data", [])
            logger.info(f"India market news: fetched {len(articles)} articles")
            return articles
        except Exception as e:
            logger.warning(f"Market news fetch failed: {e}")
            return []

    def _fetch_global_news(self) -> list[dict]:
        """Fetch global geopolitical/economic news (1 API call).

        Why: Events like USA-Iran-Israel conflict, oil shocks, trade wars
        don't appear in India-filtered news but heavily impact NSE.
        We search for key terms without country filter.
        """
        url = "https://api.marketaux.com/v1/news/all"
        params = {
            "api_token": self.config.api_key,
            "search": "geopolitical OR war OR sanctions OR conflict OR crude oil OR trade war OR tariff",
            "language": "en",
            "published_after": (datetime.now() - timedelta(hours=18)).strftime(
                "%Y-%m-%dT%H:%M"
            ),
            "limit": 10,
        }
        try:
            resp = requests.get(url, params=params, timeout=10)
            resp.raise_for_status()
            articles = resp.json().get("data", [])
            if articles:
                logger.info(f"Global news: fetched {len(articles)} geopolitical/macro articles")
            return articles
        except Exception as e:
            logger.warning(f"Global news fetch failed: {e}")
            return []

    def _fetch_stock_news(self, symbol: str) -> list[dict]:
        """Fetch news for a specific NSE stock symbol (1 API call per stock)."""
        url = "https://api.marketaux.com/v1/news/all"
        # Marketaux uses Yahoo Finance format: RELIANCE.NS (not .NSE)
        # .NSE returns 0 results, .NS returns actual news
        params = {
            "api_token": self.config.api_key,
            "symbols": f"{symbol}.NS",
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
        except requests.exceptions.HTTPError as he:
            # Let 402 (Payment Required) and 429 (Rate Limited) propagate
            # so caller can stop wasting API calls
            if he.response is not None and he.response.status_code in (402, 429):
                raise
            logger.warning(f"Stock news fetch failed for {symbol}: {he}")
            return []
        except Exception as e:
            logger.warning(f"Stock news fetch failed for {symbol}: {e}")
            return []

    def _analyze_articles(self, articles: list[dict], symbol: str = "") -> dict:
        """
        Score a list of news articles for a stock.

        Marketaux articles have sentiment data inside entities[].sentiment_score
        (numeric -1.0 to +1.0), NOT as a top-level string field.
        We prefer entity sentiment when available, fall back to keyword matching.

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

        # Process at most 5 articles
        capped_articles = articles[:5]

        for article in capped_articles:
            title = (article.get("title") or "").lower()
            description = (article.get("description") or "").lower()
            text = f"{title} {description}"

            headlines.append(article.get("title", "")[:100])

            # Check if it's an earnings/event day
            if any(kw in text for kw in SKIP_KEYWORDS):
                skip_today = True
                logger.info(f"Earnings/event detected in news for {symbol} — marking to skip")

            # Primary: use Marketaux entity sentiment_score (numeric, -1 to +1)
            # The API puts sentiment on each entity inside the article
            entity_sentiment = self._extract_entity_sentiment(article, symbol)

            if entity_sentiment is not None:
                # Numeric score: > 0.2 = positive, < -0.2 = negative
                if entity_sentiment > 0.2:
                    positive_count += 1
                elif entity_sentiment < -0.2:
                    negative_count += 1
                # Between -0.2 and 0.2 = neutral (not counted)
            else:
                # Fallback: keyword matching with word-boundary regex
                # (avoids "up" matching "update", "down" matching "download", etc.)
                pos_hits = sum(1 for p in POSITIVE_PATTERNS if p.search(text))
                neg_hits = sum(1 for p in NEGATIVE_PATTERNS if p.search(text))
                if pos_hits > neg_hits:
                    positive_count += 1
                elif neg_hits > pos_hits:
                    negative_count += 1

        # Aggregate sentiment — use capped count, not full list length
        total = len(capped_articles)
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

    def _extract_entity_sentiment(self, article: dict, symbol: str) -> Optional[float]:
        """Extract numeric sentiment_score from Marketaux article entities.

        Marketaux puts sentiment data inside entities[].sentiment_score as a
        float between -1.0 and +1.0. We look for the entity matching our stock
        symbol (e.g., RELIANCE.NS). If not found, average all entity scores.

        Returns:
            Float sentiment score, or None if no entities have sentiment.
        """
        entities = article.get("entities", [])
        if not entities:
            return None

        # Try to find entity matching our symbol (e.g., "RELIANCE.NS")
        target_symbol = f"{symbol}.NS" if symbol else ""
        for entity in entities:
            entity_symbol = entity.get("symbol", "")
            if entity_symbol == target_symbol:
                score = entity.get("sentiment_score")
                if score is not None:
                    return float(score)

        # No exact match — fall back to keyword matching (safer than averaging
        # unrelated entities which may be for completely different stocks)
        logger.debug(
            f"No exact entity match for {target_symbol} in article — "
            f"falling back to keyword matching"
        )
        return None

    def _check_global_risk(self, articles: list[dict]) -> bool:
        """Check if general market news contains a major risk event.

        Scans both title and description of each article for keywords
        from GLOBAL_RISK_KEYWORDS list.
        """
        for article in articles:
            text = (
                (article.get("title") or "") + " " + (article.get("description") or "")
            ).lower()
            for kw in GLOBAL_RISK_KEYWORDS:
                if kw in text:
                    logger.info(f"Global risk keyword '{kw}' found in: {article.get('title', '')[:80]}")
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
