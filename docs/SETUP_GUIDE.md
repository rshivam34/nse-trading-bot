# Complete Setup Guide

## Step 1 — Firebase Web Config (Dashboard)

The dashboard needs your Firebase **web** API key (different from the admin key).

1. Go to: https://console.firebase.google.com/project/nse-trading-bot-7bb00/settings/general
2. Scroll to **"Your apps"** → click the Web (</>) icon if no app exists → Register app
3. Copy the `firebaseConfig` object
4. Open `dashboard/src/firebase.js` and replace the placeholder values

Your config will look like:
```js
const firebaseConfig = {
  apiKey: "AIzaSy...",
  authDomain: "nse-trading-bot-7bb00.firebaseapp.com",
  databaseURL: "https://nse-trading-bot-7bb00-default-rtdb.asia-southeast1.firebasedatabase.app",
  projectId: "nse-trading-bot-7bb00",
  storageBucket: "nse-trading-bot-7bb00.firebasestorage.app",
  messagingSenderId: "123456789",
  appId: "1:123456789:web:abcdef"
}
```

## Step 2 — Firebase Security Rules

Set rules so only the backend (service account) can write, but dashboard can read.

1. Go to: https://console.firebase.google.com/project/nse-trading-bot-7bb00/database/rules
2. Replace with:

```json
{
  "rules": {
    ".read": true,
    ".write": false,
    "kill_switch": {
      ".write": true
    },
    "config": {
      ".write": true
    }
  }
}
```

This allows:
- Anyone can READ (your dashboard)
- No one can WRITE (only backend service account via Admin SDK)
- Exception: `kill_switch` and `config` can be written from dashboard

## Step 3 — Backend .env File

Make sure `backend/.env` has all values filled:

```env
ANGEL_API_KEY=your_api_key
ANGEL_CLIENT_ID=S50998150
ANGEL_PASSWORD=your_password
ANGEL_TOTP_SECRET=your_totp_base32_secret
FIREBASE_CREDENTIALS_PATH=firebase-credentials.json
FIREBASE_DATABASE_URL=https://nse-trading-bot-7bb00-default-rtdb.asia-southeast1.firebasedatabase.app
INITIAL_CAPITAL=1000
LOG_LEVEL=INFO
```

**Where to find TOTP secret:**
- Angel One SmartAPI → Enable TOTP → They show a QR code
- Instead of scanning QR, click "Can't scan?" → You'll see the base32 secret
- This is a 32-character string like: `JBSWY3DPEHPK3PXP`

## Step 4 — Run the Backend

```bash
cd backend
python main.py          # Paper trading (safe, no real orders)
python main.py --live   # Live trading (real money!)
```

## Step 5 — Deploy Dashboard to GitHub Pages

### One-time setup:
```bash
cd dashboard
npm run build           # Build the React app
npm run deploy          # Deploy to GitHub Pages
```

Then enable Pages in GitHub:
1. Go to: https://github.com/rshivam34/nse-trading-bot/settings/pages
2. Source: Deploy from branch
3. Branch: `gh-pages` / `/ (root)`
4. Save

Dashboard will be live at: **https://rshivam34.github.io/nse-trading-bot/**

### Update dashboard after changes:
```bash
cd dashboard
npm run deploy
```

## Daily Workflow

1. **Morning (9:00 AM)**: Run `python main.py` in backend folder
2. **Open dashboard**: https://rshivam34.github.io/nse-trading-bot/
3. **9:15–9:30 AM**: Bot tracks opening range (no trades)
4. **9:30 AM onwards**: Signals appear in dashboard
5. **Evening**: Bot auto-exits at 3:15 PM, shows daily report

## Architecture Reminder

```
Backend (your laptop)
  → Real-time prices from Angel One WebSocket
  → Detects ORB/VWAP/EMA patterns
  → Pushes signals to Firebase
                    ↓
          Firebase Realtime Database
                    ↓
  Dashboard (GitHub Pages)
  → Shows signals, P&L, positions in real-time
  → Kill switch writes back to Firebase
                    ↓
  Backend reads kill switch → exits positions
```
