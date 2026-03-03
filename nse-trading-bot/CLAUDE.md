# NSE Intraday Trading Bot — Project Context

## What This Project Is

An automated intraday trading system for the Indian stock market (NSE).
It has two parts:

1. **Python Backend** (`/backend`) — Runs on the user's laptop during market hours (9:15 AM – 3:30 PM IST). Connects to Angel One SmartAPI, streams real-time price data, detects technical patterns, manages risk, and places/exits trades automatically.

2. **React Dashboard** (`/dashboard`) — Hosted on GitHub Pages. The user's control panel — shows live signals, open positions, P&L, and trade history. Reads real-time data from Firebase (the backend pushes updates there).

## Architecture Overview

```
Angel One SmartAPI (broker)
        │
        ▼
┌──────────────────────┐
│   Python Backend     │  ← Runs on user's laptop
│   (pattern engine,   │
│    risk manager,     │
│    order executor)   │
└──────┬───────────────┘
       │ pushes updates
       ▼
┌──────────────────────┐
│   Firebase Realtime  │  ← Free tier, acts as data bridge
│   Database           │
└──────┬───────────────┘
       │ reads in real-time
       ▼
┌──────────────────────┐
│   React Dashboard    │  ← GitHub Pages (static site)
│   (user interface)   │
└──────────────────────┘
```

## Current Phase

**Phase 1 — Foundation**
- [ ] Dashboard UI (React, GitHub Pages)
- [ ] Pattern engine with sample data
- [ ] Firebase integration

**Phase 2 — Live Data**
- [ ] Angel One SmartAPI connection
- [ ] Real-time WebSocket streaming
- [ ] Live pattern detection

**Phase 3 — Auto-Execution**
- [ ] Order placement via API
- [ ] Stop-loss and target monitoring
- [ ] Kill switch and safety limits

## User Profile

- **Experience**: Beginner in both Python and trading
- **Capital**: ₹1,000 (with ~5× intraday margin = ₹5,000 buying power)
- **Broker**: Angel One (SmartAPI — free API access)
- **Hosting**: Laptop for backend, GitHub Pages for dashboard
- **Goal**: Learn algorithmic trading with real but minimal risk

## Tech Stack

### Backend (`/backend`)
- Python 3.10+
- `smartapi-python` — Angel One broker API
- `websocket-client` — real-time price streaming
- `pandas`, `numpy` — data manipulation
- `pandas-ta` — technical indicators (EMA, RSI, VWAP, etc.)
- `firebase-admin` — push data to Firebase
- `python-dotenv` — environment variable management
- `schedule` — task scheduling

### Dashboard (`/dashboard`)
- React 18 (Vite build)
- Firebase Realtime Database SDK
- Tailwind CSS for styling
- Recharts for charts
- Hosted on GitHub Pages via `gh-pages` package

### Data Bridge
- Firebase Realtime Database (free Spark plan)
- Backend WRITES → Firebase ← Dashboard READS

## Key Design Decisions

1. **Rule-based strategies, NOT machine learning.** Strategies are explicit if/else logic based on proven technical patterns. No training data needed. ML is overkill for this stage and more likely to lose money.

2. **"Suggest first, execute later" approach.** Start in suggestion-only mode. Auto-execution is Phase 3, only enabled after 1 month of paper trading.

3. **Risk management is non-negotiable.** Every trade must have a stop-loss. Max 1-2% capital risk per trade. Daily loss limit of 3% — bot stops if hit. Max 3 trades per day.

4. **Commissions matter at ₹1K capital.** The bot must factor in ~₹25-40 round-trip cost per trade. It should skip trades where expected profit doesn't justify the cost.

5. **Market context awareness.** Never go long when NIFTY is falling hard. Never go short when NIFTY is rallying. The bot checks index direction before every signal.

## Coding Conventions

- **Python**: Use type hints everywhere. Dataclasses for data structures. Logging (not print) for all output. Config via `.env` file and `config.py`.
- **React**: Functional components with hooks. Tailwind for styling. No localStorage (not supported in artifacts). Keep components small and focused.
- **Error handling**: Every API call wrapped in try/except. Every WebSocket message validated. Graceful degradation — if Firebase is down, bot still trades; if broker API hiccups, bot retries 3x then skips.
- **Security**: API keys NEVER in code. Always in `.env` (gitignored). Firebase security rules restrict write access.

## File Structure

