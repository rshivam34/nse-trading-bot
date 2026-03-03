# System Architecture

## Data Flow

```
┌─────────────────────────────────────────────────────────────┐
│                    MARKET HOURS (9:15 AM - 3:30 PM)          │
│                                                              │
│  Angel One ──WebSocket──► DataStream ──ticks──► Scanner     │
│                                                    │         │
│                                         ┌──────────┘         │
│                                         ▼                    │
│                                   ORB Strategy               │
│                                   VWAP Strategy              │
│                                   EMA Strategy               │
│                                         │                    │
│                                    Signal?                   │
│                                    ╱    ╲                    │
│                                 Yes      No                  │
│                                  │       └─ continue scan    │
│                                  ▼                           │
│                           Risk Manager                       │
│                           (can trade? position size?)         │
│                                  │                           │
│                            Approved?                         │
│                            ╱      ╲                          │
│                         Yes        No                        │
│                          │         └─ log & skip             │
│                          ▼                                   │
│                    Order Manager                             │
│                    (place order, monitor SL/target)           │
│                          │                                   │
│                          ▼                                   │
│                    Firebase Sync ──push──► Firebase DB        │
│                                               │              │
│                                               ▼              │
│                                        React Dashboard       │
│                                        (GitHub Pages)        │
└─────────────────────────────────────────────────────────────┘
```

## Component Responsibilities

| Component | File | Role |
|-----------|------|------|
| **main.py** | `backend/main.py` | Orchestrates everything, runs the main loop |
| **BrokerConnection** | `core/broker.py` | Authenticates and communicates with Angel One |
| **DataStream** | `core/data_stream.py` | Receives real-time price ticks via WebSocket |
| **PatternScanner** | `core/scanner.py` | Runs all strategies against incoming data |
| **RiskManager** | `core/risk_manager.py` | Enforces safety rules, sizes positions |
| **OrderManager** | `core/order_manager.py` | Places orders, monitors SL/target, exits |
| **Portfolio** | `core/portfolio.py` | Tracks capital, P&L, generates reports |
| **FirebaseSync** | `utils/firebase_sync.py` | Pushes live data to Firebase for dashboard |
| **Strategies** | `strategies/*.py` | Pattern detection logic (ORB, VWAP, EMA) |

## Build Phases

### Phase 1: Foundation (Current)
- Dashboard UI with mock data
- Pattern engine running on sample data
- No real broker connection

### Phase 2: Live Data
- Real Angel One WebSocket connection
- Live pattern detection on market data
- Firebase bridge working
- Dashboard shows real signals

### Phase 3: Auto-Execution
- Order placement through Angel One
- Real stop-loss and target monitoring
- Kill switch functional
- Paper trading validation (1 month)

### Phase 4: Optimization
- Add VWAP and EMA strategies
- Performance analytics
- Strategy parameter tuning
- Consider basic ML confidence scoring
