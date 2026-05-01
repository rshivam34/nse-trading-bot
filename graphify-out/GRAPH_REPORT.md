# Graph Report - nse-trading-bot  (2026-05-01)

## Corpus Check
- 57 files · ~72,002 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 871 nodes · 2264 edges · 34 communities detected
- Extraction: 45% EXTRACTED · 55% INFERRED · 0% AMBIGUOUS · INFERRED: 1238 edges (avg confidence: 0.56)
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

## God Nodes (most connected - your core abstractions)
1. `Signal` - 131 edges
2. `PatternScanner` - 71 edges
3. `VWAPBounceStrategy` - 68 edges
4. `SRBreakoutStrategy` - 67 edges
5. `BrokerConnection` - 65 edges
6. `EMACrossoverStrategy` - 65 edges
7. `ORBStrategy` - 65 edges
8. `SignalScorer` - 60 edges
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
Nodes (125): ABC, Run backtests for all available months at Rs.15K and Rs.50K capital. yfinance 5-, run_all(), Backtester, BacktestPosition, BacktestTrade, main(), Backtester — Replay Historical Data Through Full Signal Pipeline. ============== (+117 more)

### Community 1 - "Community 1"
Cohesion: 0.03
Nodes (56): BrokerConnection, Broker Connection — Angel One SmartAPI Wrapper =================================, Fetch today's completed 5-minute intraday candles from Angel One.          Used, Refresh the auth token before it expires.         Angel One tokens expire after, Get user profile — useful to verify connection., Check if an API response indicates a rate limit error.          Angel One return, Check if connected before making API calls., Log out from Angel One and clean up. (+48 more)

### Community 2 - "Community 2"
Cohesion: 0.03
Nodes (43): Run all pre-market checks. Returns True if safe to trade.          Steps:, Pre-seed today's 5-minute candles from Angel One Historical API.          This m, Fetch today's 5-min intraday candles for multiple stocks and indices.          U, Set market stance from macro analysis (called at startup)., Flag global risk day for awareness — NO size reduction.          Called from mai, PatternScanner, Human-readable score quality label., Called during 9:15-9:30 to record the opening range. (+35 more)

### Community 3 - "Community 3"
Cohesion: 0.04
Nodes (33): Get last traded price from WebSocket cache. Zero API calls.          Returns 0.0, Exit 50% of position at 1x RR and move SL to breakeven., Close all remaining shares. Cancel broker SL first. Record final P&L., Sync internal state with broker's actual positions after reconnect.         If b, Remove a Position that was created for an unfilled order.          This handles, Get last traded price from WebSocket cache. ZERO API calls.          Falls back, Update the broker-side SL order to match the new trailing/breakeven SL., Cancel the broker-side SL order before placing a manual exit.          Must be c (+25 more)

### Community 4 - "Community 4"
Cohesion: 0.1
Nodes (34): main(), NSE Intraday Trading Bot -- Main Entry Point ===================================, 30-second confirmation window for live trades.          Push the signal to Fireb, Called when a position fully closes (SL hit, target hit, or force exit)., Called by data_stream after a successful WebSocket reconnect.         During the, Called when the dashboard toggles trading ON or OFF.         Does NOT exit posit, Main loop -- runs from market open until 3:15 PM or kill switch.         The act, Record all force-closed positions to CSV and Firebase.          Called after exi (+26 more)

### Community 5 - "Community 5"
Cohesion: 0.06
Nodes (18): CapitalInput(), getScoreTier(), SignalCard(), MarketContext(), PositionCard(), PerformanceCard(), StrategyBreakdown(), StrategyRow() (+10 more)

### Community 6 - "Community 6"
Cohesion: 0.07
Nodes (18): Start the bot. This is the entry point called from main().          Startup sequ, Subscribe to live price data for all stocks + NIFTY + BANKNIFTY + VIX., Start streaming price data for the given instrument tokens.          Args:, FirebaseSync, Firebase Sync -- Pushes live trading data to the dashboard. ====================, Delete ALL positions from Firebase on startup.          Prevents stale phantom p, Update bot status in Firebase.         Dashboard uses this to show if bot is run, Mark bot as running in Firebase. (+10 more)

### Community 7 - "Community 7"
Cohesion: 0.07
Nodes (18): Called once at 10:30 AM to lock in the day's market regime.         Updates risk, Called every time a price tick arrives from Angel One WebSocket.         This is, Check if index ORB breakout + retest → option signal.          Returns dict with, Update regime-based multipliers (called from main.py on regime update)., Push a new trading signal to Firebase.         The dashboard's LiveSignals compo, Push NIFTY market context for the dashboard's MarketContext component., Push market regime to Firebase.         The MarketContext dashboard component sh, MarketRegimeDetector (+10 more)

