# Graph Report - nse-trading-bot  (2026-05-02)

## Corpus Check
- 59 files · ~76,690 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 909 nodes · 2339 edges · 35 communities detected
- Extraction: 46% EXTRACTED · 54% INFERRED · 0% AMBIGUOUS · INFERRED: 1272 edges (avg confidence: 0.56)
- Token cost: 0 input · 0 output

## Community Hubs (Navigation)
- [[_COMMUNITY_Community 0|Community 0]]
- [[_COMMUNITY_Community 1|Community 1]]
- [[_COMMUNITY_Community 2|Community 2]]
- [[_COMMUNITY_Community 3|Community 3]]
- [[_COMMUNITY_Community 4|Community 4]]
- [[_COMMUNITY_Community 5|Community 5]]
- [[_COMMUNITY_Community 6|Community 6]]
- [[_COMMUNITY_Community 7|Community 7]]
- [[_COMMUNITY_Community 8|Community 8]]
- [[_COMMUNITY_Community 9|Community 9]]
- [[_COMMUNITY_Community 10|Community 10]]
- [[_COMMUNITY_Community 11|Community 11]]
- [[_COMMUNITY_Community 12|Community 12]]
- [[_COMMUNITY_Community 13|Community 13]]
- [[_COMMUNITY_Community 14|Community 14]]
- [[_COMMUNITY_Community 15|Community 15]]
- [[_COMMUNITY_Community 16|Community 16]]
- [[_COMMUNITY_Community 17|Community 17]]
- [[_COMMUNITY_Community 18|Community 18]]
- [[_COMMUNITY_Community 19|Community 19]]
- [[_COMMUNITY_Community 20|Community 20]]
- [[_COMMUNITY_Community 25|Community 25]]
- [[_COMMUNITY_Community 26|Community 26]]
- [[_COMMUNITY_Community 27|Community 27]]
- [[_COMMUNITY_Community 28|Community 28]]
- [[_COMMUNITY_Community 30|Community 30]]
- [[_COMMUNITY_Community 31|Community 31]]
- [[_COMMUNITY_Community 38|Community 38]]
- [[_COMMUNITY_Community 39|Community 39]]
- [[_COMMUNITY_Community 40|Community 40]]
- [[_COMMUNITY_Community 41|Community 41]]
- [[_COMMUNITY_Community 42|Community 42]]
- [[_COMMUNITY_Community 43|Community 43]]
- [[_COMMUNITY_Community 44|Community 44]]
- [[_COMMUNITY_Community 45|Community 45]]

## God Nodes (most connected - your core abstractions)
1. `Signal` - 131 edges
2. `ORBStrategy` - 74 edges
3. `PatternScanner` - 71 edges
4. `SignalScorer` - 68 edges
5. `VWAPBounceStrategy` - 68 edges
6. `SRBreakoutStrategy` - 67 edges
7. `BrokerConnection` - 65 edges
8. `EMACrossoverStrategy` - 65 edges
9. `MacroAnalyzer` - 58 edges
10. `SectorAnalyzer` - 57 edges

## Surprising Connections (you probably didn't know these)
- `Order Manager — Places, Monitors, and Exits Trades (Sniper Mode V2). ===========` --uses--> `Signal`  [INFERRED]
  backend\core\order_manager.py → backend\strategies\base_strategy.py
- `An open trade being monitored.      Key fields for production tracking:     - re` --uses--> `Signal`  [INFERRED]
  backend\core\order_manager.py → backend\strategies\base_strategy.py
- `Get last traded price from WebSocket cache. ZERO API calls.          Falls back` --uses--> `Signal`  [INFERRED]
  backend\core\order_manager.py → backend\strategies\base_strategy.py
- `Adopt existing open intraday positions from Angel One on startup.          Calle` --uses--> `Signal`  [INFERRED]
  backend\core\order_manager.py → backend\strategies\base_strategy.py
- `Place a STOPLOSS-LIMIT order with Angel One for a position.          This is the` --uses--> `Signal`  [INFERRED]
  backend\core\order_manager.py → backend\strategies\base_strategy.py

## Communities

### Community 0 - "Community 0"
Cohesion: 0.06
Nodes (90): NSE Intraday Trading Bot -- Main Entry Point ===================================, Distribute VIX value to all components that need it., Poll India VIX via Yahoo Finance every 5 minutes.          Why: Angel One WebSoc, Called once at 10:30 AM to lock in the day's market regime.         Updates risk, Execute a signal: place order, update Firebase, log to CSV., 30-second confirmation window for live trades.          Push the signal to Fireb, Called when a position fully closes (SL hit, target hit, or force exit)., Called by data_stream after a successful WebSocket reconnect.         During the (+82 more)

