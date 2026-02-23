#!/usr/bin/env python3
"""FastAPI web application for RG Candle Breakout Strategy."""

import csv
import json
import time
import base64
import asyncio
import logging
import threading
from datetime import date, datetime
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse, StreamingResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from strategy import (
    RGCandleBreakoutStrategy, Timeframe, StrikeType, DayState,
    CandlePair, Trade, TradeDirection,
)
from auth import FyersAuth, TOKEN_FILE
from config import (
    CLIENT_ID, CLIENT_SECRET, REDIRECT_URI,
    CAPITAL, DEFAULT_INDEX, DEFAULT_LOTS, DEFAULT_STRIKE,
    MAX_SL_PER_DAY, MAX_1MIN_TRADES, MAX_1MIN_SL, FIVE_MIN_MAX_RANGE_POINTS,
)
from state import app_state

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s', datefmt='%H:%M:%S')
logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).parent

app = FastAPI(title="RG Candle Breakout Strategy")
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")


# ── Helpers ────────────────────────────────────────────────────────────────

def get_config(key: str):
    """Read config with runtime override support."""
    if key in app_state.config_overrides:
        return app_state.config_overrides[key]
    import config
    return getattr(config, key)


def pair_to_dict(pair: CandlePair) -> dict:
    return {
        "time": pair.candle2_time.strftime("%H:%M"),
        "candle1_time": pair.candle1_time.strftime("%H:%M"),
        "pattern": pair.pattern,
        "range_high": round(pair.range_high, 1),
        "range_low": round(pair.range_low, 1),
        "range_points": round(pair.range_points, 1),
    }


def trade_to_dict(trade: Trade) -> dict:
    return {
        "entry_time": trade.entry_time.strftime("%H:%M:%S"),
        "direction": trade.direction.value,
        "entry_price": round(trade.entry_price, 2),   # Option premium
        "spot_price": round(trade.spot_price, 1),      # Index spot price
        "stop_loss": round(trade.stop_loss, 1),        # SL in spot terms
        "option_symbol": trade.option_symbol,
        "strike_price": trade.strike_price,
        "qty": trade.qty,
        "pnl": round(trade.pnl, 1),
        "is_active": trade.is_active,
        "is_sl_hit": trade.is_sl_hit,
        "is_paper": trade.is_paper,
        "trailing_sl": trade.trailing_sl_active,
        "exit_price": round(trade.exit_price, 2) if trade.exit_price else 0,
        "exit_time": trade.exit_time.strftime("%H:%M:%S") if trade.exit_time else None,
    }


def day_state_to_dict(ds: DayState) -> dict:
    return {
        "date": str(ds.date),
        "total_sl": ds.total_sl_count,
        "max_sl": int(get_config("MAX_SL_PER_DAY")),
        "onemin_sl": ds.onemin_sl_count,
        "max_1m_sl": int(get_config("MAX_1MIN_SL")),
        "onemin_trades": ds.onemin_trade_count,
        "max_1m_trades": int(get_config("MAX_1MIN_TRADES")),
        "onemin_disabled": ds.onemin_disabled,
        "trading_stopped": ds.is_trading_stopped,
        "active_count": len(ds.active_trades),
        "completed_count": len(ds.completed_trades),
    }


def publish_sse(event_type: str, data: dict):
    """Queue an SSE event from any thread."""
    event = {"event": event_type, "data": data, "id": int(time.time() * 1000)}
    with app_state.lock:
        app_state.sse_queue.append(event)
        if len(app_state.sse_queue) > 200:
            app_state.sse_queue = app_state.sse_queue[-200:]


def format_sse(event: str, data: dict, event_id=None) -> str:
    lines = []
    if event_id:
        lines.append(f"id: {event_id}")
    lines.append(f"event: {event}")
    lines.append(f"data: {json.dumps(data)}")
    lines.append("")
    return "\n".join(lines) + "\n"


# ── Background Workers ────────────────────────────────────────────────────

