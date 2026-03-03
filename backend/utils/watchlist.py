"""
Watchlist — Stocks the bot scans for patterns.
===============================================
These are NIFTY 50 liquid stocks suitable for intraday trading.
Each stock has its Angel One instrument token.

To find tokens: Use Angel One's instrument list CSV
https://margincalculator.angelone.in/OpenAPI/files/OpenAPIScripMaster.json
"""

# Default watchlist: NIFTY 50 high-volume stocks
# Format: {"symbol": "RELIANCE", "token": "2885", "exchange": "NSE", "name": "Reliance Industries"}
# TODO: Update tokens from Angel One instrument master after API setup

DEFAULT_WATCHLIST = [
    {"symbol": "RELIANCE", "token": "2885", "exchange": "NSE", "name": "Reliance Industries"},
    {"symbol": "TCS", "token": "11536", "exchange": "NSE", "name": "Tata Consultancy Services"},
    {"symbol": "HDFCBANK", "token": "1333", "exchange": "NSE", "name": "HDFC Bank"},
    {"symbol": "INFY", "token": "1594", "exchange": "NSE", "name": "Infosys"},
    {"symbol": "ICICIBANK", "token": "4963", "exchange": "NSE", "name": "ICICI Bank"},
    {"symbol": "SBIN", "token": "3045", "exchange": "NSE", "name": "State Bank of India"},
    {"symbol": "BHARTIARTL", "token": "10604", "exchange": "NSE", "name": "Bharti Airtel"},
    {"symbol": "ITC", "token": "1660", "exchange": "NSE", "name": "ITC Limited"},
    {"symbol": "KOTAKBANK", "token": "1922", "exchange": "NSE", "name": "Kotak Mahindra Bank"},
    {"symbol": "LT", "token": "11483", "exchange": "NSE", "name": "Larsen & Toubro"},
    {"symbol": "AXISBANK", "token": "5900", "exchange": "NSE", "name": "Axis Bank"},
    {"symbol": "TATAMOTORS", "token": "3456", "exchange": "NSE", "name": "Tata Motors"},
    {"symbol": "SUNPHARMA", "token": "3351", "exchange": "NSE", "name": "Sun Pharma"},
    {"symbol": "BAJFINANCE", "token": "317", "exchange": "NSE", "name": "Bajaj Finance"},
    {"symbol": "WIPRO", "token": "3787", "exchange": "NSE", "name": "Wipro"},
    {"symbol": "HCLTECH", "token": "7229", "exchange": "NSE", "name": "HCL Technologies"},
    {"symbol": "TATASTEEL", "token": "3499", "exchange": "NSE", "name": "Tata Steel"},
    {"symbol": "NTPC", "token": "11630", "exchange": "NSE", "name": "NTPC"},
    {"symbol": "MARUTI", "token": "10999", "exchange": "NSE", "name": "Maruti Suzuki"},
    {"symbol": "TITAN", "token": "3506", "exchange": "NSE", "name": "Titan Company"},
    {"symbol": "POWERGRID", "token": "14977", "exchange": "NSE", "name": "Power Grid Corp"},
    {"symbol": "ONGC", "token": "2475", "exchange": "NSE", "name": "ONGC"},
    {"symbol": "JSWSTEEL", "token": "11723", "exchange": "NSE", "name": "JSW Steel"},
    {"symbol": "TECHM", "token": "13538", "exchange": "NSE", "name": "Tech Mahindra"},
    {"symbol": "INDUSINDBK", "token": "5258", "exchange": "NSE", "name": "IndusInd Bank"},
]

# NIFTY 50 index token (for market context)
NIFTY_TOKEN = {"symbol": "NIFTY 50", "token": "99926000", "exchange": "NSE"}


def get_watchlist() -> list[dict]:
    """Return the active watchlist."""
    return DEFAULT_WATCHLIST


def get_nifty_token() -> dict:
    """Return NIFTY 50 token for market context tracking."""
    return NIFTY_TOKEN
