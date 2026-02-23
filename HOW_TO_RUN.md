# How to Run — RG Candle Breakout Strategy

## 1. Install Dependencies

```bash
cd RG_Candle_Breakout_Strategy
uv sync
```

> Requires [UV](https://docs.astral.sh/uv/) and Python 3.10+.

---

## 2. Configure Fyers Credentials

Edit `config.py`:

```python
CLIENT_ID = "YOUR_APP_ID-100"
CLIENT_SECRET = "YOUR_SECRET_KEY"
REDIRECT_URI = "http://127.0.0.1:8080"
```

Create a Fyers API App at https://myapi.fyers.in/dashboard with Redirect URL set to `http://127.0.0.1:8080`.

---

## 3. Authenticate

```bash
uv run python auth.py
```

Browser opens automatically — login to Fyers — auth code is captured. Token saved to `.tokens/` (valid ~24 hours).

---

## 4. Run

You have **two ways** to use the strategy:

### Option A: Web App (Recommended)

```bash
uv run uvicorn app:app --port 8000 --reload
```

Open **http://localhost:8000** in your browser.

#### Dashboard Features

| Section | Description |
|---------|-------------|
| **Spot Price** | Live NIFTY/BANKNIFTY price with tick animation |
| **Controls** | Start Scan, Start Live, Stop, Paper toggle, TF/Strike/Lots, Afternoon mode, Backtest |
| **Detected Pairs** | RG/GR pairs on 1m/5m/15m tabs with range high/low/points |
| **Active Trades** | Open position with entry, spot, SL (with trailing indicator), live PnL, **Exit button** |
| **Day Summary** | Total SLs, 1m SLs, 1m trades, trading status |
| **Completed Trades** | Closed trades with entry/exit prices, PnL, SL hit status |
| **Backtest Results** | Win/loss stats and individual trade breakdown |

#### Controls

| Control | Action |
|---------|--------|
| **Start Scan** | Detect pairs without placing any trades |
| **Start Live** | Scan + trade breakouts (respects paper/live toggle) |
| **Stop** | Stop any running scan or live session |
| **Exit** (red button on trade row) | Manually exit the active trade at market price |
| **Paper Trade** checkbox | When checked, no real orders are sent to the broker |
| **Afternoon mode** checkbox | Skip market until 1:00 PM (for people with jobs) |
| **Run Backtest** | Test strategy on N days of historical data |

#### Other Pages

| Page | URL | Purpose |
|------|-----|---------|
| Trade Log | `/trades` | All trades with filters (1m/5m/15m, LIVE/PAPER) |
| Settings | `/settings` | Edit config values, manage Fyers authentication |

#### Notifications

The dashboard sends **browser notifications** and plays a **beep sound** on:
- SL hit (low tone)
- Manual trade exit

Allow notifications when prompted by your browser for the best experience.

---

### Option B: Command Line

#### Scan (No Trading)

```bash
uv run python run.py                          # Scan NIFTY, all timeframes
uv run python run.py --index BANKNIFTY        # Scan BANKNIFTY
uv run python run.py --timeframe 5            # 5-min only
```

#### Backtest

```bash
uv run python run.py --mode backtest                           # Last 7 days
uv run python run.py --mode backtest --days 14 --timeframe 5   # 14 days, 5-min
```

#### Live Trading

```bash
uv run python run.py --mode live                                # Live, all timeframes
uv run python run.py --mode live --paper                        # Paper trade (no real orders)
uv run python run.py --mode live --timeframe 1 --strike ATM     # 1-min scalping
uv run python run.py --mode live --index BANKNIFTY --lots 2     # BANKNIFTY, 2 lots
uv run python run.py --mode live --afternoon                    # Start at 1:00 PM
uv run python run.py --mode live --strike OTM                   # OTM for big trends
```

Press `Ctrl+C` to stop live trading.

#### All CLI Options

| Option | Values | Default | Description |
|--------|--------|---------|-------------|
| `--index` | NIFTY, BANKNIFTY | NIFTY | Index to trade |
| `--mode` | scan, live, backtest | scan | Operating mode |
| `--timeframe` | 1, 5, 15, all | all | Chart timeframe |
| `--strike` | ATM, OTM | ATM | ATM = scalp, OTM = big trends |
| `--lots` | 1+ | 1 | Lots per trade |
| `--days` | 1-30 | 7 | Backtest history |
| `--paper` | (flag) | OFF | Paper trade mode |
| `--afternoon` | (flag) | OFF | Start at 1:00 PM |
| `--poll` | seconds | 5 | Scan interval |
| `--capital` | amount | 100000 | Capital in INR |

```bash
uv run python run.py --help    # Full help
```

---

## 5. Trade Lifecycle

Understanding what happens when you click **Start Live**:

1. Bot scans for RG/GR candle pairs on selected timeframe(s)
2. When a pair is found and price breaks above/below the range → **entry signal**
3. **Stale check** — if price already moved >30% of range past breakout, skip (too late)
4. **One-at-a-time** — if a trade is already open, skip (wait for exit first)
5. Fetches correct option symbol from Fyers symbol master
6. Places buy order (or logs paper trade)
7. **SL monitoring** — every 5 seconds, checks spot price vs stop-loss level
8. **Trailing SL** — after price moves 1R in favor, SL moves to breakeven
9. **Exit** happens via: SL hit, manual Exit button, or auto-exit at 3:15 PM
10. After exit, bot resumes scanning for the next pair

---

## 6. Trade Logging

All trades (live and paper) are saved to CSV files automatically:

```
trades_NIFTY_2026-02-23.csv
trades_BANKNIFTY_2026-02-23.csv
```

CSV columns: timestamp, timeframe, pattern, direction, range_high, range_low, range_points, spot_price, stop_loss, entry_price, option_symbol, strike_price, qty, mode

View them on the web app's **Trade Log** page or open directly in Excel/Sheets.

---

## 7. Risk Management (Automatic)

| Rule | What Happens |
|------|-------------|
| One trade at a time | No new entries while a position is open |
| SL = opposite side of range | CE → SL at range low, PE → SL at range high |
| Trailing SL | After 1R profit, SL moves to breakeven |
| Max 3 SLs per day | Trading stops (sideways market signal) |
| 1-min disabled after 2 SLs | Auto-switches to 5-min chart |
| 5-min max 100pt range | Skips wide/risky pairs |
| Stale breakout filter | Skips if price moved >30% of range past breakout |
| Margin shortfall | Trading halts if broker rejects for insufficient funds |
| Market close | All positions auto-squared off at 3:15 PM |

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| "Authentication failed" | Check `CLIENT_ID` / `CLIENT_SECRET` in `config.py`. Ensure Redirect URL matches. |
| Token expired | Run `uv run python auth.py` again (tokens expire daily). |
| No pairs found | Normal — wait for the next candle to form a RG pair. |
| "STALE BREAKOUT — skipping" | Price moved too far past range. Correct behavior — entry window missed. |
| "ATM premium outside ideal range" | Warning only — trade still proceeds. Consider adjusting strike. |
| "Margin Shortfall" | Insufficient funds. Trading halts. Add funds and restart. |
| Port 8000 in use | Use `--port 8001` with uvicorn, or kill the existing process. |
| Port 8080 in use | Stop other services on 8080 before authenticating. |
| Web app won't connect | Run `auth.py` first, or click "Connect" on the Settings page. |
| Wrong lot size | Lot sizes auto-update from Fyers symbol master on first trade. Restart if stale. |