def background_scan_loop():
    """Continuously scan for pairs — no order placement.

    Price updates every 2s, pair scanning every 3rd cycle (~6s).
    """
    strategy = app_state.strategy
    tfs = [Timeframe.ONE_MIN, Timeframe.FIVE_MIN, Timeframe.FIFTEEN_MIN]
    cycle = 0

    while not app_state.stop_event.is_set():
        # Price update every cycle (fast)
        try:
            quote = strategy.fyers.quotes(data={"symbols": strategy.config["spot_symbol"]})
            if quote.get('s') == 'ok' and quote.get('d'):
                price = quote['d'][0]['v']['lp']
                with app_state.lock:
                    app_state.current_price = price
                publish_sse("price", {"price": price, "index": strategy.index})
        except Exception:
            pass

        # Pair scanning every 3rd cycle (slower — involves heavy API calls)
        if cycle % 3 == 0:
            for tf in tfs:
                if app_state.stop_event.is_set():
                    break
                try:
                    df = strategy.fetch_candles(tf, lookback_days=1)
                    if df is not None and len(df) >= 2:
                        pairs = strategy.detect_candle_pairs(df, tf)
                        key = tf.value + "m"
                        with app_state.lock:
                            app_state.detected_pairs[key] = [pair_to_dict(p) for p in pairs]
                        publish_sse("pairs", {"timeframe": key, "pairs": app_state.detected_pairs[key]})
                except Exception:
                    pass

        cycle += 1
        app_state.stop_event.wait(timeout=2)

    with app_state.lock:
        app_state.mode = "idle"
    publish_sse("status", {"mode": "idle"})


def background_live_loop(paper: bool, strike_type: StrikeType, lots: int,
                         timeframe_filter: Optional[str] = None, afternoon: bool = False):
    """Continuously scan and trade (or paper trade).

    Price + SL monitoring every 2s (fast loop).
    Pair scanning every 3rd cycle (~6s) to reduce API load.
    """
    strategy = app_state.strategy
    strategy.day_state = DayState()

    if timeframe_filter and timeframe_filter != "all":
        tfs = [Timeframe(timeframe_filter)]
    else:
        tfs = [Timeframe.ONE_MIN, Timeframe.FIVE_MIN, Timeframe.FIFTEEN_MIN]

    cycle = 0

    while not app_state.stop_event.is_set():
        now = datetime.now()
        if now.hour < 9 or (now.hour == 9 and now.minute < 15):
            app_state.stop_event.wait(timeout=10)
            continue
        # Afternoon mode: skip until 1:00 PM
        if afternoon and (now.hour < 13):
            app_state.stop_event.wait(timeout=30)
            continue
        if now.hour >= 15 and now.minute >= 25:
            publish_sse("status", {"mode": "market_closed"})
            break

        if strategy.day_state.is_trading_stopped:
            publish_sse("status", {"mode": "stopped_max_sl"})
            app_state.stop_event.wait(timeout=30)
            continue

        # ── Fast path: price + SL monitoring (every cycle, ~2s) ──
        try:
            quote = strategy.fyers.quotes(data={"symbols": strategy.config["spot_symbol"]})
            if quote.get('s') == 'ok' and quote.get('d'):
                price = quote['d'][0]['v']['lp']
                with app_state.lock:
                    app_state.current_price = price
                publish_sse("price", {"price": price, "index": strategy.index})
        except Exception:
            pass

        # Monitor active trades for SL hits every cycle (critical for fast exits)
        try:
            spot = strategy.monitor_active_trades()
            if spot is not None:
                publish_sse("trades", {
                    "active": [trade_to_dict(t) for t in strategy.day_state.active_trades],
                    "completed": [trade_to_dict(t) for t in strategy.day_state.completed_trades[-5:]],
                    "day_summary": day_state_to_dict(strategy.day_state),
                })
        except Exception as e:
            logger.error(f"Monitor error: {e}")

        # ── Slow path: pair scanning (every 3rd cycle, ~6s) ──
        if cycle % 3 == 0:
            for tf in tfs:
                if app_state.stop_event.is_set():
                    break
                can, _ = strategy.can_trade(tf)
                if not can:
                    continue
                try:
                    pairs = strategy.scan_and_trade(tf, strike_type, lots, paper=paper)
                    key = tf.value + "m"
                    with app_state.lock:
                        app_state.detected_pairs[key] = [pair_to_dict(p) for p in pairs]

                    publish_sse("pairs", {"timeframe": key, "pairs": app_state.detected_pairs.get(key, [])})
                    publish_sse("trades", {
                        "active": [trade_to_dict(t) for t in strategy.day_state.active_trades],
                        "day_summary": day_state_to_dict(strategy.day_state),
                    })
                except Exception as e:
                    publish_sse("error", {"message": f"Error on {tf.value}m: {e}"})

        cycle += 1
        app_state.stop_event.wait(timeout=2)

    with app_state.lock:
        app_state.mode = "idle"
    publish_sse("status", {"mode": "idle"})


