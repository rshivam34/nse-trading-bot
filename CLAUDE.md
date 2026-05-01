# NSE Intraday Trading Bot — Project Context

> Last updated: 2026-05-01 (rework session). This file is rewritten directly from the live code (`config.py`, `scanner.py`, `risk_manager.py`, `order_manager.py`, `options_manager.py`, all 4 active strategy files) to replace stale Sniper Mode V1/V2 sections that no longer matched the codebase.

---

## LAUNCH 2026-05-02 — Manual Live F&O Trading at Rs.30K

User decided to launch live with manual control rather than auto-scheduling.

**Final operational setup:**
- **Capital: Rs.30,000** (starting smaller, may scale to Rs.50K-Rs.1L after live validation)
- **Mode: F&O-only LIVE** (`PAPER_TRADING=False`, `equity_enabled=False`)
- **Auto-scaling lots: enabled** — 25% of capital per position
- **Scheduled task: REMOVED** (user prefers manual control)
- **Desktop launcher: `C:\Users\rshiv\OneDrive\Desktop\NSE-Bot-Launch.bat`**
- **First live trading day: Monday May 4, 2026** (when user double-clicks the launcher)

**Important — IP whitelist gotcha:**
Angel One whitelists by IP for ALL endpoints (auth, orders, market data, WebSocket).
Current Primary IP: `49.32.238.63` (Jio mobile, dynamic — will change).
When AG8004 errors appear in future logs, update Primary IP at https://smartapi.angelone.in/.
For office/home dual-use, add Secondary Static IP.

**12-month validated backtest results (Apr 2025 - Apr 2026 with real Angel One 5-min data):**

| Capital | Trades | Win % | Net P&L | Return | PF |
|---|---|---|---|---|---|
| Rs.30K | 48 | 58% | +Rs.23,768* | ~+79% | 1.70 |
| Rs.50K | 48 | 58% | +Rs.39,613 | +79.23% | 1.70 |
| Rs.75K | 48 | 58% | +Rs.60,949 | +81.26% | 1.68 |
| Rs.1L | 48 | 58% | +Rs.83,727 | +83.73% | 1.67 |

*Rs.30K projection from Rs.50K data (60% scaled — 1-2 lots fewer per trade)

**Mar/Apr 2026 (war/crisis): 0 F&O trades — VIX > 18 on 95% of days. Bot correctly stayed in cash.**

Realistic real-world expectation (after slippage haircut): **+30-50% annualized** at Rs.30K.

## Previous: REWORK 2026-05-02 (F&O-ONLY MODE)

After backtesting both systems and the delivery bot at Rs.30K/Rs.50K/Rs.1L, decided to:
1. **Disable equity scanner entirely** (`equity_enabled = False`)
2. **Allocate full Rs.50K to F&O** (was Rs.21K with 70/30 split)
3. **Pause the delivery bot** (it's profitable but at +2-4%/year vs intraday F&O's higher upside)
4. **Run intraday in F&O-only paper mode** until proven profitable, then go live

Comparison data that drove the decision:

| Strategy | Rs.50K capital | Period | Result |
|---|---|---|---|
| Delivery bot (with bug fix) | Rs.50K | 14 months | **+3.77%** (+Rs.1,886) |
| Delivery bot (with bug fix) | Rs.50K | 6 months war | **+2.62%** (+Rs.1,312) |
| Intraday equity | Rs.50K | 60-day war | -0.11% (1 trade -Rs.53) |
| Intraday F&O | Rs.50K | 60-day war | 0% (0 trades, VIX too high) |
| Intraday F&O (relaxed VIX test) | Rs.30K | 2 weeks Apr | +Rs.629 (1 NIFTY trade +Rs.633) |

12-month true intraday backtest is NOT possible via yfinance (60-day 5-min limit). The 60-day window happens to be all war/crisis. Real edge will only show in normal-VIX months (Nov 2025 - Feb 2026 was VIX 9-15 — bot would have been very active, but no backtest data).

## Previous: REWORK 2026-05-01

Session goals: rework toward options-primary at Rs.30K capital, fix F&O execution bug, set up Windows Task Scheduler for daily auto-paper-trading.

### What changed

