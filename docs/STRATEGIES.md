# Trading Strategies Documentation

## Strategy 1: Opening Range Breakout (ORB) — PRIMARY

**Status**: Implemented  
**File**: `backend/strategies/orb_strategy.py`

### How It Works
1. **9:15–9:30 AM**: Record the HIGH and LOW of first 15 minutes
2. **After 9:30**: Watch for price to break above HIGH or below LOW
3. **LONG setup**: Price > ORB High + buffer → BUY
4. **SHORT setup**: Price < ORB Low - buffer → SELL
5. **Stop Loss**: Opposite end of the range
6. **Target**: Entry + (range × 1.5)

### Filters
- ORB range must be 0.3%–2.0% of price (skip if too narrow or too wide)
- NIFTY must not be moving against the trade direction
- Volume must be above minimum threshold

### Example
```
ORB High: ₹500 | ORB Low: ₹495 | Range: ₹5 (1.0%)
LONG Entry: ₹500.25 (high + buffer)
Stop Loss: ₹495
Target: ₹507.75 (entry + 5 × 1.5)
Risk: ₹5.25 per share | Reward: ₹7.50 per share
```

---

## Strategy 2: VWAP Mean Reversion — PLANNED (Phase 2)

**Status**: Stub only  
**File**: `backend/strategies/vwap_strategy.py`

### Concept
Trade bounces off VWAP in trending stocks. When a stock is trending above VWAP and pulls back to touch it, buy the bounce.

---

## Strategy 3: EMA Crossover — PLANNED (Phase 2)

**Status**: Stub only  
**File**: `backend/strategies/ema_strategy.py`

### Concept
When 9-period EMA crosses above 21-period EMA, go long. When it crosses below, go short.

---

## Adding New Strategies

1. Create a new file in `backend/strategies/`
2. Inherit from `BaseStrategy` (in `base_strategy.py`)
3. Implement `check_signal()` method
4. Return a `Signal` object with entry, SL, target, and reason
5. Register the strategy in `scanner.py`'s `__init__` method