# ── Lifecycle ─────────────────────────────────────────────────────────────

@app.on_event("startup")
async def startup():
    """Try to connect on startup using saved token."""
    try:
        strategy = RGCandleBreakoutStrategy(index=DEFAULT_INDEX, capital=CAPITAL)
        if strategy.connect():
            with app_state.lock:
                app_state.strategy = strategy
                app_state.is_connected = True
            logger.info("Auto-connected to Fyers on startup")
    except Exception as e:
        logger.info(f"No saved token, manual auth needed: {e}")


@app.on_event("shutdown")
async def shutdown():
    app_state.stop_event.set()


# ── Page Routes ───────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def page_dashboard(request: Request):
    return templates.TemplateResponse("dashboard.html", {"request": request, "page": "dashboard"})


@app.get("/trades", response_class=HTMLResponse)
async def page_trades(request: Request):
    return templates.TemplateResponse("trades.html", {"request": request, "page": "trades"})


@app.get("/settings", response_class=HTMLResponse)
async def page_settings(request: Request):
    return templates.TemplateResponse("settings.html", {"request": request, "page": "settings"})


# ── SSE Endpoint ──────────────────────────────────────────────────────────

@app.get("/api/events")
async def sse_events():
    async def generator():
        # Initial snapshot
        with app_state.lock:
            snapshot = {
                "mode": app_state.mode,
                "price": app_state.current_price,
                "pairs": app_state.detected_pairs,
                "connected": app_state.is_connected,
            }
            if app_state.strategy and app_state.strategy.day_state:
                snapshot["day_summary"] = day_state_to_dict(app_state.strategy.day_state)
                snapshot["active_trades"] = [trade_to_dict(t) for t in app_state.strategy.day_state.active_trades]
                snapshot["completed_trades"] = [trade_to_dict(t) for t in app_state.strategy.day_state.completed_trades]
        yield format_sse("snapshot", snapshot)

        last_idx = len(app_state.sse_queue)
        while True:
            await asyncio.sleep(1)
            with app_state.lock:
                new_events = app_state.sse_queue[last_idx:]
                last_idx = len(app_state.sse_queue)
            for ev in new_events:
                yield format_sse(ev["event"], ev["data"], ev.get("id"))

    return StreamingResponse(generator(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ── API: Status ───────────────────────────────────────────────────────────

@app.get("/api/status")
async def api_status():
    with app_state.lock:
        result = {
            "mode": app_state.mode,
            "connected": app_state.is_connected,
            "price": app_state.current_price,
            "index": app_state.strategy.index if app_state.strategy else DEFAULT_INDEX,
        }
        if app_state.strategy and app_state.strategy.day_state:
            result["day_summary"] = day_state_to_dict(app_state.strategy.day_state)
    return result


@app.get("/api/price")
async def api_price():
    if not app_state.is_connected or not app_state.strategy:
        return {"price": 0, "error": "Not connected"}
    try:
        quote = app_state.strategy.fyers.quotes(
            data={"symbols": app_state.strategy.config["spot_symbol"]}
        )
        if quote.get('s') == 'ok':
            price = quote['d'][0]['v']['lp']
            with app_state.lock:
                app_state.current_price = price
            return {"price": price, "index": app_state.strategy.index}
    except Exception as e:
        return {"price": 0, "error": str(e)}


@app.get("/api/pairs")
async def api_pairs():
    with app_state.lock:
        return {"pairs": dict(app_state.detected_pairs)}


@app.get("/api/trades/active")
async def api_active_trades():
    if not app_state.strategy:
        return {"trades": []}
    with app_state.lock:
        trades = [trade_to_dict(t) for t in app_state.strategy.day_state.active_trades]
    return {"trades": trades}


@app.get("/api/trades/completed")
async def api_completed_trades():
    if not app_state.strategy:
        return {"trades": []}
    with app_state.lock:
        trades = [trade_to_dict(t) for t in app_state.strategy.day_state.completed_trades]
    return {"trades": trades}


@app.get("/api/trades/log")
async def api_trade_log():
    index = app_state.strategy.index if app_state.strategy else DEFAULT_INDEX
    today = date.today().isoformat()
    filepath = BASE_DIR / f"trades_{index}_{today}.csv"
    if not filepath.exists():
        return {"trades": []}
    with open(filepath) as f:
        reader = csv.DictReader(f)
        trades = list(reader)
    return {"trades": trades}


@app.get("/api/day-summary")
async def api_day_summary():
    if not app_state.strategy:
        return {"error": "Not initialized"}
    with app_state.lock:
        return day_state_to_dict(app_state.strategy.day_state)


# ── API: Auth ─────────────────────────────────────────────────────────────

@app.get("/api/auth/status")
async def api_auth_status():
    token_exists = TOKEN_FILE.exists()
    connected = app_state.is_connected
    expiry = None
    if token_exists:
        try:
            with open(TOKEN_FILE) as f:
                info = json.load(f)
            payload = info["access_token"].split(".")[1]
            payload += "=" * (4 - len(payload) % 4)
            decoded = json.loads(base64.urlsafe_b64decode(payload))
            expiry = datetime.fromtimestamp(decoded["exp"]).isoformat()
        except Exception:
            pass
    return {"connected": connected, "token_saved": token_exists, "expiry": expiry}


@app.post("/api/auth/connect")
async def api_auth_connect():
    def do_connect():
        index = get_config("DEFAULT_INDEX")
        capital = float(get_config("CAPITAL"))
        strategy = RGCandleBreakoutStrategy(index=index, capital=capital)
        if strategy.connect():
            with app_state.lock:
                app_state.strategy = strategy
                app_state.is_connected = True
            publish_sse("status", {"connected": True, "mode": app_state.mode})
        else:
            publish_sse("error", {"message": "Connection failed"})

    threading.Thread(target=do_connect, daemon=True).start()
    return {"message": "Connecting... check browser for Fyers login"}


@app.post("/api/auth/clear")
async def api_auth_clear():
    if TOKEN_FILE.exists():
        TOKEN_FILE.unlink()
    with app_state.lock:
        app_state.is_connected = False
        app_state.strategy = None
    publish_sse("status", {"connected": False})
    return {"message": "Tokens cleared"}


# ── API: Controls ─────────────────────────────────────────────────────────

@app.post("/api/control/start-scan")
async def api_start_scan():
    if not app_state.is_connected:
        raise HTTPException(400, "Not connected. Authenticate first.")
    if app_state.mode != "idle":
        raise HTTPException(409, f"Already running: {app_state.mode}")

    with app_state.lock:
        app_state.stop_event = threading.Event()
        app_state.mode = "scanning"
    publish_sse("status", {"mode": "scanning"})
    threading.Thread(target=background_scan_loop, daemon=True).start()
    return {"message": "Scan started"}


@app.post("/api/control/start-live")
async def api_start_live(body: dict):
    if not app_state.is_connected:
        raise HTTPException(400, "Not connected. Authenticate first.")
    if app_state.mode != "idle":
        raise HTTPException(409, f"Already running: {app_state.mode}")

    paper = body.get("paper", True)
    strike = StrikeType.ATM if body.get("strike", "ATM") == "ATM" else StrikeType.OTM
    lots = int(body.get("lots", get_config("DEFAULT_LOTS")))
    tf = body.get("timeframe", "all")
    afternoon = body.get("afternoon", False)

    mode_label = "paper" if paper else "live"
    with app_state.lock:
        app_state.stop_event = threading.Event()
        app_state.mode = mode_label
    publish_sse("status", {"mode": mode_label})
    threading.Thread(
        target=background_live_loop,
        args=(paper, strike, lots, tf, afternoon),
        daemon=True
    ).start()
    return {"message": f"{'Paper' if paper else 'Live'} trading started"}


@app.post("/api/control/exit-trade")
async def api_exit_trade(body: dict = None):
    """Manually exit the active trade (paper or live)."""
    if not app_state.strategy:
        raise HTTPException(400, "Not initialized")
    if not app_state.strategy.has_active_trade():
        raise HTTPException(404, "No active trade to exit")

    symbol = body.get("symbol") if body else None
    with app_state.lock:
        trade = app_state.strategy.manual_exit_trade(symbol)

    if trade:
        publish_sse("trades", {
            "active": [trade_to_dict(t) for t in app_state.strategy.day_state.active_trades],
            "completed": [trade_to_dict(t) for t in app_state.strategy.day_state.completed_trades[-5:]],
            "day_summary": day_state_to_dict(app_state.strategy.day_state),
        })
        return {
            "message": f"Exited {trade.direction.value} | PnL: Rs.{trade.pnl:.2f}",
            "trade": trade_to_dict(trade),
        }
    raise HTTPException(404, "No matching trade found")


@app.post("/api/control/stop")
async def api_stop():
    app_state.stop_event.set()
    return {"message": "Stop signal sent"}


@app.post("/api/control/backtest")
async def api_backtest(body: dict):
    if not app_state.is_connected:
        raise HTTPException(400, "Not connected")
    if app_state.mode != "idle":
        raise HTTPException(409, f"Cannot backtest while {app_state.mode}")

    tf_val = body.get("timeframe", "5")
    days = int(body.get("days", 7))
    tf = Timeframe(tf_val)

    def run():
        with app_state.lock:
            app_state.mode = "backtesting"
        publish_sse("status", {"mode": "backtesting"})

        try:
            results_df = app_state.strategy.backtest(tf, days=days)
            if len(results_df) > 0:
                records = json.loads(results_df.to_json(orient="records"))
                total = len(results_df)
                wins = len(results_df[~results_df['sl_hit']])
                trailing_count = int(results_df['trailing_sl'].sum()) if 'trailing_sl' in results_df.columns else 0
                exit_types = results_df['exit_type'].value_counts().to_dict() if 'exit_type' in results_df.columns else {}
                summary = {
                    "total": total,
                    "wins": wins,
                    "losses": total - wins,
                    "win_rate": round(wins / total * 100, 1),
                    "avg_range": round(float(results_df['range_points'].mean()), 1),
                    "avg_profit": round(float(results_df['profit_pts'].mean()), 1),
                    "sl_rate": round(float(results_df['sl_hit'].mean()) * 100, 1),
                    "trailing_sl_count": trailing_count,
                    "exit_types": exit_types,
                }
                publish_sse("backtest", {"status": "complete", "results": records, "summary": summary})
            else:
                publish_sse("backtest", {"status": "complete", "results": [], "summary": {}})
        except Exception as e:
            publish_sse("error", {"message": f"Backtest error: {e}"})
        finally:
            with app_state.lock:
                app_state.mode = "idle"
            publish_sse("status", {"mode": "idle"})

    threading.Thread(target=run, daemon=True).start()
    return {"message": "Backtest started", "timeframe": tf_val, "days": days}


# ── API: Settings ─────────────────────────────────────────────────────────

@app.get("/api/settings")
async def api_get_settings():
    return {
        "DEFAULT_INDEX": get_config("DEFAULT_INDEX"),
        "CAPITAL": get_config("CAPITAL"),
        "DEFAULT_LOTS": get_config("DEFAULT_LOTS"),
        "DEFAULT_STRIKE": get_config("DEFAULT_STRIKE"),
        "MAX_SL_PER_DAY": get_config("MAX_SL_PER_DAY"),
        "MAX_1MIN_TRADES": get_config("MAX_1MIN_TRADES"),
        "MAX_1MIN_SL": get_config("MAX_1MIN_SL"),
        "FIVE_MIN_MAX_RANGE_POINTS": get_config("FIVE_MIN_MAX_RANGE_POINTS"),
    }


@app.post("/api/settings")
async def api_save_settings(body: dict):
    type_map = {
        "CAPITAL": float, "DEFAULT_LOTS": int, "MAX_SL_PER_DAY": int,
        "MAX_1MIN_TRADES": int, "MAX_1MIN_SL": int, "FIVE_MIN_MAX_RANGE_POINTS": int,
    }
    for key, value in body.items():
        if key in type_map:
            app_state.config_overrides[key] = type_map[key](value)
        else:
            app_state.config_overrides[key] = value
    return {"message": "Settings saved", "overrides": app_state.config_overrides}


# ── Run ───────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=True)
