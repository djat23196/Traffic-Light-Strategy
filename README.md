# RG Candle Pair Breakout Strategy

An automated options trading strategy for **NIFTY** and **BANKNIFTY** that detects consecutive Red-Green (or Green-Red) candle pairs and trades the breakout with CE/PE options.

Built on **Fyers API v3** (Python) with **UV** for dependency management.

---

## What This Strategy Does

1. **Finds a pair** of consecutive candles where one is red (bearish) and one is green (bullish)
2. **Marks the range** — the highest point (top wick) and lowest point (bottom wick) of both candles
3. **Trades the breakout**:
   - Price breaks **above** the range → Buy a **Call Option (CE)**
   - Price breaks **below** the range → Buy a **Put Option (PE)**

It works on three timeframes simultaneously (1-minute, 5-minute, and 15-minute) with built-in risk management.

---

## Prerequisites

1. **Python 3.10+** installed
2. **UV** package manager — install with: `curl -LsSf https://astral.sh/uv/install.sh | sh`
3. **A Fyers trading account** with API access — https://fyers.in/
4. **A Fyers API App** (takes 2 minutes):
   - Go to: https://myapi.fyers.in/dashboard
   - Click **"Create App"**
   - Fill in:
     - App Name: anything (e.g., "RG Strategy")
     - **Redirect URL: `http://127.0.0.1:8080`** (enables auto-capture login)
     - App Type: Web
   - Note down your **App ID** and **Secret Key**

---

## Quick Setup

### Step 1: Install Dependencies

```bash
cd RG_Candle_Breakout_Strategy
uv sync
```

### Step 2: Add Your Fyers Credentials

Copy `config.example.py` to `config.py` (config.py is gitignored and never committed):

```bash
cp config.example.py config.py
```

Then open `config.py` and replace the placeholder values:

```python
CLIENT_ID = "YOUR_APP_ID-100"          # Your App ID from Fyers dashboard
CLIENT_SECRET = "YOUR_SECRET_KEY"       # Your Secret Key from Fyers dashboard
REDIRECT_URI = "http://127.0.0.1:8080" # Must match your Fyers app settings
```

### Step 3: Authenticate

```bash
uv run python auth.py
```

Your browser opens → login to Fyers → approve → **auth code is captured automatically** (no copy-paste needed).

Token is saved locally in `.tokens/`. Valid for ~24 hours.

### Step 4: Run the Strategy

```bash
uv run python run.py
```

---

## How to Use

### Scan for Pairs (No Trading — Safe to Run Anytime)

```bash
# Scan NIFTY on all timeframes
uv run python run.py

# Scan BANKNIFTY
uv run python run.py --index BANKNIFTY

# Scan only 5-minute chart
uv run python run.py --timeframe 5
```

### Backtest (Test on Historical Data)

```bash
# Backtest NIFTY, last 7 days, all timeframes
uv run python run.py --mode backtest

# Backtest BANKNIFTY, last 14 days, 5-minute only
uv run python run.py --mode backtest --index BANKNIFTY --days 14 --timeframe 5
```

Results are saved as CSV files.

### Live Trading (Places Real Orders)

```bash
# Live trade NIFTY, all timeframes, ATM options, 1 lot
uv run python run.py --mode live

# Live trade BANKNIFTY, 5-min only, 2 lots
uv run python run.py --mode live --index BANKNIFTY --timeframe 5 --lots 2

# OTM options for capturing big trends
uv run python run.py --mode live --strike OTM

# Afternoon mode — start at 1:00 PM (for people with jobs)
uv run python run.py --mode live --afternoon

# Scalping mode — 1-min chart, ATM options
uv run python run.py --mode live --timeframe 1 --strike ATM
```

**To stop live trading:** Press `Ctrl+C` in the terminal.

### All Options

```bash
uv run python run.py --help
```