### Community 1 - "Community 1"
Cohesion: 0.06
Nodes (88): backtest_equity_orb(), backtest_options(), daily_to_5min_groups(), fetch_vix_daily(), load_cached_data(), main(), mom_table(), 12-Month Intraday Backtester — uses cached Angel One 5-min data ================ (+80 more)

### Community 2 - "Community 2"
Cohesion: 0.03
Nodes (61): ABC, First partial exit level: entry + 1x risk., How long this position has been open (minutes)., Current unrealized profit as a percentage of entry price., Price at 70% of target (win zone threshold)., Manages order lifecycle: place -> monitor -> exit., Wire up the WebSocket data stream for cached price reads., Run the 17-point pre-flight checklist before placing any order.          Every c (+53 more)

### Community 3 - "Community 3"
Cohesion: 0.03
Nodes (41): Fetch today's completed 5-minute intraday candles from Angel One.          Used, Get available cash and intraday margin from Angel One RMS system.          Retur, Check if an API response indicates a rate limit error.          Angel One return, Check if connected before making API calls., Call an API function with exponential backoff on failure.          How it works:, Place an order with Angel One.          Angel One transaction types:         - ", Place a NIFTY/BANKNIFTY option order on Angel One.          Key differences from, Get current LTP (premium) of an option from Angel One. (+33 more)

### Community 4 - "Community 4"
Cohesion: 0.04
Nodes (22): main(), Refresh the auth token before it expires.         Angel One tokens expire after, Fetch today's 5-min intraday candles for multiple stocks and indices.          U, Try to connect multiple times with increasing delay between attempts., Authenticate with Angel One.          Steps:         1. Create SmartConnect sess, Creates and runs the WebSocket connection.         Handles reconnection with tok, Called when WebSocket connection is established.         This is where we tell A, Start streaming price data for the given instrument tokens.          Args: (+14 more)

### Community 5 - "Community 5"
Cohesion: 0.06
Nodes (18): CapitalInput(), getScoreTier(), SignalCard(), MarketContext(), PositionCard(), PerformanceCard(), StrategyBreakdown(), StrategyRow() (+10 more)

