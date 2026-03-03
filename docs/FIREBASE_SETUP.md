# Firebase Realtime Database Setup Guide

Firebase acts as the bridge between your Python backend and the React dashboard.
Backend WRITES data → Firebase ← Dashboard READS data in real-time.

## Step 1: Create Firebase Project

1. Go to https://console.firebase.google.com/
2. Click "Create a project"
3. Name it: "nse-trading-bot" (or anything)
4. Disable Google Analytics (not needed)
5. Click "Create project"

## Step 2: Enable Realtime Database

1. In Firebase console → Build → Realtime Database
2. Click "Create Database"
3. Choose location: `asia-south1` (Mumbai — lowest latency for India)
4. Start in **test mode** (we'll add security rules later)
5. Note your database URL: `https://your-project-id-default-rtdb.asia-south1.firebasedatabase.app`

## Step 3: Generate Service Account Key (for Python backend)

1. Go to Project Settings (gear icon) → Service Accounts
2. Click "Generate new private key"
3. Download the JSON file
4. Rename it to `firebase-credentials.json`
5. Place it in the `backend/` folder
6. **This file is gitignored** — never commit it

## Step 4: Get Web Config (for React dashboard)

1. Go to Project Settings → General
2. Scroll to "Your apps" → Click web icon (</>)
3. Register app name: "trading-dashboard"
4. Copy the `firebaseConfig` object — you'll need this for the dashboard

```javascript
const firebaseConfig = {
  apiKey: "...",
  authDomain: "...",
  databaseURL: "https://your-project-id-default-rtdb.asia-south1.firebasedatabase.app",
  projectId: "...",
  storageBucket: "...",
  messagingSenderId: "...",
  appId: "..."
};
```

## Step 5: Configure .env

Add to your `backend/.env`:
```
FIREBASE_CREDENTIALS_PATH=firebase-credentials.json
FIREBASE_DATABASE_URL=https://your-project-id-default-rtdb.asia-south1.firebasedatabase.app
```

## Step 6: Security Rules (do this before going live)

In Firebase console → Realtime Database → Rules:

```json
{
  "rules": {
    "signals": { ".read": true, ".write": false },
    "trades": { ".read": true, ".write": false },
    "portfolio": { ".read": true, ".write": false },
    "reports": { ".read": true, ".write": false }
  }
}
```

The Python backend uses the admin SDK (service account) which bypasses these rules.
The dashboard can only READ — it cannot modify data.

## Database Structure

```
/
├── signals/          ← Latest trading signals
│   └── {signal_id}: { stock, direction, entry, sl, target, strategy, timestamp }
│
├── trades/           ← Executed trades
│   └── {trade_id}: { stock, direction, entry, exit, pnl, reason, timestamp }
│
├── portfolio/        ← Current state (overwritten each update)
│   └── { current_capital, day_pnl, total_pnl, trades_today }
│
└── reports/          ← Daily reports
    └── {date}: { starting_capital, ending_capital, day_pnl, win_rate, trades }
```

## Cost

Firebase Spark (free) plan includes:
- 1 GB storage
- 100 simultaneous connections
- 10 GB/month data transfer

This is more than enough for our use case.