| Option | Values | Default | Description |
|--------|--------|---------|-------------|
| `--index` | NIFTY, BANKNIFTY | NIFTY | Which index to trade |
| `--mode` | scan, live, backtest | scan | What to do |
| `--timeframe` | 1, 5, 15, all | all | Which chart timeframe |
| `--strike` | ATM, OTM | ATM | ATM = scalp, OTM = big trends |
| `--lots` | 1, 2, 3... | 1 | Lots per trade |
| `--days` | 1-30 | 7 | Backtest history length |
| `--afternoon` | (flag) | OFF | Start at 1:00 PM |
| `--poll` | seconds | 5 | Time between scans in live mode |
| `--capital` | amount | 100000 | Trading capital in INR |

---

## Strategy Rules

### Timeframe-Specific Rules

| Rule | 1-Minute | 5-Minute | 15-Minute |
|------|----------|----------|-----------|
| Skip first candle of the day | Yes (9:15 AM) | No | No |
| Maximum trades allowed | 2 per day | Unlimited | Unlimited |
| After 2 stop-losses | Auto-switches to 5-min | Continues | Continues |
| 100-point range limit | No | Yes (skips wide pairs) | No |
| Best for | Quick scalps | Standard intraday | Options selling / theta |

### Which Options to Buy

| Scenario | Strike Type | Premium Range | When to Use |
|----------|-------------|---------------|-------------|
| Quick scalp | ATM (`--strike ATM`) | Rs.200-300 | Fast in-and-out trades |
| Big trend | OTM (`--strike OTM`) | Rs.50-150 | Hold through large moves |

### Risk Management (Automatic)

- **Max 3 stop-losses per day** — after 3 SLs, the strategy stops (market is sideways)
- **1-minute chart gets disabled after 2 SLs** — automatically switches to 5-minute
- **5-minute chart rejects pairs wider than 100 points** — keeps risk:reward in check

---

## File Structure

```
RG_Candle_Breakout_Strategy/
├── config.py          ← Your Fyers credentials + settings (EDIT THIS FIRST)
├── auth.py            ← Handles Fyers login with auto-capture OAuth
├── strategy.py        ← The core strategy engine
├── run.py             ← Main entry point (run this)
├── pyproject.toml     ← Project config & dependencies (managed by UV)
├── uv.lock            ← Locked dependency versions
├── README.md          ← You are here
├── .gitignore         ← Prevents credentials from being committed to git
├── .venv/             ← (Auto-created) Virtual environment
└── .tokens/           ← (Auto-created) Stores your login token locally
```

---

## Troubleshooting

### "Authentication failed"
1. Check `CLIENT_ID` and `CLIENT_SECRET` in `config.py`
2. Make sure your Redirect URL in Fyers dashboard matches `config.py` (`http://127.0.0.1:8080`)
3. Delete `.tokens/` folder and try again: `uv run python auth.py`

### "No valid pairs found"
Normal — the market hasn't produced a Red-Green candle pair yet on that timeframe. Wait for the next candle.

### "5-min pair rejected — range > 100 pts"
The pair's range exceeds 100 points. This is a safety rule — wide ranges mean higher risk. The strategy will wait for a tighter pair.

### Token expired (next day)
Fyers tokens expire daily. Just run the strategy again — it will auto-open the browser for a fresh login.

---

## Settings

All risk/trading settings are in `config.py`:

```python
CAPITAL = 100000              # Your trading capital
DEFAULT_INDEX = "NIFTY"       # Default index
DEFAULT_LOTS = 1              # Lots per trade
DEFAULT_STRIKE = "ATM"        # ATM or OTM

MAX_SL_PER_DAY = 3            # Stop trading after this many SLs
MAX_1MIN_TRADES = 2           # Max trades on 1-min chart
MAX_1MIN_SL = 2               # Disable 1-min after this many SLs
FIVE_MIN_MAX_RANGE_POINTS = 100  # Skip wide pairs on 5-min
```

---

## Disclaimer

This strategy involves real money and real risk. Options trading can result in significant losses. Always:

- **Paper trade first** (use `--mode scan` or `--mode backtest` before going live)
- **Start with 1 lot** until you're comfortable
- **Never trade money you can't afford to lose**

The author is not responsible for any financial losses. Use at your own risk.