```
nse-trading-bot/
│
├── CLAUDE.md                    ← YOU ARE HERE (project context)
├── README.md                    ← Setup instructions for the user
├── .gitignore                   ← Ignores .env, __pycache__, node_modules
│
├── backend/
│   ├── main.py                  ← Entry point — starts the bot
│   ├── config.py                ← All configuration (reads from .env)
│   ├── .env.example             ← Template for API keys
│   │
│   ├── core/
│   │   ├── __init__.py
│   │   ├── broker.py            ← Angel One SmartAPI connection
│   │   ├── data_stream.py       ← WebSocket real-time data handler
│   │   ├── scanner.py           ← Scans watchlist, detects patterns
│   │   ├── risk_manager.py      ← Position sizing, daily limits
│   │   ├── order_manager.py     ← Places and monitors orders
│   │   └── portfolio.py         ← Tracks positions and P&L
│   │
│   ├── strategies/
│   │   ├── __init__.py
│   │   ├── base_strategy.py     ← Abstract base class for strategies
│   │   ├── orb_strategy.py      ← Opening Range Breakout
│   │   ├── vwap_strategy.py     ← VWAP Mean Reversion
│   │   └── ema_strategy.py      ← EMA Crossover
│   │
│   ├── utils/
│   │   ├── __init__.py
│   │   ├── firebase_sync.py     ← Push updates to Firebase
│   │   ├── watchlist.py         ← Stock watchlist management
│   │   ├── indicators.py        ← Technical indicator calculations
│   │   └── logger.py            ← Logging configuration
│   │
│   └── requirements.txt         ← Python dependencies
│
├── dashboard/
│   ├── package.json
│   ├── vite.config.js
│   ├── index.html
│   ├── tailwind.config.js
│   │
│   └── src/
│       ├── App.jsx              ← Main app with routing
│       ├── main.jsx             ← Entry point
│       ├── firebase.js          ← Firebase config
│       │
│       ├── components/
│       │   ├── CapitalInput.jsx     ← Enter starting capital
│       │   ├── LiveSignals.jsx      ← Current pattern signals
│       │   ├── OpenPositions.jsx    ← Active trades with live P&L
│       │   ├── TradeHistory.jsx     ← Past trades log
│       │   ├── PerformanceCard.jsx  ← Daily P&L summary
│       │   ├── MarketContext.jsx    ← NIFTY direction indicator
│       │   ├── StrategyBreakdown.jsx← Which strategies are winning
│       │   └── KillSwitch.jsx       ← Emergency stop button
│       │
│       ├── hooks/
│       │   ├── useFirebase.js       ← Real-time Firebase listener
│       │   └── useTradeData.js      ← Trade data state management
│       │
│       └── utils/
│           ├── calculations.js      ← P&L, position size helpers
│           └── formatters.js        ← Currency, time formatting
│
└── docs/
    ├── ARCHITECTURE.md          ← Detailed system design
    ├── STRATEGIES.md            ← Strategy logic documentation
    ├── API_SETUP.md             ← Angel One API setup guide
    └── FIREBASE_SETUP.md        ← Firebase configuration guide
```

## Watchlist (Default — NIFTY 50 liquid stocks)

The bot scans these by default. All are high-volume, liquid stocks suitable for intraday:
RELIANCE, TCS, HDFCBANK, INFY, ICICIBANK, HINDUNILVR, SBIN, BHARTIARTL,
ITC, KOTAKBANK, LT, AXISBANK, ASIANPAINT, MARUTI, TATAMOTORS, SUNPHARMA,
TITAN, BAJFINANCE, WIPRO, HCLTECH, TATASTEEL, NTPC, POWERGRID, ONGC,
JSWSTEEL, ADANIENT, TECHM, ULTRACEMCO, INDUSINDBK, NESTLEIND

## Trading Hours & Bot Schedule

- **9:00 AM** — Bot starts, authenticates with Angel One, loads watchlist
- **9:15 AM** — Market opens, WebSocket stream begins
- **9:15–9:30** — Opening Range period (watch only, no trades)
- **9:30–2:30 PM** — Active scanning and trading window
- **2:30 PM** — No new trades after this
- **3:15 PM** — Force-exit all open positions
- **3:30 PM** — Market closes, bot generates daily report, pushes to Firebase

## Safety Rules (HARDCODED — never override)

1. Every trade MUST have a stop-loss. No exceptions.
2. Max risk per trade: 2% of current capital.
3. Max trades per day: 3.
4. Daily loss limit: 3% of starting capital. Bot stops if hit.
5. No trading in first 15 minutes (opening range observation).
6. No new trades after 2:30 PM.
7. All positions closed by 3:15 PM.
8. Kill switch on dashboard immediately cancels all orders and exits positions.
