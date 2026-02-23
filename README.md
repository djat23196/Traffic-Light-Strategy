# RG Candle Pair Breakout Strategy

An automated options trading bot for **NIFTY** and **BANKNIFTY** that detects consecutive Red-Green (or Green-Red) candle pairs and trades the breakout with CE/PE options.

Built on **Fyers API v3** with a **FastAPI web dashboard** and **UV** for dependency management.

---

## What This Strategy Does

1. **Finds a pair** of consecutive candles where one is red (bearish) and one is green (bullish)
2. **Marks the range** — the highest point (top wick) and lowest point (bottom wick) of both candles
3. **Trades the breakout**:
   - Price breaks **above** the range → Buy a **Call Option (CE)**
   - Price breaks **below** the range → Buy a **Put Option (PE)**
4. **Manages the trade** — SL at opposite side of range, trailing SL to breakeven after 1R, auto-exit at market close

Works on three timeframes simultaneously (1-minute, 5-minute, 15-minute) with built-in risk management.

---

## Features

- **Web Dashboard** — Real-time price, detected pairs, active trades with live PnL, completed trades, day summary
- **Paper Trading** — Test with no real orders before going live
- **One Trade at a Time** — Enters a position, waits for SL/exit, then looks for the next pair
- **Automatic SL** — Stop-loss = opposite side of the candle pair range
- **Trailing SL** — After price moves 1R in your favor, SL trails to breakeven
- **Stale Breakout Filter** — Skips entries if price has already moved too far past the range
- **Market Close Auto-Exit** — Squares off all positions at 3:15 PM
- **Manual Exit** — One-click exit button on the dashboard for any active trade
- **Premium Validation** — Warns if option premium is outside ideal range (ATM: Rs.100-400, OTM: Rs.30-200)
- **Margin Shortfall Protection** — Stops trading if broker rejects order for insufficient margin
- **Browser Notifications** — Sound alert + desktop notification on SL hit or trade exit
- **Afternoon Mode** — Start scanning at 1:00 PM for people who can't watch the morning session
- **Symbol Master** — Auto-downloads Fyers symbol master for correct option symbols and lot sizes
- **CSV Trade Log** — Every trade (paper and live) logged with entry, SL, premium, PnL
- **Backtest** — Test the strategy on historical data (1-30 days)

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

### Step 4: Run the Web App

```bash
uv run uvicorn app:app --port 8000 --reload
```

Open **http://localhost:8000** in your browser.

---

## Web App Usage

### Dashboard (http://localhost:8000)

| Section | What It Shows |
|---------|---------------|
| **Spot Price** | Live NIFTY/BANKNIFTY price with tick animation |
| **Controls** | Start Scan, Start Live, Stop, Paper toggle, TF/Strike/Lots selectors, Afternoon mode, Backtest |
| **Detected Pairs** | RG/GR candle pairs found on each timeframe with range levels |
| **Active Trades** | Open position with entry price, spot, SL, live PnL, Exit button |
| **Day Summary** | SL count, 1m status, trading status |
| **Completed Trades** | Closed trades with entry/exit prices and PnL |
| **Backtest Results** | Historical strategy performance |

### Controls

| Control | Action |
|---------|--------|
| **Start Scan** | Detect pairs without placing trades |
| **Start Live** | Scan + trade breakouts (paper or live) |
| **Stop** | Stop any running session |
| **Exit** (on trade row) | Manually exit the active trade |
| **Paper Trade** checkbox | Toggle paper mode (no real orders) |
| **Afternoon mode** checkbox | Start scanning from 1:00 PM |
| **Run Backtest** | Test on historical data |

### Other Pages

| Page | URL | Purpose |
|------|-----|---------|
| Trade Log | `/trades` | All trades with filters (timeframe, live/paper) |
| Settings | `/settings` | Edit config, manage Fyers authentication |

---

## CLI Usage (Alternative)

### Scan (No Trading)

```bash
uv run python run.py                          # Scan NIFTY, all timeframes
uv run python run.py --index BANKNIFTY        # Scan BANKNIFTY
uv run python run.py --timeframe 5            # 5-min only
```

### Backtest

```bash
uv run python run.py --mode backtest                           # Last 7 days
uv run python run.py --mode backtest --days 14 --timeframe 5   # 14 days, 5-min
```

### Live Trading

```bash
uv run python run.py --mode live                                # Live, all timeframes
uv run python run.py --mode live --paper                        # Paper trade
uv run python run.py --mode live --timeframe 1 --strike ATM     # 1-min scalping
uv run python run.py --mode live --index BANKNIFTY --lots 2     # BANKNIFTY, 2 lots
uv run python run.py --mode live --afternoon                    # Start at 1:00 PM
uv run python run.py --mode live --strike OTM                   # OTM for big trends
```

Press `Ctrl+C` to stop live trading.

### All CLI Options

| Option | Values | Default | Description |
|--------|--------|---------|-------------|
| `--index` | NIFTY, BANKNIFTY | NIFTY | Which index to trade |
| `--mode` | scan, live, backtest | scan | What to do |
| `--timeframe` | 1, 5, 15, all | all | Which chart timeframe |
| `--strike` | ATM, OTM | ATM | ATM = scalp, OTM = big trends |
| `--lots` | 1, 2, 3... | 1 | Lots per trade |
| `--days` | 1-30 | 7 | Backtest history length |
| `--paper` | (flag) | OFF | Paper trade mode |
| `--afternoon` | (flag) | OFF | Start at 1:00 PM |
| `--poll` | seconds | 5 | Time between scans |
| `--capital` | amount | 100000 | Trading capital in INR |

---

