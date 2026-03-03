# Angel One SmartAPI Setup Guide

## Step 1: Open Angel One Account

1. Go to https://www.angelone.in/open-demat-account
2. Fill in your details: Name, Phone, Email
3. Upload documents: PAN Card, Aadhaar, Bank proof, Signature
4. Complete video KYC (takes 5 minutes)
5. Wait 1-2 business days for account activation

## Step 2: Enable SmartAPI

1. Go to https://smartapi.angelone.in/
2. Click "Sign Up" and log in with your Angel One credentials
3. Go to "My Apps" → "Create App"
4. Fill in:
   - App Name: "Trading Bot" (anything you like)
   - Redirect URL: `http://localhost` (not used but required)
5. Note down your **API Key** — you'll need this
6. Your **Client ID** is your Angel One login ID

## Step 3: Generate TOTP Secret

Angel One uses TOTP (Time-based One-Time Password) for login.

1. In the Angel One app → Settings → Security → Enable TOTP
2. When it shows you a QR code, also look for "Secret Key" or "Manual Entry Code"
3. Save this secret key — this is your `ANGEL_TOTP_SECRET`
4. You can also use apps like Google Authenticator or Authy

## Step 4: Configure .env File

```bash
cd backend
cp .env.example .env
```

Edit `.env`:
```
ANGEL_API_KEY=your_api_key_from_step_2
ANGEL_CLIENT_ID=your_angel_one_login_id
ANGEL_PASSWORD=your_angel_one_password
ANGEL_TOTP_SECRET=your_totp_secret_from_step_3
```

## Step 5: Test Connection

```python
from SmartApi import SmartConnect
import pyotp

api_key = "your_api_key"
client_id = "your_client_id"
password = "your_password"
totp_secret = "your_totp_secret"

smart_api = SmartConnect(api_key=api_key)
totp = pyotp.TOTP(totp_secret).now()

data = smart_api.generateSession(client_id, password, totp)
print("Login successful!" if data["status"] else "Login failed!")
```

## Cost

- Account opening: FREE
- SmartAPI access: FREE
- Brokerage: ₹20/order or 0.03% (whichever is lower)
- No monthly charges for API

## Important Notes

- Your API key and credentials are sensitive — never share or commit them
- The TOTP secret lets anyone generate login codes — guard it carefully
- Angel One rate limits: ~10 requests/second for REST, unlimited for WebSocket
- Market hours: 9:15 AM – 3:30 PM IST (Mon–Fri, except holidays)