### Community 8 - "Community 8"
Cohesion: 0.1
Nodes (12): TradingBot, Fetch India VIX value.          Uses Yahoo Finance free API (no API key needed), Emergency exit for all open positions (kill switch / force exit at 3:15)., Current portfolio snapshot for Firebase and logging.          Returns both gross, End-of-day performance summary.         Includes charge breakdown so you can see, Check if we've lost 3% or more of start-of-day capital., Push an executed/closed trade to Firebase.         These appear in the TradeHist, Push the current portfolio state to Firebase.         Called every few seconds s (+4 more)

### Community 9 - "Community 9"
Cohesion: 0.1
Nodes (12): Graceful shutdown: disconnect cleanly from broker and Firebase., Pre-flight check before the bot does anything.          Checks (in order):, Connect to Angel One with retry., Populate Average Daily Volume (ADV) from the daily volumes         captured duri, Try to connect multiple times with increasing delay between attempts., Load profiles from disk. Safe to call multiple times., Save profiles to disk., Set ADV data from broker's daily candle volumes (called at startup).          Ar (+4 more)

### Community 10 - "Community 10"
Cohesion: 0.1
Nodes (12): Fundamental Filter — Red Flags + Fair Value + Earnings Calendar. ===============, Fetch fundamental data for a single stock via yfinance., Check if stock has earnings within 7 days., Compute PE vs sector average to determine fair value modifier., Load fundamental cache from JSON file., Save fundamental cache to JSON file., Fundamental metrics and flags for a single stock., Check if cached entry is still valid (within expiry window). (+4 more)