### Community 6 - "Community 6"
Cohesion: 0.05
Nodes (22): Fetch India VIX value.          Uses Yahoo Finance free API (no API key needed), Set market stance from macro analysis (called at startup)., Flag global risk day for awareness — NO size reduction.          Called from mai, Push news sentiment summary to Firebase.         The NewsAlert dashboard compone, Push pre-market check results to Firebase.         The PreMarketStatus dashboard, _neutral_sentiment(), News Sentiment — Marketaux API Integration =====================================, Fetch sentiment for all watchlist stocks.         Returns dict: {symbol: {sentim (+14 more)

### Community 7 - "Community 7"
Cohesion: 0.07
Nodes (25): Cancel a broker-side SL order (before placing a manual exit)., Place a MARKET order to exit a position.         Used for force-exit at 3:15 PM, Exit 50% of position at 1x RR and move SL to breakeven., Close all remaining shares. Cancel broker SL first. Record final P&L., Sync internal state with broker's actual positions after reconnect.         If b, Remove a Position that was created for an unfilled order.          This handles, Update the broker-side SL order to match the new trailing/breakeven SL., Cancel the broker-side SL order before placing a manual exit.          Must be c (+17 more)

### Community 8 - "Community 8"
Cohesion: 0.08
Nodes (31): authenticate(), fetch_all(), fetch_chunk(), fetch_symbol_full_year(), main(), parse_candles_to_df(), Angel One Historical Data Fetcher — 12 months of 5-min bars ====================, Fetch one chunk (max 30 days) of 5-min candles.     Returns list of [timestamp_s (+23 more)

### Community 9 - "Community 9"
Cohesion: 0.08
Nodes (25): Human-readable score quality label., Score a signal from 0-100.          Args:             signal: The Signal to eval, calculate_atr(), calculate_ema(), calculate_vwap(), candle_price_confirmation(), choppiness_index(), detect_support_resistance() (+17 more)

### Community 10 - "Community 10"
Cohesion: 0.08
Nodes (17): Fetch previous day OHLC for a single stock with rate limiting and smart backoff., Master function: cache -> capital filter -> batch fetch -> cache results., calculate_trade_viability(), filter_stocks_by_capital(), Pre-filters the watchlist by capital before any expensive historical API calls., Check if trading this stock can realistically profit after all charges.      Ang, Filter watchlist to only stocks that are affordable AND profitable to trade., load_cached_ohlc() (+9 more)

### Community 11 - "Community 11"
Cohesion: 0.07
Nodes (11): current_time_slot(), generate_time_slots(), is_expiry_day(), Volume Profile Manager — Time-of-Day (TOD) volume tracking. ====================, Get 10-day average volume for a stock at a specific time-of-day slot.          R, How many days of historical TOD data exist for this stock at this slot., Get 10-day average volume for NIFTY at a specific time-of-day slot., Get 20-day average daily volume for a stock.         Returns 0.0 if no data exis (+3 more)

### Community 12 - "Community 12"
Cohesion: 0.09
Nodes (10): Check if index ORB breakout + retest → option signal.          Returns dict with, Update regime-based multipliers (called from main.py on regime update)., Push a new trading signal to Firebase.         The dashboard's LiveSignals compo, Push market regime to Firebase.         The MarketContext dashboard component sh, Determines and locks in the market regime for the day.         Called once at 10, Position size multiplier based on regime.          All regimes return 1.0 — posi, Stop-loss width multiplier based on regime.         - VOLATILE: wider SL (1.2×), Override minimum score threshold based on regime.         Returns 0 = use config (+2 more)

### Community 13 - "Community 13"
Cohesion: 0.1
Nodes (12): Fundamental Filter — Red Flags + Fair Value + Earnings Calendar. ===============, Fetch fundamental data for a single stock via yfinance., Check if stock has earnings within 7 days., Compute PE vs sector average to determine fair value modifier., Load fundamental cache from JSON file., Save fundamental cache to JSON file., Fundamental metrics and flags for a single stock., Check if cached entry is still valid (within expiry window). (+4 more)

### Community 14 - "Community 14"
Cohesion: 0.12
Nodes (14): AppConfig, BrokerConfig, FirebaseConfig, IndicatorConfig, NewsConfig, Configuration for the trading bot. All settings in one place. Reads secrets from, Angel One SmartAPI credentials., Firebase connection settings. (+6 more)

### Community 15 - "Community 15"
Cohesion: 0.21
Nodes (6): Read the entire CSV and compute all-time performance stats.         Called at en, Same as get_summary() but filtered to today's trades only., Per-strategy performance.          Returns something like:         {, Counts how many trades were taken at each score range.          Use this to tune, Read all rows from the CSV file., Read only today's trades from the CSV.

### Community 16 - "Community 16"
Cohesion: 0.32
Nodes (4): useFirebase(), useFirebaseList(), useTradeData(), App()

### Community 17 - "Community 17"
Cohesion: 0.33
Nodes (4): OptionSignal, NIFTY/BANKNIFTY Options Strategy — ORB-Based Option Buying. ====================, Check for NIFTY ORB breakout + retest → option buy signal.          Args:, Signal to buy a NIFTY/BANKNIFTY option.

### Community 18 - "Community 18"
Cohesion: 0.33
Nodes (3): Combine VIX zone + NIFTY DMA trend into a single market stance.          Stance, Main entry point. Fetch NIFTY daily data, compute DMAs, determine stance., Fetch 1 year of NIFTY 50 daily candles and compute 50/200 DMA.

### Community 19 - "Community 19"
Cohesion: 0.5
Nodes (2): Called every time a new price tick arrives from Angel One.          The message, Convert Angel One's raw WebSocket message into our standard tick format.

### Community 20 - "Community 20"
Cohesion: 0.67
Nodes (1): Data Stream — Real-time Price Data via Angel One WebSocket =====================

### Community 25 - "Community 25"
Cohesion: 1.0
Nodes (1): How many points between entry and stop-loss.

### Community 26 - "Community 26"
Cohesion: 1.0
Nodes (1): How many points between entry and target.

### Community 27 - "Community 27"
Cohesion: 1.0
Nodes (1): Reward ÷ Risk. We want this ≥ 1.5.

### Community 28 - "Community 28"
Cohesion: 1.0
Nodes (1): Analyze data and return a Signal if conditions are met.                  Args:

### Community 30 - "Community 30"
Cohesion: 1.0
Nodes (1): Safely convert to float, handling None and non-numeric values.

### Community 31 - "Community 31"
Cohesion: 1.0
Nodes (1): Look up sector for a stock symbol. Returns empty string if not mapped.

### Community 38 - "Community 38"
Cohesion: 1.0
Nodes (1): Validate config values to catch misconfiguration early.

### Community 39 - "Community 39"
Cohesion: 1.0
Nodes (1): Technical indicator settings.

### Community 40 - "Community 40"
Cohesion: 1.0
Nodes (1): Master config combining all sub-configs.

### Community 41 - "Community 41"
Cohesion: 1.0
Nodes (1): Monitor open option positions. Check SL, target, time exit.         Returns list

### Community 42 - "Community 42"
Cohesion: 1.0
Nodes (1): Force-exit all open option positions.

### Community 43 - "Community 43"
Cohesion: 1.0
Nodes (1): Close an option position — sell the option.

### Community 44 - "Community 44"
Cohesion: 1.0
Nodes (1): Get next Thursday expiry in Angel One format: DDMMMYYYY.         Example: "27MAR

### Community 45 - "Community 45"
Cohesion: 1.0
Nodes (1): Reset for new trading day.

## Knowledge Gaps
- **242 isolated node(s):** `Configuration for the trading bot. All settings in one place. Reads secrets from`, `Angel One SmartAPI credentials.`, `Firebase connection settings.`, `News sentiment API settings (Marketaux free tier: 100 req/day).`, `Core trading parameters.` (+237 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **Thin community `Community 19`** (4 nodes): `._on_data()`, `._parse_tick()`, `Called every time a new price tick arrives from Angel One.          The message`, `Convert Angel One's raw WebSocket message into our standard tick format.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 20`** (3 nodes): `data_stream.py`, `Data Stream — Real-time Price Data via Angel One WebSocket =====================`, `# IMPORTANT: pass a COPY of the tokens list. SmartWebSocketV2.subscribe()`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 25`** (1 nodes): `How many points between entry and stop-loss.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 26`** (1 nodes): `How many points between entry and target.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 27`** (1 nodes): `Reward ÷ Risk. We want this ≥ 1.5.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 28`** (1 nodes): `Analyze data and return a Signal if conditions are met.                  Args:`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 30`** (1 nodes): `Safely convert to float, handling None and non-numeric values.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 31`** (1 nodes): `Look up sector for a stock symbol. Returns empty string if not mapped.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 38`** (1 nodes): `Validate config values to catch misconfiguration early.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 39`** (1 nodes): `Technical indicator settings.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 40`** (1 nodes): `Master config combining all sub-configs.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 41`** (1 nodes): `Monitor open option positions. Check SL, target, time exit.         Returns list`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 42`** (1 nodes): `Force-exit all open option positions.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 43`** (1 nodes): `Close an option position — sell the option.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 44`** (1 nodes): `Get next Thursday expiry in Angel One format: DDMMMYYYY.         Example: "27MAR`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 45`** (1 nodes): `Reset for new trading day.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `Signal` connect `Community 2` to `Community 0`, `Community 1`, `Community 3`, `Community 4`, `Community 6`, `Community 7`, `Community 12`?**
  _High betweenness centrality (0.181) - this node is a cross-community bridge._
- **Why does `PatternScanner` connect `Community 0` to `Community 1`, `Community 2`, `Community 4`, `Community 6`, `Community 9`, `Community 10`, `Community 11`, `Community 12`?**
  _High betweenness centrality (0.169) - this node is a cross-community bridge._
- **Why does `BrokerConnection` connect `Community 0` to `Community 3`, `Community 4`, `Community 6`, `Community 7`, `Community 10`?**
  _High betweenness centrality (0.151) - this node is a cross-community bridge._
- **Are the 126 inferred relationships involving `Signal` (e.g. with `Position` and `OrderManager`) actually correct?**
  _`Signal` has 126 INFERRED edges - model-reasoned connections that need verification._
- **Are the 66 inferred relationships involving `ORBStrategy` (e.g. with `BacktestPosition` and `BacktestTrade`) actually correct?**
  _`ORBStrategy` has 66 INFERRED edges - model-reasoned connections that need verification._
- **Are the 38 inferred relationships involving `PatternScanner` (e.g. with `TradingBot` and `NSE Intraday Trading Bot -- Main Entry Point ===================================`) actually correct?**
  _`PatternScanner` has 38 INFERRED edges - model-reasoned connections that need verification._
- **Are the 63 inferred relationships involving `SignalScorer` (e.g. with `BacktestPosition` and `BacktestTrade`) actually correct?**
  _`SignalScorer` has 63 INFERRED edges - model-reasoned connections that need verification._