## Strategy Rules

### Trade Lifecycle

1. **Detect** RG/GR candle pair → mark range (high/low)
2. **Wait** for breakout above high (CE) or below low (PE)
3. **Validate** — skip if price already moved too far past range (stale breakout)
4. **Enter** — buy CE or PE option, set SL at opposite side of range
5. **Monitor** — check SL every 5 seconds, compute live PnL
6. **Trail SL** — after 1R profit, move SL to breakeven (breakout level)
7. **Exit** — on SL hit, manual exit, or auto-exit at 3:15 PM
8. **Next** — after exit, look for the next pair (one trade at a time)

### Timeframe Rules

| Rule | 1-Minute | 5-Minute | 15-Minute |
|------|----------|----------|-----------|
| Skip first candle of the day | Yes (9:15 AM) | No | No |
| Maximum trades allowed | 2 per day | Unlimited | Unlimited |
| After 2 stop-losses | Auto-switches to 5-min | Continues | Continues |
| 100-point range limit | No | Yes (skips wide pairs) | No |
| Best for | Quick scalps | Standard intraday | Options selling / theta |

### Strike Selection

| Scenario | Strike Type | Premium Range | When to Use |
|----------|-------------|---------------|-------------|
| Quick scalp | ATM | Rs.100-400 | Fast in-and-out trades |
| Big trend | OTM | Rs.30-200 | Hold through large moves |

### Risk Management (Automatic)

- **One trade at a time** — no new entries while a position is open
- **Max 3 stop-losses per day** — after 3 SLs, trading stops (market is sideways)
- **1-minute chart disabled after 2 SLs** — automatically switches to 5-minute
- **5-minute rejects pairs wider than 100 points** — keeps risk:reward in check
- **Stale breakout filter** — skips if price moved >30% of range past breakout level
- **Margin shortfall** — stops all trading if broker rejects for insufficient margin
- **Market close exit** — auto-squares off all positions at 3:15 PM

---

## File Structure

```
RG_Candle_Breakout_Strategy/
├── app.py             ← FastAPI web app (routes, SSE, background workers)
├── strategy.py        ← Core strategy engine (detection, trading, monitoring)
├── state.py           ← Thread-safe shared app state
├── auth.py            ← Fyers OAuth with auto-capture
├── config.py          ← Your credentials + settings (EDIT THIS FIRST)
├── run.py             ← CLI entry point
├── pyproject.toml     ← Dependencies (managed by UV)
├── uv.lock            ← Locked dependency versions
├── templates/
│   ├── base.html      ← Layout (dark theme, nav bar)
│   ├── dashboard.html ← Main page: price, controls, pairs, trades
│   ├── trades.html    ← Trade log with filters
│   └── settings.html  ← Config editor + auth status
├── static/
│   ├── style.css      ← Dark theme CSS
│   └── app.js         ← SSE consumer, DOM updaters, controls
├── .tokens/           ← (Auto-created) Login token storage
└── trades_*.csv       ← (Auto-created) Daily trade logs
```

---

## API Endpoints

### Pages
| Method | Path | Description |
|--------|------|-------------|
| GET | `/` | Dashboard |
| GET | `/trades` | Trade log |
| GET | `/settings` | Settings |

### REST API
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/status` | Full status snapshot |
| GET | `/api/price` | Current spot price |
| GET | `/api/pairs` | Detected pairs by timeframe |
| GET | `/api/trades/active` | Open trades |
| GET | `/api/trades/completed` | Closed trades with PnL |
| GET | `/api/trades/log` | Today's CSV trade log |
| GET | `/api/day-summary` | SL/trade counts |
| GET | `/api/auth/status` | Connection + token expiry |
| POST | `/api/auth/connect` | Trigger Fyers OAuth |
| POST | `/api/auth/clear` | Clear tokens |
| POST | `/api/control/start-scan` | Start pair scanning |
| POST | `/api/control/start-live` | Start live/paper trading |
| POST | `/api/control/stop` | Stop running session |
| POST | `/api/control/exit-trade` | Manually exit active trade |
| POST | `/api/control/backtest` | Run backtest |
| GET | `/api/settings` | Read config |
| POST | `/api/settings` | Update config |
| GET | `/api/events` | SSE stream (real-time updates) |

---

## Settings

All risk/trading settings are in `config.py` (also editable from the web Settings page):

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

## Troubleshooting

| Problem | Fix |
|---------|-----|
| "Authentication failed" | Check `CLIENT_ID` / `CLIENT_SECRET` in `config.py`. Ensure Redirect URL matches. |
| Token expired | Run `uv run python auth.py` again (tokens expire daily). |
| No pairs found | Normal — wait for the next candle to form a RG pair. |
| "STALE BREAKOUT — skipping" | Price moved too far past range. This is correct behavior — the entry window was missed. |
| "ATM premium outside ideal range" | Advisory warning — trade still proceeds. Consider adjusting strike. |
| "Margin Shortfall" | Insufficient funds. Trading halts automatically. Add funds and restart. |
| Port 8000 in use | Use `--port 8001` with uvicorn, or kill the existing process. |
| Port 8080 in use | Stop other services on 8080 before authenticating. |
| Web app won't connect | Run `auth.py` first, or click "Connect" on the Settings page. |
| Wrong lot size error | Lot sizes auto-update from Fyers symbol master. Restart the app. |

---

## Disclaimer

This strategy involves real money and real risk. Options trading can result in significant losses. Always:

- **Paper trade first** — use the paper toggle before going live
- **Start with 1 lot** until you're comfortable
- **Never trade money you can't afford to lose**

The author is not responsible for any financial losses. Use at your own risk.