### Community 11 - "Community 11"
Cohesion: 0.11
Nodes (11): _neutral_sentiment(), News Sentiment — Marketaux API Integration =====================================, Fetch sentiment for all watchlist stocks.         Returns dict: {symbol: {sentim, Get cached sentiment for a specific stock., Fetch general India market news (1 API call)., Fetch global geopolitical/economic news (1 API call).          Why: Events like, Fetch news for a specific NSE stock symbol (1 API call per stock)., Score a list of news articles for a stock.          Marketaux articles have sent (+3 more)

### Community 12 - "Community 12"
Cohesion: 0.14
Nodes (18): Load 200-stock watchlist and index tokens., build_watchlist(), get_banknifty_token(), get_nifty_token(), _get_token_map_from_master(), get_vix_token(), get_watchlist(), _load_cache() (+10 more)

### Community 13 - "Community 13"
Cohesion: 0.11
Nodes (7): Position, Order Manager — Places, Monitors, and Exits Trades (Sniper Mode V2). ===========, Adopt existing open intraday positions from Angel One on startup.          Calle, An open trade being monitored.      Key fields for production tracking:     - re, Fetch available margin from Angel One RMS API and cache it.          Called afte, Called by order_manager ONLY after Angel One confirms the order.          Increm, Call this at start of each trading day.

### Community 14 - "Community 14"
Cohesion: 0.12
Nodes (14): AppConfig, BrokerConfig, FirebaseConfig, IndicatorConfig, NewsConfig, Configuration for the trading bot. All settings in one place. Reads secrets from, Angel One SmartAPI credentials., Firebase connection settings. (+6 more)

### Community 15 - "Community 15"
Cohesion: 0.12
Nodes (8): Execute a signal: place order, update Firebase, log to CSV., Check available margin via getRMS() API on startup.         Caches it in risk_ma, Adopt any existing open intraday positions from Angel One.          This is CRIT, Get available cash and intraday margin from Angel One RMS system.          Retur, Get all open intraday positions from Angel One.         Returns a list of positi, Query Angel One for available intraday margin.          Returns the usable intra, Place an order based on a signal.          After placing and confirming fill:, Push an open position to Firebase.         The OpenPositions component shows liv

### Community 16 - "Community 16"
Cohesion: 0.17
Nodes (7): Poll India VIX via Yahoo Finance every 5 minutes.          Why: Angel One WebSoc, DataStream, Stop streaming and close the WebSocket. Waits for thread to exit., Called when WebSocket connection is established.         This is where we tell A, Called when a WebSocket error occurs., Called when the WebSocket connection closes., Manages the real-time price stream from Angel One WebSocket.      Flow:     1. s

### Community 17 - "Community 17"
Cohesion: 0.21
Nodes (6): Read the entire CSV and compute all-time performance stats.         Called at en, Same as get_summary() but filtered to today's trades only., Per-strategy performance.          Returns something like:         {, Counts how many trades were taken at each score range.          Use this to tune, Read all rows from the CSV file., Read only today's trades from the CSV.

### Community 18 - "Community 18"
Cohesion: 0.22
Nodes (5): Sector Analysis — Relative Strength & Rotation Classification. =================, Sector relative strength result., Fetch sector data and classify each sector's rotation phase.          Returns:, Fetch 2 months of daily data and compute 1-month return., SectorStrength

### Community 19 - "Community 19"
Cohesion: 0.32
Nodes (4): useFirebase(), useFirebaseList(), useTradeData(), App()

### Community 20 - "Community 20"
Cohesion: 0.33
Nodes (3): Distribute VIX value to all components that need it., Update current VIX value for pre-flight checklist., Update India VIX (called when VIX tick arrives).

### Community 21 - "Community 21"
Cohesion: 0.2
Nodes (3): Risk Manager — The Guardian of Your Capital (Sniper Mode V2) ===================, Update current VIX value for position sizing decisions., Record that we have an open position in this stock.

### Community 22 - "Community 22"
Cohesion: 0.33
Nodes (4): OptionSignal, NIFTY/BANKNIFTY Options Strategy — ORB-Based Option Buying. ====================, Check for NIFTY ORB breakout + retest → option buy signal.          Args:, Signal to buy a NIFTY/BANKNIFTY option.

### Community 23 - "Community 23"
Cohesion: 0.33
Nodes (2): Reset for new trading day., Called during 9:15-9:30 to track index ORB range.

### Community 24 - "Community 24"
Cohesion: 0.5
Nodes (2): Called every time a new price tick arrives from Angel One.          The message, Convert Angel One's raw WebSocket message into our standard tick format.

### Community 25 - "Community 25"
Cohesion: 0.5
Nodes (3): Logging configuration for the trading bot., Configure logging to both console and file., setup_logger()

### Community 26 - "Community 26"
Cohesion: 0.67
Nodes (1): Data Stream — Real-time Price Data via Angel One WebSocket =====================

### Community 27 - "Community 27"
Cohesion: 1.0
Nodes (1): Trade Analytics — CSV logging and performance analysis. ========================

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

## Knowledge Gaps
- **228 isolated node(s):** `Configuration for the trading bot. All settings in one place. Reads secrets from`, `Angel One SmartAPI credentials.`, `Firebase connection settings.`, `News sentiment API settings (Marketaux free tier: 100 req/day).`, `Core trading parameters.` (+223 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **Thin community `Community 23`** (4 nodes): `.reset_daily()`, `.update_orb_range()`, `Reset for new trading day.`, `Called during 9:15-9:30 to track index ORB range.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 24`** (4 nodes): `._on_data()`, `._parse_tick()`, `Called every time a new price tick arrives from Angel One.          The message`, `Convert Angel One's raw WebSocket message into our standard tick format.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 26`** (3 nodes): `data_stream.py`, `Data Stream — Real-time Price Data via Angel One WebSocket =====================`, `# IMPORTANT: pass a COPY of the tokens list. SmartWebSocketV2.subscribe()`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 27`** (2 nodes): `trade_analytics.py`, `Trade Analytics — CSV logging and performance analysis. ========================`
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

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `Signal` connect `Community 0` to `Community 1`, `Community 2`, `Community 3`, `Community 4`, `Community 7`, `Community 8`, `Community 13`, `Community 15`, `Community 20`, `Community 21`?**
  _High betweenness centrality (0.190) - this node is a cross-community bridge._
- **Why does `PatternScanner` connect `Community 2` to `Community 0`, `Community 4`, `Community 6`, `Community 7`, `Community 8`, `Community 9`, `Community 12`, `Community 15`, `Community 16`, `Community 20`?**
  _High betweenness centrality (0.168) - this node is a cross-community bridge._
- **Why does `BrokerConnection` connect `Community 1` to `Community 2`, `Community 4`, `Community 6`, `Community 7`, `Community 8`, `Community 9`, `Community 12`, `Community 15`, `Community 16`, `Community 20`?**
  _High betweenness centrality (0.144) - this node is a cross-community bridge._
- **Are the 126 inferred relationships involving `Signal` (e.g. with `Position` and `OrderManager`) actually correct?**
  _`Signal` has 126 INFERRED edges - model-reasoned connections that need verification._
- **Are the 38 inferred relationships involving `PatternScanner` (e.g. with `TradingBot` and `NSE Intraday Trading Bot -- Main Entry Point ===================================`) actually correct?**
  _`PatternScanner` has 38 INFERRED edges - model-reasoned connections that need verification._
- **Are the 56 inferred relationships involving `VWAPBounceStrategy` (e.g. with `BacktestPosition` and `BacktestTrade`) actually correct?**
  _`VWAPBounceStrategy` has 56 INFERRED edges - model-reasoned connections that need verification._
- **Are the 56 inferred relationships involving `SRBreakoutStrategy` (e.g. with `BacktestPosition` and `BacktestTrade`) actually correct?**
  _`SRBreakoutStrategy` has 56 INFERRED edges - model-reasoned connections that need verification._