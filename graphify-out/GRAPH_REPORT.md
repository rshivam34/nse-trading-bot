# Graph Report - nse-trading-bot  (2026-05-07)

## Corpus Check
- 65 files · ~85,553 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 983 nodes · 2463 edges · 42 communities detected
- Extraction: 48% EXTRACTED · 52% INFERRED · 0% AMBIGUOUS · INFERRED: 1276 edges (avg confidence: 0.56)
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
- [[_COMMUNITY_Community 21|Community 21]]
- [[_COMMUNITY_Community 22|Community 22]]
- [[_COMMUNITY_Community 23|Community 23]]
- [[_COMMUNITY_Community 24|Community 24]]
- [[_COMMUNITY_Community 25|Community 25]]
- [[_COMMUNITY_Community 26|Community 26]]
- [[_COMMUNITY_Community 27|Community 27]]
- [[_COMMUNITY_Community 32|Community 32]]
- [[_COMMUNITY_Community 33|Community 33]]
- [[_COMMUNITY_Community 34|Community 34]]
- [[_COMMUNITY_Community 35|Community 35]]
- [[_COMMUNITY_Community 37|Community 37]]
- [[_COMMUNITY_Community 38|Community 38]]
- [[_COMMUNITY_Community 47|Community 47]]
- [[_COMMUNITY_Community 48|Community 48]]
- [[_COMMUNITY_Community 49|Community 49]]
- [[_COMMUNITY_Community 50|Community 50]]
- [[_COMMUNITY_Community 51|Community 51]]
- [[_COMMUNITY_Community 52|Community 52]]
- [[_COMMUNITY_Community 53|Community 53]]
- [[_COMMUNITY_Community 54|Community 54]]

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
- `Manages order lifecycle: place -> monitor -> exit.` --uses--> `Signal`  [INFERRED]
  backend\core\order_manager.py → backend\strategies\base_strategy.py
- `Wire up the WebSocket data stream for cached price reads.` --uses--> `Signal`  [INFERRED]
  backend\core\order_manager.py → backend\strategies\base_strategy.py
- `Get last traded price from WebSocket cache. ZERO API calls.          Falls back` --uses--> `Signal`  [INFERRED]
  backend\core\order_manager.py → backend\strategies\base_strategy.py

## Communities

### Community 0 - "Community 0"
Cohesion: 0.03
Nodes (129): backtest_equity_orb(), backtest_options(), daily_to_5min_groups(), fetch_vix_daily(), load_cached_data(), main(), mom_table(), 12-Month Intraday Backtester — uses cached Angel One 5-min data ================ (+121 more)

### Community 1 - "Community 1"
Cohesion: 0.06
Nodes (93): NSE Intraday Trading Bot -- Main Entry Point ===================================, Distribute VIX value to all components that need it., Poll India VIX via Yahoo Finance every 5 minutes.          Why: Angel One WebSoc, Called once at 10:30 AM to lock in the day's market regime.         Updates risk, Execute a signal: place order, update Firebase, log to CSV., 30-second confirmation window for live trades.          Push the signal to Fireb, Called when a position fully closes (SL hit, target hit, or force exit)., Called by data_stream after a successful WebSocket reconnect.         During the (+85 more)

### Community 2 - "Community 2"
Cohesion: 0.03
Nodes (43): Fetch today's completed 5-minute intraday candles from Angel One.          Used, Get available cash and intraday margin from Angel One RMS system.          Retur, Check if an API response indicates a rate limit error.          Angel One return, Check if connected before making API calls., Call an API function with exponential backoff on failure.          How it works:, Place an order with Angel One.          Angel One transaction types:         - ", Cancel a pending order., Place a STOPLOSS-LIMIT order with Angel One.          This is a safety net — eve (+35 more)

