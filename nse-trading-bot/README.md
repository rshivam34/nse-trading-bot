# 🤖 NSE Intraday Trading Bot

An automated intraday trading system for Indian stocks (NSE) with a live web dashboard.

> ⚠️ **DISCLAIMER**: This is for educational purposes only. Not financial advice. Paper trade for at least 1 month before using real money. Markets involve real financial risk.

## Quick Start

### Prerequisites

1. **Python 3.10+** — [Download](https://www.python.org/downloads/)
2. **Node.js 18+** — [Download](https://nodejs.org/)
3. **Git** — [Download](https://git-scm.com/)
4. **Angel One Account** with SmartAPI enabled — [Sign Up](https://www.angelone.in/)
5. **Firebase Account** — [Console](https://console.firebase.google.com/)

### 1. Clone & Install

```bash
git clone https://github.com/YOUR_USERNAME/nse-trading-bot.git
cd nse-trading-bot

# Backend
cd backend
pip install -r requirements.txt

# Dashboard
cd ../dashboard
npm install
```

### 2. Configure API Keys

```bash
cd backend
cp .env.example .env
# Edit .env with your Angel One and Firebase credentials
```

### 3. Run (Development)

```bash
# Terminal 1 — Backend
cd backend
python main.py

# Terminal 2 — Dashboard
cd dashboard
npm run dev
```

### 4. Deploy Dashboard

```bash
cd dashboard
npm run deploy  # Pushes to GitHub Pages
```

## How It Works

1. **9:00 AM** — Bot starts, connects to Angel One
2. **9:15 AM** — Market opens, bot streams live prices for 30 stocks
3. **9:15–9:30** — Observes opening range (no trades)
4. **9:30+** — Detects patterns, generates signals, places trades
5. **3:15 PM** — Exits all positions
6. **3:30 PM** — Generates daily report

## Strategies

| Strategy | Logic | Best For |
|----------|-------|----------|
| **ORB** | Breakout above/below first 15-min range | Trending days |
| **VWAP** | Bounce from volume-weighted average price | Mean reversion |
| **EMA** | 9 EMA crosses 21 EMA | Momentum trades |

## Safety Features

- 🛑 Stop-loss on every trade (mandatory)
- 📊 Max 2% risk per trade
- 🚫 Max 3 trades per day
- ⚠️ 3% daily loss limit — auto-stop
- 🔴 Kill switch on dashboard
- ⏰ No trades after 2:30 PM
- 📋 All positions closed by 3:15 PM

## License

MIT — Use at your own risk.