1. **Capital raised to Rs.30K** (`.env: INITIAL_CAPITAL=30000`)
2. **Mode flipped to PAPER by default** (`.env: PAPER_TRADING=True`) — REAL orders disabled until you flip back
3. **Options-primary capital split**: F&O Rs.21K (70%), Equity Rs.9K (30%)
4. **Equity-disable toggle added**: `config.equity_enabled` — set False to run options-only
5. **F&O daily limit raised**: 2 → 4 trades (was hardcoded in `options_manager.py`, now reads `config.options_max_trades_per_day`)
6. **F&O premium cap raised**: Rs.500 → Rs.700 (BANKNIFTY needs higher)
7. **CRITICAL F&O BUG FIXED**: `broker._lookup_option_token` was importing a non-existent function `get_instrument_master` from `utils.watchlist` — every options token lookup raised ImportError silently swallowed by try/except, so NO F&O trade ever placed an order despite `options_enabled=True`. Fixed to read instrument master JSON directly from `logs/scrip_master.json` cache (downloads if missing). User confirmed: F&O was never tested live, only via backtest, so this is a forward fix not a regression.
8. **Windows Task Scheduler set up**: Daily 8:55 AM auto-launch in paper mode. Task name: `NSE-IntradayBot-Paper`. Uses `start_bot_paper.bat` wrapper.
9. **GitHub backup**: `origin = git@github-studytimer:rshivam34/nse-trading-bot.git`. All rework commits pushed.

### Why options-primary

Empirical evidence:
- 2-week relaxed-VIX backtest: equity -Rs.4 (2 trades), options +Rs.633 (1 trade)
- 12 March 2026 live equity trades: ~-Rs.700 net (charges + losses)
- F&O bug meant zero options trades fired live (hidden zero) — but backtest shows the strategy *would* work
- At Rs.15K-30K capital, equity per-trade max gain (~Rs.225) is ~2× round-trip charges (Rs.30-50). F&O premium movement is asymmetric — same effort, much better R/R

### Why VIX cutoff stays at 18

User's deliberate choice. 6-month VIX history (Nov 2025 - Apr 2026):
- Nov-Feb: VIX 9-15 → 80 of 80 days tradeable
- Mar-Apr: VIX 17-28 (war/crisis) → 5 of 39 days tradeable
- Total: 85 of 119 days (71%) at VIX < 18