### Community 3 - "Community 3"
Cohesion: 0.04
Nodes (31): Check if index ORB breakout + retest → option signal.          Returns dict with, Run the 17-point pre-flight checklist before placing any order.          Every c, Update regime-based multipliers (called from main.py on regime update)., Get the maximum capital we're allowed to have deployed at once.          Returns, Return current capital deployment stats (for logging/dashboard)., Gate every potential trade through all safety rules.         Sets signal.reason, Position sizing with VIX 4-zone scaling, time-based, and regime scaling., Position size % based on time of day.          Full trading: 9:30-14:30 at 100%. (+23 more)

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
Cohesion: 0.09
Nodes (24): BotProcess, ControlPanel, daily_history(), monthly_summary(), overall_stats(), parse_trade_pnl(), NSE Bot Control Panel — Desktop GUI ====================================== Singl, Read trades from logs/trades.csv, filtered to >= since date. Returns list of dic (+16 more)

### Community 8 - "Community 8"
Cohesion: 0.07
Nodes (27): Human-readable score quality label., Score a signal from 0-100.          Args:             signal: The Signal to eval, calculate_atr(), calculate_ema(), calculate_rsi(), calculate_vwap(), candle_price_confirmation(), choppiness_index() (+19 more)

### Community 9 - "Community 9"
Cohesion: 0.08
Nodes (31): authenticate(), fetch_all(), fetch_chunk(), fetch_symbol_full_year(), main(), parse_candles_to_df(), Angel One Historical Data Fetcher — 12 months of 5-min bars ====================, Fetch one chunk (max 30 days) of 5-min candles.     Returns list of [timestamp_s (+23 more)

### Community 10 - "Community 10"
Cohesion: 0.08
Nodes (17): Fetch previous day OHLC for a single stock with rate limiting and smart backoff., Master function: cache -> capital filter -> batch fetch -> cache results., calculate_trade_viability(), filter_stocks_by_capital(), Pre-filters the watchlist by capital before any expensive historical API calls., Check if trading this stock can realistically profit after all charges.      Ang, Filter watchlist to only stocks that are affordable AND profitable to trade., load_cached_ohlc() (+9 more)

### Community 11 - "Community 11"
Cohesion: 0.07
Nodes (11): current_time_slot(), generate_time_slots(), is_expiry_day(), Volume Profile Manager — Time-of-Day (TOD) volume tracking. ====================, Get 10-day average volume for a stock at a specific time-of-day slot.          R, How many days of historical TOD data exist for this stock at this slot., Get 10-day average volume for NIFTY at a specific time-of-day slot., Get 20-day average daily volume for a stock.         Returns 0.0 if no data exis (+3 more)

### Community 12 - "Community 12"
Cohesion: 0.15
Nodes (22): discover_chat_id(), fetch_portfolio(), fetch_status(), fetch_today_trades(), format_report(), init_firebase(), load_env(), log() (+14 more)

### Community 13 - "Community 13"
Cohesion: 0.1
Nodes (12): Place a NIFTY/BANKNIFTY option order on Angel One.          Key differences from, Get current LTP (premium) of an option from Angel One., Get option chain (CE + PE) for strikes around the spot price.          Returns l, Look up instrument token for an option from the cached instrument master., OptionPosition, Options Manager — NIFTY/BANKNIFTY Option Buying via ORB Retest. ================, Execute an option signal: build symbol, look up token, place order.          Ret, Active option position being monitored. (+4 more)

### Community 14 - "Community 14"
Cohesion: 0.1
Nodes (12): Fundamental Filter — Red Flags + Fair Value + Earnings Calendar. ===============, Fetch fundamental data for a single stock via yfinance., Check if stock has earnings within 7 days., Compute PE vs sector average to determine fair value modifier., Load fundamental cache from JSON file., Save fundamental cache to JSON file., Fundamental metrics and flags for a single stock., Check if cached entry is still valid (within expiry window). (+4 more)

### Community 15 - "Community 15"
Cohesion: 0.12
Nodes (14): AppConfig, BrokerConfig, FirebaseConfig, IndicatorConfig, NewsConfig, Configuration for the trading bot. All settings in one place. Reads secrets from, Angel One SmartAPI credentials., Firebase connection settings. (+6 more)

### Community 16 - "Community 16"
Cohesion: 0.21
Nodes (6): Read the entire CSV and compute all-time performance stats.         Called at en, Same as get_summary() but filtered to today's trades only., Per-strategy performance.          Returns something like:         {, Counts how many trades were taken at each score range.          Use this to tune, Read all rows from the CSV file., Read only today's trades from the CSV.

### Community 17 - "Community 17"
Cohesion: 0.32
Nodes (4): useFirebase(), useFirebaseList(), useTradeData(), App()

### Community 18 - "Community 18"
Cohesion: 0.29
Nodes (2): ABC, Base Strategy — All trading strategies inherit from this. ======================

### Community 19 - "Community 19"
Cohesion: 0.33
Nodes (4): OptionSignal, NIFTY/BANKNIFTY Options Strategy — ORB-Based Option Buying. ====================, Check for NIFTY ORB breakout + retest → option buy signal.          Args:, Signal to buy a NIFTY/BANKNIFTY option.

### Community 20 - "Community 20"
Cohesion: 0.33
Nodes (3): Combine VIX zone + NIFTY DMA trend into a single market stance.          Stance, Main entry point. Fetch NIFTY daily data, compute DMAs, determine stance., Fetch 1 year of NIFTY 50 daily candles and compute 50/200 DMA.

### Community 21 - "Community 21"
Cohesion: 0.6
Nodes (4): get_log_tail(), main(), Telegram notification hooks for systemd. =======================================, send()

### Community 22 - "Community 22"
Cohesion: 0.5
Nodes (2): Called every time a new price tick arrives from Angel One.          The message, Convert Angel One's raw WebSocket message into our standard tick format.

### Community 23 - "Community 23"
Cohesion: 0.67
Nodes (1): Data Stream — Real-time Price Data via Angel One WebSocket =====================

### Community 24 - "Community 24"
Cohesion: 1.0
Nodes (1): Risk Manager — The Guardian of Your Capital (Sniper Mode V2) ===================

### Community 25 - "Community 25"
Cohesion: 1.0
Nodes (1): Update current VIX value for position sizing decisions.

### Community 26 - "Community 26"
Cohesion: 1.0
Nodes (1): Record that we have an open position in this stock.

### Community 27 - "Community 27"
Cohesion: 1.0
Nodes (1): Macro Analysis — NIFTY DMA Trend + Market Stance System. =======================

### Community 32 - "Community 32"
Cohesion: 1.0
Nodes (1): How many points between entry and stop-loss.

### Community 33 - "Community 33"
Cohesion: 1.0
Nodes (1): How many points between entry and target.

### Community 34 - "Community 34"
Cohesion: 1.0
Nodes (1): Reward ÷ Risk. We want this ≥ 1.5.

### Community 35 - "Community 35"
Cohesion: 1.0
Nodes (1): Analyze data and return a Signal if conditions are met.                  Args:

### Community 37 - "Community 37"
Cohesion: 1.0
Nodes (1): Safely convert to float, handling None and non-numeric values.

### Community 38 - "Community 38"
Cohesion: 1.0
Nodes (1): Look up sector for a stock symbol. Returns empty string if not mapped.

### Community 47 - "Community 47"
Cohesion: 1.0
Nodes (1): Validate config values to catch misconfiguration early.

### Community 48 - "Community 48"
Cohesion: 1.0
Nodes (1): Technical indicator settings.

### Community 49 - "Community 49"
Cohesion: 1.0
Nodes (1): Master config combining all sub-configs.

### Community 50 - "Community 50"
Cohesion: 1.0
Nodes (1): Monitor open option positions. Check SL, target, time exit.         Returns list

### Community 51 - "Community 51"
Cohesion: 1.0
Nodes (1): Force-exit all open option positions.

### Community 52 - "Community 52"
Cohesion: 1.0
Nodes (1): Close an option position — sell the option.

### Community 53 - "Community 53"
Cohesion: 1.0
Nodes (1): Get next Thursday expiry in Angel One format: DDMMMYYYY.         Example: "27MAR

### Community 54 - "Community 54"
Cohesion: 1.0
Nodes (1): Reset for new trading day.

## Knowledge Gaps
- **266 isolated node(s):** `NSE Bot Control Panel — Desktop GUI ====================================== Singl`, `Read a single key=value line from .env`, `Update a single key=value in .env (preserves other lines).`, `Read a field's value from config.py (matches `field: type = value`).`, `Update a field's value in config.py (preserves type annotation + comment).` (+261 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **Thin community `Community 18`** (7 nodes): `ABC`, `base_strategy.py`, `check_signal()`, `Base Strategy — All trading strategies inherit from this. ======================`, `reward_points()`, `risk_points()`, `risk_reward_ratio()`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 22`** (4 nodes): `._on_data()`, `._parse_tick()`, `Called every time a new price tick arrives from Angel One.          The message`, `Convert Angel One's raw WebSocket message into our standard tick format.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 23`** (3 nodes): `data_stream.py`, `Data Stream — Real-time Price Data via Angel One WebSocket =====================`, `# IMPORTANT: pass a COPY of the tokens list. SmartWebSocketV2.subscribe()`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 24`** (2 nodes): `risk_manager.py`, `Risk Manager — The Guardian of Your Capital (Sniper Mode V2) ===================`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 25`** (2 nodes): `Update current VIX value for position sizing decisions.`, `.update_vix()`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 26`** (2 nodes): `Record that we have an open position in this stock.`, `.mark_stock_active()`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 27`** (2 nodes): `macro_analysis.py`, `Macro Analysis — NIFTY DMA Trend + Market Stance System. =======================`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 32`** (1 nodes): `How many points between entry and stop-loss.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 33`** (1 nodes): `How many points between entry and target.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 34`** (1 nodes): `Reward ÷ Risk. We want this ≥ 1.5.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 35`** (1 nodes): `Analyze data and return a Signal if conditions are met.                  Args:`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 37`** (1 nodes): `Safely convert to float, handling None and non-numeric values.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 38`** (1 nodes): `Look up sector for a stock symbol. Returns empty string if not mapped.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 47`** (1 nodes): `Validate config values to catch misconfiguration early.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 48`** (1 nodes): `Technical indicator settings.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 49`** (1 nodes): `Master config combining all sub-configs.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 50`** (1 nodes): `Monitor open option positions. Check SL, target, time exit.         Returns list`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 51`** (1 nodes): `Force-exit all open option positions.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 52`** (1 nodes): `Close an option position — sell the option.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 53`** (1 nodes): `Get next Thursday expiry in Angel One format: DDMMMYYYY.         Example: "27MAR`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 54`** (1 nodes): `Reset for new trading day.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `Signal` connect `Community 0` to `Community 1`, `Community 2`, `Community 3`, `Community 4`, `Community 6`, `Community 18`, `Community 24`, `Community 25`, `Community 26`?**
  _High betweenness centrality (0.161) - this node is a cross-community bridge._
- **Why does `PatternScanner` connect `Community 1` to `Community 0`, `Community 3`, `Community 4`, `Community 6`, `Community 8`, `Community 10`, `Community 11`?**
  _High betweenness centrality (0.143) - this node is a cross-community bridge._
- **Why does `BrokerConnection` connect `Community 1` to `Community 2`, `Community 4`, `Community 6`, `Community 10`, `Community 13`?**
  _High betweenness centrality (0.135) - this node is a cross-community bridge._
- **Are the 126 inferred relationships involving `Signal` (e.g. with `Position` and `OrderManager`) actually correct?**
  _`Signal` has 126 INFERRED edges - model-reasoned connections that need verification._
- **Are the 66 inferred relationships involving `ORBStrategy` (e.g. with `BacktestPosition` and `BacktestTrade`) actually correct?**
  _`ORBStrategy` has 66 INFERRED edges - model-reasoned connections that need verification._
- **Are the 38 inferred relationships involving `PatternScanner` (e.g. with `TradingBot` and `NSE Intraday Trading Bot -- Main Entry Point ===================================`) actually correct?**
  _`PatternScanner` has 38 INFERRED edges - model-reasoned connections that need verification._
- **Are the 63 inferred relationships involving `SignalScorer` (e.g. with `BacktestPosition` and `BacktestTrade`) actually correct?**
  _`SignalScorer` has 63 INFERRED edges - model-reasoned connections that need verification._