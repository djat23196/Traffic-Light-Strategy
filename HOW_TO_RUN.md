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

#### Web App Pages

| Page | URL | What It Does |
|------|-----|--------------|
| Dashboard | `/` | Live price, controls, detected pairs, active trades, day summary |
| Trade Log | `/trades` | All trades with filters (timeframe, live/paper) |
| Settings | `/settings` | Edit config, manage Fyers authentication |

#### Dashboard Controls

| Button | Action |
|--------|--------|
| **Start Scan** | Detect RG candle pairs without trading |
| **Start Live** | Trade breakouts (toggle paper/live mode) |
| **Stop** | Stop any running scan or live session |
| **Run Backtest** | Test strategy on historical data |

Configure **timeframe** (1m / 5m / 15m / all), **strike** (ATM / OTM), **lots**, and **paper mode** toggle before starting.

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

## 5. Trade Logging

All trades (live and paper) are saved to CSV files automatically:

```
trades_NIFTY_2026-02-23.csv
trades_BANKNIFTY_2026-02-23.csv
```

View them on the web app's **Trade Log** page or open directly in Excel/Sheets.

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| "Authentication failed" | Check `CLIENT_ID` / `CLIENT_SECRET` in `config.py`. Ensure Redirect URL matches. |
| Token expired | Run `uv run python auth.py` again (tokens expire daily). |
| No pairs found | Normal — wait for the next candle to form a RG pair. |
| Port 8000 in use | Use `--port 8001` with uvicorn, or kill the existing process. |
| Port 8080 in use | Stop other services on 8080 before authenticating. |
| Web app won't connect | Run `auth.py` first, or click "Connect" on the Settings page. |