The Mar-Apr crisis is the OUTLIER, not the rule. Cutoff at 18 protects from crisis whipsaw (March's 12 live trades = -Rs.700 net) while not blocking normal markets. Historical March 2026 SHORTs at VIX 22-26 were unanimously losers; user is correct to stay out.

### How to start trading

**Paper mode (auto-runs daily at 8:55 AM via Task Scheduler):**
```powershell
# Already set up. Verify with:
Get-ScheduledTask -TaskName "NSE-IntradayBot-Paper"
```
The bot self-skips weekends and NSE holidays. Logs go to `backend/logs/trading_bot_YYYY-MM-DD.log`.

**Manual run:**
```powershell
cd C:\Users\rshiv\nse-trading-bot\backend
python main.py --paper       # paper mode (default in .env)
python main.py --live        # LIVE — REAL money
```

**Options-only mode:** edit `config.py` line ~325 → `equity_enabled: bool = False`

**Disable Task Scheduler auto-run:**
```powershell
Unregister-ScheduledTask -TaskName "NSE-IntradayBot-Paper" -Confirm:$false
```

### Going-live checklist (DO NOT SKIP)

The Windows Task Scheduler runs **paper mode only** (`--paper` flag in `start_bot_paper.bat`). It will never place real orders, even if `.env: PAPER_TRADING=True` is flipped.

Before going live with real money:

1. **Run paper mode for at least 2 full trading weeks (10 trading days minimum).**
2. Validate during paper period:
   - F&O signals are actually firing (most critical — bug was just fixed today, never tested live)
   - Equity scoring rejects most signals (expected — sniper mode)
   - Daily loss limit gates work (3% = Rs.900 at Rs.30K)
   - Force-exit at 3:15 PM closes all positions
3. **Review every paper trade in `backend/logs/trades.csv`** — confirm signal logic matches what you expect
4. Only after 2 weeks of clean paper data:
   - Edit `start_bot_paper.bat` → change `--paper` to `--live`
   - **OR** edit `.env: PAPER_TRADING=False`
   - **Start with Rs.10,000, NOT the full Rs.30K** — scale up only after 4 profitable weeks

### Controls available (ask Claude or run yourself)

| Action | Command |
|---|---|
| Pause auto-run | `Disable-ScheduledTask -TaskName "NSE-IntradayBot-Paper"` |
| Resume auto-run | `Enable-ScheduledTask -TaskName "NSE-IntradayBot-Paper"` |
| Remove auto-run | `Unregister-ScheduledTask -TaskName "NSE-IntradayBot-Paper" -Confirm:$false` |
| Run once manually | Double-click `start_bot_paper.bat` |
| Switch to live mode | Edit `.env: PAPER_TRADING=False` (after 2-week paper test) |
| Stop running bot | Close terminal window, or Ctrl+C in it, or kill the python process |

---

---

## What This Project Is

An automated intraday trading system for the Indian stock market (NSE). It actually contains **TWO independent trading systems running inside one bot process**:

| System | What it trades | Manager class |
|---|---|---|
| **A. Equity Intraday** | NIFTY 200 stocks, MIS leveraged | `core/order_manager.py` |
| **B. Index Options (F&O)** | NIFTY + BANKNIFTY weekly ATM options | `core/options_manager.py` |

Both share the same Angel One auth, kill switch, force-exit timer (3:15 PM), and VIX gate — but their entry pipelines, position sizing, exits, and trade-count limits are completely separate.

**Two parts:**
1. **Python Backend** (`/backend`) — Runs on user's laptop during market hours. Angel One SmartAPI for orders, WebSocket for live ticks, REST polling for VIX (Yahoo Finance fallback).
2. **React Dashboard** (`/dashboard`) — GitHub Pages, reads real-time data from Firebase. Shows signals, positions, P&L, trade history. Has kill switch + trading enable/disable toggle.

## Architecture

```
Angel One SmartAPI ──► Python Backend ──► Firebase Realtime DB ──► React Dashboard
  (broker)              (this bot)         (data bridge)            (GitHub Pages)
```

---

## Capital & Mode

- **Initial capital:** Rs.15,000 (set in `.env: INITIAL_CAPITAL`, default 15000)
- **Effective buying power:** ~Rs.60,000 (cash × 4× MIS leverage estimate)
- **Mode toggles** (in `.env`):
  - `PAPER_TRADING=True/False` — paper vs live
  - `SUGGEST_ONLY=True/False` — log signals without executing
- **CLI overrides:** `python main.py --live` or `--paper`

---

## SYSTEM A: Equity Intraday (4 active strategies)

### Active strategies (loaded in `scanner.py:71-76`)
1. **ORB** (`orb_strategy.py`) — Opening Range Breakout with retest confirmation
2. **VWAP_BOUNCE** (`vwap_strategy.py`) — VWAP support/resistance bounce
3. **EMA_CROSS** (`ema_strategy.py`) — 9/21 EMA crossover on completed candles
4. **SR_BREAKOUT** (`sr_breakout_strategy.py`) — Prev day H/L/C + 5-day swing breakouts

> The folder also contains `vwap_reversion_strategy.py` and `options_strategy.py` — these are **NOT loaded by the live scanner**. The first is used only by the backtest; the second is referenced by `options_manager.py` indirectly (the options manager reimplements its own ORB-retest state machine for live trading).

### Each strategy's exact entry rules

| Strategy | Trigger | SL | Target | Time window |
|---|---|---|---|---|
| **ORB** | 9:15-9:30 range size 0.5%-2% → previous **completed candle close** past range + 0.15% buffer (state: BREAKOUT) → price pulls back within 0.2% of broken edge (state: RETESTING) → next completed candle closes back past edge as green/red with ≥1.5× volume | Opposite ORB edge | 1.5× range width | **9:30 – 10:15 only** |
| **VWAP_BOUNCE** | Stock above (or below) VWAP for ≥6 completed candles → 2-candle bounce: prev candle touched within 0.3% of VWAP and closed across as green/red, current candle confirms same direction → volume ≥ 1.5× avg → RSI not >75 (LONG) / <25 (SHORT) → sector not LAGGING/WEAKENING | 0.4% beyond VWAP | max(swing high/low, 1.5R) | **9:30 – 11:30 only** |
| **EMA_CROSS** | EMA9 crosses EMA21 on completed candles (not ticks) → separation ≥ 0.15% (filters noise) → volume ≥ 20-candle avg → RSI 30-70 → price on correct side of VWAP | Recent 10-candle low/high × 0.998 (LONG) / 1.002 (SHORT) | 1.5R | No cutoff |
| **SR_BREAKOUT** | Price > 0.1% past prev day H/L/C or 5-day swing → volume ≥ 2.0× last completed candle vs 20-candle avg → NIFTY direction not opposite → on correct side of VWAP | 1% inside broken level | next key level OR 1.5R, whichever further | No cutoff (only 1× per stock per level per day) |

All four require: NIFTY direction not opposite, gap < 1.5%, no signal yet on this stock today.

### The full equity scan pipeline (`scanner.py:scan` line 317)

For every stock tick after 9:30 AM:

```
1. Skip if already signaled this stock today
2. Skip if news flagged stock (skip_today)
3. Skip if earnings this week
4. Build 5-min candles from ticks (OHLCV)
5. Build context (VWAP, RSI, EMA9/21, RVOL, ADV, gap%)
6. Run ALL 4 strategies → collect raw signals
7. Pick highest-confidence signal (NO confluence requirement — Option C)
8. Compute ATR(14), Choppiness, 15m trend

   FILTER CHAIN — any failure = REJECT:
9.  VIX > 18 .................. SKIPPED-VIX-GATE
10. Stock Choppiness > 70 ...... SKIPPED-CHOPPY
11. NIFTY Choppiness > 70 ...... SKIPPED-CHOPPY
12. 15-min trend opposite ...... DISABLED in config (trend_15m_enabled=False)
13. Breakout candle didn't close
    past level (ORB/SR only) ... SKIPPED-NO-CANDLE-CLOSE

14. Score the signal (signal_scorer.py — 14 factors, see below)

    SCORE MODIFIERS:
15. ATR compressing? → -10 OR HARD REJECT for ORB/SR_BREAKOUT
16. RVOL <1×: -10  |  1-2×: -5  |  ≥3×: +5
17. VWAP_BOUNCE at VIX > 18: -15 (rarely fires — VIX>18 already blocks)
18. After 12:00, NIFTY exhausted (40%+ giveback): -15
19. After 14:00: -5

20. Score < 80? → SKIPPED-LOW-SCORE
21. Recalculate SL/target using ATR (overrides what strategy set)
22. Mark signal QUALIFIED → main.py executes pipeline
```

### Risk manager gate (`risk_manager.py:can_trade` line 201)

After scanner returns a qualified signal, this runs before the order is placed:

```
Rule 1:  trades_today < min(5, stance_max_trades)            # HARD daily cap
Rule 2:  losses_today < 3                                     # max losses today
Rule 3:  daily_pnl > -3% of starting capital                  # daily loss limit
Rule 4:  current time <= 13:00                                # no_new_trades_after
Rule 5:  in trading window (9:30-13:00)
Rule 6:  not in 15-min consecutive-loss cooldown (after 2 in a row)
Rule 6b: ≥10 min since last entry (entry spacing — prevents correlated bets)
Rule 7:  not already in position on this stock
Rule 7b: not in 15-min re-entry cooldown for this stock
Rule 8:  signal has stop-loss
Rule 9:  signal RR ≥ 1.0
Rule 10: position size > 0 after VIX/stance/regime scaling
Rule 11: capital deployed < 80% of broker margin
Rule 12: expected net profit > Rs.15 (or Rs.8/Rs.12 if capital < Rs.5K/2K)
```

### Pre-flight checklist (`order_manager.py:pre_flight_check` line 426)

After risk manager passes, this 17-point check runs:

| # | Check | Source |
|---|---|---|
| 1 | Score ≥ 80 | config.min_score_to_trade |
| 2 | Scanner pipeline passed (informational) | always pass — confluence removed |
| 3 | RVOL informational | always pass — score modifier handles it |
| 4 | VIX ≤ 18 | re-check at order time |
| 5 | Lunch flag (informational) | always pass |
| 6 | trades_today < 5 | risk manager |
| 7 | losses_today < 3 | risk manager |
| 8 | Stock CHOP ≤ 70 | scanner-set on signal |
| 9 | NIFTY CHOP ≤ 70 | scanner market context |
| 10 | 15m trend aligned | DISABLED (trend_15m_enabled=False) |
| 11 | Candle close confirmed | pre-verified in scanner |
| 12 | SL distance 1.0%-1.5% | ATR floor/ceiling |
| 13 | Risk within limits | always pass |
| 14 | Capital deployed < 80% | risk manager |
| 15 | Not in re-entry cooldown | risk manager |
| 16 | Time 9:30-13:00 | window check |
| 17 | Estimated net profit > Rs.15 | brokerage calculator |

### Scoring breakdown (`signal_scorer.py`)

A signal must score **≥80/100** to execute. 14 factors:

| Factor | Max | Trigger |
|---|---|---|
| ORB strategy | +15 | strategy_name == "ORB" |
| VWAP aligned | +15 | LONG above VWAP / SHORT below |
| Volume spike | +20 (≥5×) or +10 (≥2×) | RVOL |
| RSI 30-70 | +10 | not extreme |
| NIFTY aligned | +15 (or +8 if NEUTRAL) | direction matches |
| EMA aligned | +10 | EMA9 vs EMA21 matches direction |
| vs prev close | +5 | LONG above / SHORT below |
| News sentiment | +10 (or +4 if neutral) | matches direction |
| Away from prev levels | +5 | not within 0.3% of prev H/L/C |
| Time bonus | +5 | 9:30-11:30 or 13:00-14:30 |
| Low VIX | +5 (or +3 if no data) | VIX < 15 |
| **Macro aligned** | +10 / -10 | NIFTY 50/200 DMA trend matches |
| **Sector aligned** | +5 / -5 | LEADING/IMPROVING vs LAGGING/WEAKENING |
| **Fundamental** | -10 + ±5 | red flag (ROE<10%, D/E>2, EPS<0) + PE vs sector |

Total capped at 100. Score 80+ = "EXCELLENT", 90+ = "EXCEPTIONAL".

### Execution flow (`order_manager.py:execute` line 591)

1. Margin check — reduce qty if needed
2. Place LIMIT order (3 retries, 2s/4s backoff)
3. Poll fill status (3 checks, 1s apart)
4. If filled: place broker-side STOPLOSS-LIMIT order (exchange-level safety net)
5. If unfilled after 3s: leaves order pending → `_check_pending_timeouts` either adopts late fill or cancels at 30s

### Position monitoring (`order_manager.py:monitor_positions` line 755)

Runs every second in trading loop. Priority order:

1. Effective SL hit → exit
2. Trailing SL hit → exit
3. After 15:00, position in profit → exit (TIME_PROFIT_EXIT)
4. Partial exit at 1.0R → sell 50%, move SL to breakeven, activate trailing
5. Full target hit (1.5R) → exit
6. Profit management: at +0.5% → SL to breakeven; at +1.5R → activate trailing at 1.5× ATR from peak
7. After 13:00, tighten SL to 1× ATR from current price

---

## SYSTEM B: Index Options (F&O)

Lives in `core/options_manager.py`. Trigger pipe is in `main.py:_on_price_update` lines 880-902 (only fires for NIFTY/BANKNIFTY ticks, not stocks, not VIX).

```
9:15-9:30: track ORB high/low for NIFTY index AND BANKNIFTY (independent state machines)
9:30-10:15: every NIFTY/BANKNIFTY tick →
   ├─ already 2 trades today (1 NIFTY + 1 BANKNIFTY max)? → skip
   ├─ VIX > 18? → skip
   ├─ ORB range too tight (<0.2%) or too wide (>1.5% NIFTY / >3.0% BANK)? → skip
   │
   ├─ State machine on the index itself:
   │    NONE → BREAKOUT (LTP past ORB ± 0.1%)
   │         → RETESTING (LTP back to range edge)
   │         → CONFIRM (next candle bounces away)
   │         → fire signal
   │
   ├─ Build option symbol: NIFTY27MAR2625500CE (next Thursday weekly expiry)
   ├─ Look up token from instrument master
   ├─ Get current premium via LTP API
   ├─ Skip if premium > Rs.500 (config.options_max_premium)
   ├─ Place LIMIT BUY for 1 lot (NIFTY=25, BANKNIFTY=15)
   │
   └─ SL = entry × 0.7 (30% loss), Target = entry × 1.5 (50% gain)

monitoring (every second):
   ├─ premium hit SL → market SELL
   ├─ premium hit target → market SELL
   └─ time ≥ 14:00 → SELL (theta decay protection)
```

### Differences from equity

| | Equity | Options |
|---|---|---|
| Watchlist | NIFTY 200 | NIFTY + BANKNIFTY only |
| Strategies | 4 (ORB, VWAP, EMA, SR) | 1 (ORB retest on index) |
| Direction | LONG/SHORT | CE (CALL) / PE (PUT) |
| Stop-loss | ATR-based, 1.0%-1.5% bound | 30% premium loss |
| Target | 1.5R | 50% premium gain |
| Force exit | 3:15 PM | 2:00 PM (theta) |
| Max trades/day | 5 | 2 (1 NIFTY + 1 BANK) |
| Capital cap per trade | Full ₹15K (with leverage) | min(Rs.5000, 30% of capital) = Rs.4500 |
| Signal entry window | 9:30-13:00 | 9:30-10:15 only |
| Filters | 10+ sniper filters, score ≥ 80 | VIX gate + range size only |
| Pre-flight checks | 17 | None |
| Risk manager gate | Yes | No (uses own counter) |
| Score required | 80 | N/A |

### How to run only one of the two systems

**Run only equity (disable F&O):** Edit `config.py` line 324:
```python
options_enabled: bool = False   # was: True
```
Effect: `main.py:131` sets `self.options_manager = None`. All options checks become no-ops.

**Run only options (disable equity):** Easiest — set `min_score_to_trade = 200` in `config.py` line 78. Scanner still runs but no signal can score 200, so all rejected at score gate. Options run untouched.

---

## Active Configuration (matches code at 2026-05-01)

| Setting | Value | Notes |
|---|---|---|
| `initial_capital` | Rs.15,000 | from .env |
| `max_risk_per_trade_pct` | 1.5% | Rs.225 max risk per trade |
| `max_trades_per_day` | 5 (HARD ceiling, stance can lower) |  |
| `max_losses_per_day` | 3 |  |
| `daily_loss_limit_pct` | 3.0% | Rs.450 max loss/day |
| `max_capital_deployed_pct` | 80% | of broker margin |
| `risk_reward_ratio` | 1.5R | (was 2.5R, lowered — 2.5R rarely hit) |
| `min_score_to_trade` | 80 | (was 70 then 85) |
| `min_confluence_count` | 1 | confluence requirement REMOVED (Option C) |
| `vix_normal_threshold` | 18.0 | VIX < 18 = NORMAL, full size |
| `vix_caution_threshold` | 18.0 | **VIX ≥ 18 = NO TRADES, period** |
| `chop_threshold` | 70.0 | (was 61.8 — too strict for 5-min) |
| `chop_period` | 14 |  |
| `trend_15m_enabled` | False | tick-level data not reliable for 15m |
| `atr_sl_multiplier_normal` | 1.5 | × ATR |
| `atr_sl_floor_pct` | 1.0% | SL never tighter than 1% |
| `atr_sl_ceiling_pct` | 1.5% | SL never wider than 1.5% (very tight!) |
| `partial_exit_enabled` | True |  |
| `partial_exit_rr` | 1.0 | sell 50% at 1.0R |
| `final_exit_rr` | 1.5 | exit rest at 1.5R |
| `breakeven_profit_pct` | 0.5% | move SL to breakeven |
| `trailing_activation_r` | 1.5 | start trailing at 1.5R |
| `trailing_sl_atr_multiplier` | 1.5 | trail at 1.5× ATR from peak |
| `lunch_block_start/end` | 11:30/13:00 | **flag only — NOT a hard block** |
| `no_new_trades_after` | 13:00 | hard cutoff for new entries |
| `force_exit_time` | 15:15 |  |
| `profit_exit_time` | 15:00 | exit any in-profit position |
| `min_entry_spacing_minutes` | 10 | between any two entries |
| `reentry_cooldown_minutes` | 15 | per stock after exit |
| `consecutive_loss_limit` | 2 | trigger 15-min cooldown |
| `consecutive_loss_cooldown_minutes` | 15 |  |
| `intraday_leverage_multiplier` | 4.0 | conservative MIS estimate |
| `min_expected_net_profit` | Rs.15 |  |
| `min_adv_shares` | 500,000 | 5 lakh 20-day avg daily volume |
| `min_candle_traded_value` | Rs.5,00,000 | (informational) |
| `options_enabled` | True |  |
| `options_sl_pct` | 30% | premium loss exit |
| `options_target_pct` | 50% | premium gain exit |
| `options_exit_time` | 14:00 |  |
| `options_max_premium` | Rs.500 | per lot |
| `nifty_lot_size` | 25 |  |
| `banknifty_lot_size` | 15 |  |

### Market stance (from macro analysis)

Set on startup based on NIFTY 50/200 DMA + VIX:

| Stance | Conditions | Max trades | Size % |
|---|---|---|---|
| AGGRESSIVE | VIX < 18 + above both DMAs | 5 | 100% |
| MODERATE | VIX < 18 + above 200 DMA only | 3 | 100% |
| DEFENSIVE | VIX 18-25 OR below 200 DMA | 2 | 50% |
| CASH | VIX ≥ 18 | 0 | 0% |

`max_trades_per_day` is dynamically set to `min(config.max_trades_per_day, stance_max_trades)`.

---

## Trading Day Schedule

```
09:00  Bot starts → auth → getRMS → adopt positions → load watchlist
09:00-09:15  Pre-market: holiday/margin/news/macro/sector/fundamental analysis,
             prev-day OHLC fetch, intraday candle pre-seed
09:15  Market opens → WebSocket streaming begins
09:15-09:30  ORB observation period (track high/low for stocks + indices)
09:30  ACTIVE TRADING starts. Scanner runs on every tick.
09:30-10:15  ORB strategy time-window AND options ORB-retest active
09:30-11:30  VWAP_BOUNCE strategy time-window
10:30  Market regime locked in (TRENDING / VOLATILE / RANGE_BOUND / GAP_DAY)
       → adjusts size_multiplier and SL_multiplier in risk manager
12:00  Momentum exhaustion check activates (NIFTY giveback penalty)
13:00  no_new_trades_after — risk manager rejects all new entries
14:00  Late-afternoon score penalty (-5)
14:00  Options time exit
14:30  (window 2 end — but no new trades anyway)
15:00  profit_exit_time — any open position in profit gets force-closed
15:15  force_exit_time — ALL positions force-closed regardless of P&L
15:30  Market closes. Daily report → Firebase. Volume profiles saved.
```

---

## Architecture Components

### Backend file structure (real, as of 2026-05-01)

```
nse-trading-bot/
├── CLAUDE.md                    ← this file
├── README.md
├── backend/
│   ├── main.py                  ← TradingBot orchestrator (1547 lines)
│   ├── config.py                ← all settings (370 lines)
│   ├── backtest.py              ← yfinance-based backtester (uses ORB + VWAP_REVERSION)
│   ├── backtest_all_months.py
│   ├── core/
│   │   ├── broker.py            ← Angel One SmartAPI wrapper
│   │   ├── data_stream.py       ← WebSocket handler with reconnect
│   │   ├── scanner.py           ← Pattern scanner + filter pipeline (1226 lines)
│   │   ├── signal_scorer.py     ← 0-100 scoring (14 factors)
│   │   ├── risk_manager.py      ← All gates (542 lines)
│   │   ├── order_manager.py     ← Place/monitor/exit + adoption (1408 lines)
│   │   ├── options_manager.py   ← F&O system (415 lines)
│   │   └── portfolio.py         ← P&L tracking
│   ├── strategies/
│   │   ├── base_strategy.py     ← Signal dataclass + BaseStrategy
│   │   ├── orb_strategy.py      ← ACTIVE
│   │   ├── vwap_strategy.py     ← ACTIVE (VWAPBounceStrategy)
│   │   ├── ema_strategy.py      ← ACTIVE
│   │   ├── sr_breakout_strategy.py ← ACTIVE
│   │   ├── vwap_reversion_strategy.py ← INACTIVE in live, used by backtest only
│   │   └── options_strategy.py  ← INACTIVE in live (options_manager.py reimplements)
│   ├── utils/
│   │   ├── indicators.py        ← ATR, Choppiness, EMA, RSI helpers
│   │   ├── volume_profile.py    ← TOD averages + ADV cache
│   │   ├── market_regime.py     ← TRENDING/VOLATILE/RANGE_BOUND/GAP_DAY
│   │   ├── macro_analysis.py    ← NIFTY 50/200 DMA + stance
│   │   ├── sector_analysis.py   ← 9 sector indices, RS scoring
│   │   ├── fundamental_filter.py ← yfinance + screener.in
│   │   ├── news_sentiment.py    ← Marketaux API
│   │   ├── firebase_sync.py     ← all Firebase writes/reads
│   │   ├── watchlist.py         ← 200-stock dynamic loader
│   │   ├── brokerage.py         ← NSE charge calculator
│   │   ├── trade_analytics.py   ← CSV trade log
│   │   ├── rate_limiter.py      ← Token bucket
│   │   ├── ohlc_cache.py        ← Local prev-day cache
│   │   ├── capital_filter.py    ← LTP-based affordability filter
│   │   └── logger.py
│   └── logs/
│       ├── trades.csv
│       ├── volume_profiles.json
│       ├── ohlc_cache.json
│       └── trading_bot_YYYY-MM-DD.log
└── dashboard/  (React/Vite, GitHub Pages)
```

### Firebase paths used

```
/signals/{id}         all signals (executed + skipped) with status tags
/trades/{id}          completed trades + r_multiple
/portfolio            current_capital, day_pnl, brokerage_paid_today
/positions/{stock}    open positions with trailing_sl, broker SL status
/status               running/stopped
/kill_switch          dashboard writes, bot reads
/trading_enabled      pause toggle
/market_context       NIFTY direction + VIX + nifty_choppiness + vix_regime
/regime               TRENDING/VOLATILE/RANGE_BOUND/GAP_DAY
/news_sentiment       per-stock + global_risk_day flag
/analytics            per-strategy breakdown + score distribution
/premarket_status     margin check, holiday check, capital filter stats
/reports/{date}       end-of-day reports
/signal_queue         all signals from current cycle with status tags
```

---

## Safety Rules (HARDCODED — never override without testing)

1. Every trade MUST have a stop-loss
2. Max risk per trade: 1.5% of capital (Rs.225 at 15K capital)
3. Max 5 trades per day (or stance-imposed lower limit: 0 / 2 / 3 / 5)
4. Max 3 losing trades per day
5. Max 80% of broker margin deployed at once
6. Daily loss limit: 3% of starting capital (Rs.450 at 15K)
7. 2 consecutive losses = 15-min trading cooldown
8. 10-min minimum spacing between any two entries
9. 15-min re-entry cooldown per stock after exiting
10. No new trades after 13:00
11. All positions force-closed at 15:15
12. **VIX ≥ 18 = NO TRADES (binary, both equity and F&O)**
13. Choppiness Index > 70 = reject signal (both stock AND NIFTY checked)
14. ATR-based SL bounded 1.0%-1.5% of entry price
15. Score ≥ 80 required (Sniper Mode)
16. Broker-side STOPLOSS-LIMIT order placed for every position (exchange-level safety)
17. Kill switch on dashboard immediately exits all positions

---

## Key Design Decisions

1. **Rule-based, not ML.** Strategies are explicit if/else logic.
2. **Broker-side SL orders for crash safety.** STOPLOSS-LIMIT lives on exchange. Modified on trail. Cancelled before manual exit.
3. **Confluence requirement REMOVED.** Earlier versions required 2+ strategies to agree. Now: highest-confidence single signal goes through. The 10+ filters and 14-factor score gate handle quality.
4. **VIX binary, not graduated.** Earlier `vix_caution_threshold=20`, `vix_caution_size_pct=50` allowed reduced trading at VIX 18-20. Now all set to 18 — VIX 18 = full stop. Reason: VIX > 18 in 2025-2026 only happened during wars/tariffs/crises; bot makes money in VIX 10-18 (90% of days), trading in VIX 18+ adds risk without proportional reward.
5. **Tight SL bounds (1.0%-1.5%).** Previously 0.5%-3%. With 1.5R target, 3% SL = 4.5% target = unreachable intraday. Tightened to favor higher win rate.
6. **Lunch block is FLAG ONLY.** Not a hard block. Reason: choppiness + RVOL + VIX filters already handle low-quality lunch conditions.
7. **WebSocket cache for monitoring.** `monitor_positions()` reads prices from `data_stream.price_cache`, never polls broker LTP API except as fallback. Prevents rate-limit errors.
8. **VIX REST polling fallback.** Angel One WebSocket doesn't reliably stream VIX → bot polls Yahoo Finance every 5 min if WebSocket VIX hasn't arrived.
9. **Pre-seed candles on startup.** Historical API fills today's completed 5-min candles → all strategies ready immediately on late starts.
10. **Position adoption on startup.** `getPosition()` finds orphans → adopts with 2.5% fallback SL → places broker SL.

---

## Known Active Mismatches

These are real divergences in the code worth knowing:

1. **Live vs backtest strategies differ.** Live: ORB + VWAP_BOUNCE + EMA_CROSS + SR_BREAKOUT. Backtest: ORB + VWAP_REVERSION (the opposite logic). The backtest comment explicitly states: "Old VWAP Bounce: DISABLED (-Rs.1,298 loss)". So the backtest is testing a hypothesis that hasn't been moved to live yet, OR live was never updated to match the proven backtest config. Worth resolving.
2. **Pre-flight check #2 says "confluence is informational"** — comment matches code. No gate.
3. **Pre-flight check #10 (15-min trend) is short-circuited** — `trend_15m_enabled=False`, so always passes.
4. **Trading windows in config are weird:** `trading_window_2_start=13:00`, `trading_window_2_end=13:00` (zero minutes). The risk manager uses `window_1_start (9:30) ≤ now ≤ window_2_end (13:00)` so it works as a continuous 9:30-13:00 window despite the odd config. Could be cleaned up.
5. **Adopted positions get fixed 2.5% SL.** Not ATR-based until next monitoring cycle replaces it. Documented as intentional (no ATR data at adoption time).
6. **Comments reference 2.5R target** in some places (signal_scorer docstring, options_manager comment) but actual config is 1.5R. Inconsistency, not a bug.

---

## Running the Bot

```powershell
cd C:\Users\rshiv\nse-trading-bot\backend
python main.py              # mode from .env
python main.py --paper      # force paper mode
python main.py --live       # force live mode (REAL money!)
```

Run **before 9:00 AM IST** so the bot has time to authenticate, fetch instrument cache, fetch prev-day OHLC, and pre-seed candles before market opens.

To run the backtest:
```powershell
python backtest.py --start 2026-04-17 --end 2026-04-30
python backtest.py --start 2026-04-17 --end 2026-04-30 --stocks RELIANCE,TCS,INFY
```

Backtest uses **yfinance** (free, no broker auth needed). Note: yfinance only provides 5-min data for the last 60 days.

---

## Coding Conventions

- **Python**: type hints, dataclasses, `logging` (not print), config via `.env` + `config.py`
- **Error handling**: every API call wrapped in try/except, graceful degradation
- **Security**: keys in `.env` (gitignored), Firebase creds gitignored
- **Angel One specifics**: `-EQ` suffix for tradingsymbol; producttype="INTRADAY" for MIS, "DELIVERY" for CNC
- **WebSocket prices in paise** (divide by 100)
- **Instrument cache** must refresh daily

## User Profile

- **Experience**: Beginner in Python and trading
- **Capital**: Rs.15,000
- **Broker**: Angel One SmartAPI (free)
- **Goal**: Learn algorithmic trading with real but minimal risk
- **Philosophy**: Sniper Mode — fewer, higher-quality trades. Wait for confluence of context (macro/sector/fundamental) + technical signal. Protect capital above all.
