#!/usr/bin/env python3
"""
Fyers API Configuration
========================
Replace the placeholder values below with your actual Fyers API credentials.

HOW TO GET YOUR CREDENTIALS:
1. Go to https://myapi.fyers.in/dashboard
2. Login with your Fyers account
3. Click "Create App" (or use an existing app)
4. Copy the App ID → paste as CLIENT_ID below
5. Copy the Secret Key → paste as CLIENT_SECRET below
6. Set the Redirect URL in your app settings to match REDIRECT_URI below

IMPORTANT:
- Never share your SECRET_KEY publicly
- Never commit this file to a public GitHub repo with real credentials
- If you accidentally expose your keys, regenerate them immediately from the dashboard
"""

# ┌──────────────────────────────────────────────────────────┐
# │  PASTE YOUR FYERS CREDENTIALS BELOW                     │
# └──────────────────────────────────────────────────────────┘

CLIENT_ID = "FAJNBKI82D-100"         # Your Fyers App ID
CLIENT_SECRET = "LSPB0O6I4R"         # Your Fyers Secret Key
REDIRECT_URI = "http://127.0.0.1:8080"  # Auto-capture enabled! Must match Fyers app settings

# ┌──────────────────────────────────────────────────────────┐
# │  TRADING SETTINGS (adjust to your risk appetite)         │
# └──────────────────────────────────────────────────────────┘

CAPITAL = 100000            # Starting capital in INR (Rs. 1,00,000)
DEFAULT_INDEX = "NIFTY"     # Default index: "NIFTY" or "BANKNIFTY"
DEFAULT_LOTS = 1            # Number of lots per trade
DEFAULT_STRIKE = "ATM"      # "ATM" (Rs.200-300 premium) or "OTM" (Rs.50-150 premium)

# ┌──────────────────────────────────────────────────────────┐
# │  RISK MANAGEMENT SETTINGS                                │
# └──────────────────────────────────────────────────────────┘

MAX_SL_PER_DAY = 3                # Stop trading after this many stop-losses in a day
MAX_1MIN_TRADES = 2               # Max trades allowed on 1-min chart
MAX_1MIN_SL = 2                   # Disable 1-min chart after this many SLs
FIVE_MIN_MAX_RANGE_POINTS = 100   # Reject 5-min pairs with range > this many points
