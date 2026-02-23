#!/usr/bin/env python3
"""
Red-Green Candle Pair Breakout Strategy
========================================
Multi-timeframe options breakout strategy using Fyers API v3.

Strategy Logic:
1. Detect consecutive Red-Green (or Green-Red) candle pairs
2. Mark the High (top wick) and Low (bottom wick) of the pair as the breakout range
3. Buy CE on breakout above High, Buy PE on breakout below Low
4. Multi-timeframe: 1m (scalping), 5m (intraday), 15m (positional/selling)

Rules:
- 1-min: Skip first candle (9:15), max 2 trades, switch to 5m after 2 SLs
- 5-min: Use all candles, 100-point max range rule
- 15-min: For options selling / theta decay
- Max 3 SLs per day across all timeframes
- Strike selection: ATM (Rs.200-300) for scalping, OTM (Rs.50-150) for trends
"""

import csv
import io
import os
import time
import datetime
import urllib.request
import pandas as pd
import numpy as np
import logging
from datetime import date, timedelta
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Tuple
from enum import Enum

from auth import FyersAuth
from config import (
    CLIENT_ID, CLIENT_SECRET, REDIRECT_URI,
    CAPITAL, DEFAULT_LOTS,
    MAX_SL_PER_DAY, MAX_1MIN_TRADES, MAX_1MIN_SL,
    FIVE_MIN_MAX_RANGE_POINTS,
)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger(__name__)


# ─── Enums & Data Classes ───────────────────────────────────────────────────

class Timeframe(Enum):
    ONE_MIN = "1"
    FIVE_MIN = "5"
    FIFTEEN_MIN = "15"

class TradeDirection(Enum):
    CE = "CALL"    # Breakout above High → Buy Call
    PE = "PUT"     # Breakout below Low → Buy Put

class StrikeType(Enum):
    ATM = "ATM"    # At-The-Money (Rs.200-300 premium) for scalping
    OTM = "OTM"    # Out-of-The-Money (Rs.50-150 premium) for big trends

@dataclass
class CandlePair:
    """A detected Red-Green (or Green-Red) candle pair with its breakout range"""
    timeframe: Timeframe
    candle1_time: datetime.datetime
    candle2_time: datetime.datetime
    candle1_open: float
    candle1_high: float
    candle1_low: float
    candle1_close: float
    candle2_open: float
    candle2_high: float
    candle2_low: float
    candle2_close: float
    range_high: float = 0.0
    range_low: float = 0.0
    range_points: float = 0.0
    is_valid: bool = True
    pattern: str = ""  # "RED-GREEN" or "GREEN-RED"

    def __post_init__(self):
        self.range_high = max(self.candle1_high, self.candle2_high)
        self.range_low = min(self.candle1_low, self.candle2_low)
        self.range_points = self.range_high - self.range_low
        c1_green = self.candle1_close > self.candle1_open
        c2_green = self.candle2_close > self.candle2_open
        if c1_green and not c2_green:
            self.pattern = "GREEN-RED"
        elif not c1_green and c2_green:
            self.pattern = "RED-GREEN"
        else:
            self.is_valid = False
            self.pattern = "INVALID"

@dataclass
class Trade:
    """An executed or pending trade"""
    entry_time: datetime.datetime
    direction: TradeDirection
    pair: CandlePair
    strike_price: int = 0
    option_symbol: str = ""
    entry_price: float = 0.0   # Option premium (LTP of CE/PE)
    spot_price: float = 0.0    # Index spot price at entry
    stop_loss: float = 0.0
    target: float = 0.0
    exit_price: float = 0.0
    exit_time: Optional[datetime.datetime] = None
    pnl: float = 0.0
    is_active: bool = True
    is_sl_hit: bool = False
    trailing_sl_active: bool = False
    is_paper: bool = False
    qty: int = 0

@dataclass
class DayState:
    """Tracks all daily trading state and enforces limits"""
    date: date = None
    total_sl_count: int = 0
    onemin_sl_count: int = 0
    onemin_trade_count: int = 0
    onemin_disabled: bool = False
    is_trading_stopped: bool = False
    active_trades: List[Trade] = field(default_factory=list)
    completed_trades: List[Trade] = field(default_factory=list)
    traded_pairs: set = field(default_factory=set)  # (timeframe, candle2_time) keys

    def __post_init__(self):
        if self.date is None:
            self.date = date.today()


# ─── Core Strategy Engine ───────────────────────────────────────────────────

class RGCandleBreakoutStrategy:
    """
    Red-Green Candle Pair Breakout Strategy Engine

    Detects consecutive opposite-color candle pairs, establishes a range
    from their combined high/low, and trades the breakout with options.
    """

    INDEX_CONFIG = {
        "NIFTY": {
            "spot_symbol": "NSE:NIFTY50-INDEX",
            "option_prefix": "NSE:NIFTY",
            "lot_size": 65,
            "strike_gap": 50,
        },
        "BANKNIFTY": {
            "spot_symbol": "NSE:NIFTYBANK-INDEX",
            "option_prefix": "NSE:BANKNIFTY",
            "lot_size": 30,
            "strike_gap": 100,
        }
    }

    def __init__(self, index: str = "NIFTY", capital: float = CAPITAL):
        self.index = index
        self.config = self.INDEX_CONFIG[index]
        self.capital = capital
        self.day_state = DayState()
        self.fyers = None

    def connect(self) -> bool:
        """Authenticate and connect to Fyers API"""
        try:
            auth = FyersAuth(CLIENT_ID, CLIENT_SECRET, REDIRECT_URI)
            self.fyers = auth.get_fyers()
            if self.fyers:
                logger.info(f"Connected to Fyers for {self.index}")
                return True
            logger.error("Fyers connection failed")
            return False
        except Exception as e:
            logger.error(f"Connection error: {e}")
            return False

    # ─── Data Fetching ───────────────────────────────────────────────────

    def fetch_candles(self, timeframe: Timeframe, lookback_days: int = 1) -> Optional[pd.DataFrame]:
        """Fetch OHLCV candle data from Fyers for the given timeframe"""
        if not self.fyers:
            if not self.connect():
                return None

        end_date = date.today()
        start_date = end_date - timedelta(days=lookback_days)

        data = {
            "symbol": self.config["spot_symbol"],
            "resolution": timeframe.value,
            "date_format": "1",
            "range_from": start_date.strftime("%Y-%m-%d"),
            "range_to": end_date.strftime("%Y-%m-%d"),
            "cont_flag": "1"
        }

        try:
            response = self.fyers.history(data=data)
            if response.get('code') == 200 and 'candles' in response:
                df = pd.DataFrame(
                    response['candles'],
                    columns=['timestamp', 'open', 'high', 'low', 'close', 'volume']
                )
                df['timestamp'] = pd.to_datetime(df['timestamp'], unit='s') + pd.Timedelta(hours=5.5)
                df.set_index('timestamp', inplace=True)
                df = df.between_time('09:15', '15:30')
                for col in ['open', 'high', 'low', 'close', 'volume']:
                    df[col] = pd.to_numeric(df[col], errors='coerce')
                df.dropna(inplace=True)
                logger.info(f"Fetched {len(df)} candles ({timeframe.value}m) for {self.index}")
                return df
            else:
                logger.error(f"Fetch failed: {response}")
                return None
        except Exception as e:
            logger.error(f"Error fetching candles: {e}")
            return None

    # ─── Candle Pair Detection ───────────────────────────────────────────

    @staticmethod
    def is_green(row) -> bool:
        return row['close'] > row['open']

    @staticmethod
    def is_red(row) -> bool:
        return row['close'] < row['open']

    def detect_candle_pairs(self, df: pd.DataFrame, timeframe: Timeframe) -> List[CandlePair]:
        """
        Scan candle data to find consecutive Red-Green or Green-Red pairs.

        Applies timeframe-specific rules:
        - 1-min: Skip first candle of the day (9:15-9:16 AM)
        - 5-min: Reject pairs where range > 100 points
        - 15-min: No special filtering
        """
        pairs = []
        if df is None or len(df) < 2:
            return pairs

        start_idx = 0

        # 1-MIN RULE: Skip the very first candle of the day (9:15 AM)
        if timeframe == Timeframe.ONE_MIN:
            for i, ts in enumerate(df.index):
                if ts.time() > datetime.time(9, 16):
                    start_idx = i
                    break
            logger.info(f"1-min: Skipping first candle, starting from index {start_idx}")

        for i in range(start_idx, len(df) - 1):
            c1 = df.iloc[i]
            c2 = df.iloc[i + 1]

            c1_green = self.is_green(c1)
            c1_red = self.is_red(c1)
            c2_green = self.is_green(c2)
            c2_red = self.is_red(c2)

            # Must be opposite colors
            is_opposite = (c1_green and c2_red) or (c1_red and c2_green)
            if not is_opposite:
                continue

            pair = CandlePair(
                timeframe=timeframe,
                candle1_time=df.index[i],
                candle2_time=df.index[i + 1],
                candle1_open=c1['open'], candle1_high=c1['high'],
                candle1_low=c1['low'], candle1_close=c1['close'],
                candle2_open=c2['open'], candle2_high=c2['high'],
                candle2_low=c2['low'], candle2_close=c2['close'],
            )

            # 5-MIN RULE: Reject pairs where range > 100 points
            if timeframe == Timeframe.FIVE_MIN and pair.range_points > FIVE_MIN_MAX_RANGE_POINTS:
                logger.info(
                    f"5-min: Pair at {pair.candle2_time} REJECTED — "
                    f"range {pair.range_points:.1f} pts > {FIVE_MIN_MAX_RANGE_POINTS} pts"
                )
                pair.is_valid = False

            if pair.is_valid:
                pairs.append(pair)
                logger.info(
                    f"[{timeframe.value}m] {pair.pattern} pair at "
                    f"{pair.candle1_time.strftime('%H:%M')}-{pair.candle2_time.strftime('%H:%M')} | "
                    f"Range: {pair.range_low:.1f} - {pair.range_high:.1f} "
                    f"({pair.range_points:.1f} pts)"
                )

        return pairs

    # ─── Breakout Detection ──────────────────────────────────────────────

    def check_breakout(self, pair: CandlePair, current_price: float) -> Optional[TradeDirection]:
        """Check if price has broken out of the candle pair range"""
        if current_price > pair.range_high:
            return TradeDirection.CE
        elif current_price < pair.range_low:
            return TradeDirection.PE
        return None

    # ─── Symbol Master & Strike Selection ─────────────────────────────────

    SYMBOL_MASTER_URL = "https://public.fyers.in/sym_details/NSE_FO.csv"

    def _load_symbol_master(self):
        """Download Fyers symbol master and cache option symbols for this index."""
        logger.info(f"Downloading Fyers symbol master for {self.index}...")
        underlying = self.index  # "NIFTY" or "BANKNIFTY"

        try:
            response = urllib.request.urlopen(self.SYMBOL_MASTER_URL, timeout=15)
            content = response.read().decode('utf-8')
        except Exception as e:
            logger.error(f"Failed to download symbol master: {e}")
            self._option_symbols = {}
            self._expiry_timestamps = []
            return

        reader = csv.reader(io.StringIO(content))
        self._option_symbols = {}   # {(expiry_ts, strike_int, opt_type): symbol}
        expiry_set = set()

        for row in reader:
            if len(row) < 17:
                continue
            if row[13] != underlying:
                continue
            opt_type = row[16]
            if opt_type not in ('CE', 'PE'):
                continue

            symbol = row[9]            # e.g. NSE:NIFTY26FEB25750CE
            expiry_ts = int(row[8])    # expiry unix timestamp
            strike = int(float(row[15]))  # strike price
            lot_size = int(row[3])     # minimum lot size
            self._option_symbols[(expiry_ts, strike, opt_type)] = symbol
            expiry_set.add(expiry_ts)

            # Auto-update lot size from symbol master (most reliable source)
            if lot_size > 0 and self.config["lot_size"] != lot_size:
                self.config["lot_size"] = lot_size

        self._expiry_timestamps = sorted(expiry_set)
        logger.info(
            f"Loaded {len(self._option_symbols)} option symbols for {underlying}, "
            f"{len(self._expiry_timestamps)} expiries available, "
            f"lot size: {self.config['lot_size']}"
        )

    def get_option_symbol(self, spot_price: float, direction: TradeDirection,
                          strike_type: StrikeType = StrikeType.ATM,
                          expiry: str = None) -> Tuple[str, int]:
        """Look up the correct Fyers option symbol from the symbol master.

        Downloads and caches the symbol master on first call.
        Returns (symbol, strike_price) or ("", 0) if not found.
        """
        # Load symbol master if not cached
        if not hasattr(self, '_option_symbols') or not self._option_symbols:
            self._load_symbol_master()

        strike_gap = self.config["strike_gap"]
        atm_strike = round(spot_price / strike_gap) * strike_gap

        if strike_type == StrikeType.ATM:
            strike = atm_strike
        else:  # OTM
            if direction == TradeDirection.CE:
                strike = atm_strike + (2 * strike_gap)
            else:
                strike = atm_strike - (2 * strike_gap)

        option_type = "CE" if direction == TradeDirection.CE else "PE"

        # Find nearest future expiry
        now_ts = int(time.time())
        nearest_expiry = None
        for exp_ts in self._expiry_timestamps:
            if exp_ts > now_ts:
                nearest_expiry = exp_ts
                break

        if nearest_expiry is None:
            logger.error("No future expiry found — symbol master may be stale")
            return "", 0

        # Look up exact symbol
        key = (nearest_expiry, strike, option_type)
        symbol = self._option_symbols.get(key, "")

        if not symbol:
            logger.error(
                f"Symbol not found: expiry_ts={nearest_expiry}, "
                f"strike={strike}, type={option_type}"
            )
            return "", 0

        expiry_dt = datetime.datetime.fromtimestamp(nearest_expiry)
        logger.info(
            f"Option: {symbol} (Strike: {strike}, {strike_type.value}, "
            f"Expiry: {expiry_dt.strftime('%b %d')})"
        )
        return symbol, strike

    # ─── Order Placement ─────────────────────────────────────────────────

    def place_option_order(self, symbol: str, qty: int,
                           sl_price: float = 0) -> Optional[Dict]:
        """Place a BUY order for the option via Fyers API v3"""
        if not self.fyers:
            logger.error("Not connected to Fyers")
            return None

        order_data = {
            "symbol": symbol,
            "qty": qty,
            "type": 2,                # Market order
            "side": 1,                # Buy
            "productType": "INTRADAY",
            "limitPrice": 0,
            "stopPrice": 0,
            "validity": "DAY",
            "disclosedQty": 0,
            "offlineOrder": False,
            "stopLoss": 0,
            "takeProfit": 0,
            "isSliceOrder": False,
        }

        try:
            logger.info(f"Placing BUY: {symbol} x {qty}")
            response = self.fyers.place_order(data=order_data)
            logger.info(f"Order response: {response}")

            # Place separate SL order if provided
            if sl_price > 0 and response.get('s') == 'ok':
                sl_order = order_data.copy()
                sl_order.update({
                    "type": 3,          # Stop order (SL-M)
                    "side": -1,         # Sell (to exit)
                    "stopPrice": sl_price,
                })
                sl_resp = self.fyers.place_order(data=sl_order)
                logger.info(f"SL order: {sl_resp}")

            return response
        except Exception as e:
            logger.error(f"Order error: {e}")
            return None

    # ─── Risk Management ─────────────────────────────────────────────────

    def can_trade(self, timeframe: Timeframe) -> Tuple[bool, str]:
        """Check if we're allowed to take another trade (enforces daily limits)"""
        s = self.day_state

        if s.total_sl_count >= MAX_SL_PER_DAY:
            return False, f"{MAX_SL_PER_DAY} SLs hit — sideways market, stop trading"
        if s.is_trading_stopped:
            return False, "Trading stopped for the day"
        if timeframe == Timeframe.ONE_MIN:
            if s.onemin_disabled:
                return False, f"1-min disabled ({MAX_1MIN_SL} SLs) — use 5-min"
            if s.onemin_trade_count >= MAX_1MIN_TRADES:
                return False, f"1-min max {MAX_1MIN_TRADES} trades reached"

        return True, "OK"

    def record_sl_hit(self, timeframe: Timeframe):
        """Record a stop-loss hit and enforce limits"""
        s = self.day_state
        s.total_sl_count += 1

        if timeframe == Timeframe.ONE_MIN:
            s.onemin_sl_count += 1
            if s.onemin_sl_count >= MAX_1MIN_SL:
                s.onemin_disabled = True
                logger.warning(f"1-min DISABLED — {MAX_1MIN_SL} SLs hit, switching to 5-min")

        if s.total_sl_count >= MAX_SL_PER_DAY:
            s.is_trading_stopped = True
            logger.warning(f"TRADING STOPPED — {MAX_SL_PER_DAY} SLs hit today")

    # ─── Trade CSV Logging ──────────────────────────────────────────────

    def _save_trade_csv(self, trade: Trade, timeframe: Timeframe, paper: bool = False):
        """Append a trade to the daily CSV log file."""
        today = date.today().isoformat()
        mode = "PAPER" if paper else "LIVE"
        filename = f"trades_{self.index}_{today}.csv"

        file_exists = os.path.exists(filename)
        with open(filename, 'a', newline='') as f:
            writer = csv.writer(f)
            if not file_exists:
                writer.writerow([
                    "timestamp", "timeframe", "pattern", "direction",
                    "range_high", "range_low", "range_points",
                    "spot_price", "stop_loss", "entry_price",
                    "option_symbol", "strike_price", "qty", "mode"
                ])
            writer.writerow([
                trade.entry_time.strftime("%Y-%m-%d %H:%M:%S"),
                f"{timeframe.value}m",
                trade.pair.pattern,
                trade.direction.value,
                f"{trade.pair.range_high:.1f}",
                f"{trade.pair.range_low:.1f}",
                f"{trade.pair.range_points:.1f}",
                f"{trade.spot_price:.1f}",
                f"{trade.stop_loss:.1f}",
                f"{trade.entry_price:.2f}",
                trade.option_symbol,
                trade.strike_price,
                trade.qty,
                mode,
            ])
        logger.info(f"[{mode}] Trade logged to {filename}")

    # ─── Main Strategy Cycle ─────────────────────────────────────────────

    def has_active_trade(self) -> bool:
        """Check if there's already an open trade (one-at-a-time rule)."""
        return any(t.is_active for t in self.day_state.active_trades)

    def monitor_active_trades(self) -> Optional[float]:
        """Check active trades against SL levels. Returns current spot price or None.

        If spot hits a trade's SL level:
        - Mark trade as SL hit and inactive
        - Place exit order (or log paper exit)
        - Record SL hit for daily limit tracking
        - Move trade to completed list
        """
        # Market close auto-exit (3:15 PM)
        now = datetime.datetime.now()
        if now.hour >= 15 and now.minute >= 15:
            self._auto_exit_all_trades()
            return None

        if not self.has_active_trade():
            return None

        # Get current spot price
        try:
            quote = self.fyers.quotes(data={"symbols": self.config["spot_symbol"]})
            if quote.get('s') != 'ok':
                return None
            spot_price = quote['d'][0]['v']['lp']
        except Exception:
            return None

        for trade in self.day_state.active_trades:
            if not trade.is_active:
                continue

            sl_hit = False
            if trade.direction == TradeDirection.CE and spot_price <= trade.stop_loss:
                sl_hit = True
            elif trade.direction == TradeDirection.PE and spot_price >= trade.stop_loss:
                sl_hit = True

            if sl_hit:
                trade.is_active = False
                trade.is_sl_hit = True
                trade.exit_time = datetime.datetime.now()

                # Get current option premium for PnL
                try:
                    opt_quote = self.fyers.quotes(data={"symbols": trade.option_symbol})
                    if opt_quote.get('s') == 'ok' and 'd' in opt_quote:
                        trade.exit_price = opt_quote['d'][0].get('v', {}).get('lp', 0.0)
                except Exception:
                    pass

                trade.pnl = (trade.exit_price - trade.entry_price) * trade.qty
                tf = trade.pair.timeframe
                self.record_sl_hit(tf)
                self.day_state.completed_trades.append(trade)

                logger.warning(
                    f"SL HIT! {trade.direction.value} | Spot: {spot_price:.1f} hit SL: {trade.stop_loss:.1f} | "
                    f"Entry: Rs.{trade.entry_price:.2f} → Exit: Rs.{trade.exit_price:.2f} | "
                    f"PnL: Rs.{trade.pnl:.2f}"
                )

                # Place exit order with broker (skip for paper trades)
                if not trade.is_paper and trade.entry_price > 0 and self.fyers:
                    try:
                        exit_order = {
                            "symbol": trade.option_symbol,
                            "qty": trade.qty,
                            "type": 2,                # Market order
                            "side": -1,               # Sell
                            "productType": "INTRADAY",
                            "limitPrice": 0, "stopPrice": 0,
                            "validity": "DAY", "disclosedQty": 0,
                            "offlineOrder": False,
                        }
                        resp = self.fyers.place_order(data=exit_order)
                        logger.info(f"Exit order: {resp}")
                    except Exception as e:
                        logger.error(f"Exit order error: {e}")
                else:
                    logger.info(f"[PAPER] SL exit logged — no broker order sent")

            # Running PnL + Trailing SL for trades still active (not SL-hit)
            if trade.is_active:
                # Fetch unrealized PnL
                try:
                    opt_quote = self.fyers.quotes(data={"symbols": trade.option_symbol})
                    if opt_quote.get('s') == 'ok' and 'd' in opt_quote:
                        current_opt_ltp = opt_quote['d'][0].get('v', {}).get('lp', 0.0)
                        trade.exit_price = current_opt_ltp  # for display; overwritten on actual exit
                        trade.pnl = (current_opt_ltp - trade.entry_price) * trade.qty
                except Exception:
                    pass

                # Trailing SL: move SL to breakeven after 1R move in favor
                if not trade.trailing_sl_active:
                    if trade.direction == TradeDirection.CE:
                        if spot_price >= trade.pair.range_high + trade.pair.range_points:
                            trade.stop_loss = trade.pair.range_high
                            trade.trailing_sl_active = True
                            logger.info(
                                f"Trailing SL: moved to {trade.pair.range_high:.1f} (breakeven)"
                            )
                    elif trade.direction == TradeDirection.PE:
                        if spot_price <= trade.pair.range_low - trade.pair.range_points:
                            trade.stop_loss = trade.pair.range_low
                            trade.trailing_sl_active = True
                            logger.info(
                                f"Trailing SL: moved to {trade.pair.range_low:.1f} (breakeven)"
                            )

        # Clean up: remove completed trades from active list
        self.day_state.active_trades = [t for t in self.day_state.active_trades if t.is_active]

        return spot_price

    def manual_exit_trade(self, option_symbol: str = None) -> Optional[Trade]:
        """Manually exit an active trade. If no symbol given, exits the first active trade.

        Works for both paper and live — places sell order for live trades.
        Returns the exited Trade or None.
        """
        target = None
        for trade in self.day_state.active_trades:
            if not trade.is_active:
                continue
            if option_symbol is None or trade.option_symbol == option_symbol:
                target = trade
                break

        if target is None:
            logger.info("Manual exit: no matching active trade found")
            return None

        target.is_active = False
        target.exit_time = datetime.datetime.now()

        # Fetch current option premium for PnL
        try:
            opt_quote = self.fyers.quotes(data={"symbols": target.option_symbol})
            if opt_quote.get('s') == 'ok' and 'd' in opt_quote:
                target.exit_price = opt_quote['d'][0].get('v', {}).get('lp', 0.0)
        except Exception:
            pass

        target.pnl = (target.exit_price - target.entry_price) * target.qty
        self.day_state.completed_trades.append(target)

        logger.info(
            f"MANUAL EXIT: {target.direction.value} | {target.option_symbol} | "
            f"Entry: Rs.{target.entry_price:.2f} → Exit: Rs.{target.exit_price:.2f} | "
            f"PnL: Rs.{target.pnl:.2f}"
        )

        # Place exit order with broker (skip for paper trades)
        if not target.is_paper and target.entry_price > 0 and self.fyers:
            try:
                exit_order = {
                    "symbol": target.option_symbol,
                    "qty": target.qty,
                    "type": 2,
                    "side": -1,
                    "productType": "INTRADAY",
                    "limitPrice": 0, "stopPrice": 0,
                    "validity": "DAY", "disclosedQty": 0,
                    "offlineOrder": False,
                }
                resp = self.fyers.place_order(data=exit_order)
                logger.info(f"Manual exit order: {resp}")
            except Exception as e:
                logger.error(f"Manual exit order error: {e}")
        else:
            logger.info(f"[PAPER] Manual exit logged — no broker order sent")

        # Clean up active list
        self.day_state.active_trades = [t for t in self.day_state.active_trades if t.is_active]
        return target

    def _auto_exit_all_trades(self):
        """Square off all open positions at market close (3:15 PM)."""
        if not any(t.is_active for t in self.day_state.active_trades):
            return

        logger.warning("MARKET CLOSE — squaring off all active trades")

        for trade in self.day_state.active_trades:
            if not trade.is_active:
                continue
            trade.is_active = False
            trade.exit_time = datetime.datetime.now()

            # Fetch final option premium
            try:
                opt_quote = self.fyers.quotes(data={"symbols": trade.option_symbol})
                if opt_quote.get('s') == 'ok' and 'd' in opt_quote:
                    trade.exit_price = opt_quote['d'][0].get('v', {}).get('lp', 0.0)
            except Exception:
                pass

            trade.pnl = (trade.exit_price - trade.entry_price) * trade.qty
            self.day_state.completed_trades.append(trade)

            logger.info(
                f"AUTO-EXIT: {trade.direction.value} | {trade.option_symbol} | "
                f"Entry: Rs.{trade.entry_price:.2f} → Exit: Rs.{trade.exit_price:.2f} | "
                f"PnL: Rs.{trade.pnl:.2f}"
            )

            # Place exit order with broker (skip for paper trades)
            if not trade.is_paper and trade.entry_price > 0 and self.fyers:
                try:
                    exit_order = {
                        "symbol": trade.option_symbol,
                        "qty": trade.qty,
                        "type": 2,
                        "side": -1,
                        "productType": "INTRADAY",
                        "limitPrice": 0, "stopPrice": 0,
                        "validity": "DAY", "disclosedQty": 0,
                        "offlineOrder": False,
                    }
                    resp = self.fyers.place_order(data=exit_order)
                    logger.info(f"Close exit order: {resp}")
                except Exception as e:
                    logger.error(f"Close exit error: {e}")
            else:
                logger.info(f"[PAPER] Auto-exit logged — no broker order sent")

        self.day_state.active_trades = [t for t in self.day_state.active_trades if t.is_active]
        self.day_state.is_trading_stopped = True

    def scan_and_trade(self, timeframe: Timeframe,
                       strike_type: StrikeType = StrikeType.ATM,
                       lots: int = DEFAULT_LOTS,
                       paper: bool = False) -> List[CandlePair]:
        """Full cycle: fetch candles → detect pairs → check breakout → place order.

        Rules enforced:
        - ONE active trade at a time (skip if a trade is already open)
        - SL = opposite side of pair range
        - Margin shortfall → stop trading for the day
        """
        tag = "[PAPER]" if paper else "[LIVE]"

        # RULE: One trade at a time — don't enter if there's an active trade
        if self.has_active_trade():
            return []

        can, reason = self.can_trade(timeframe)
        if not can:
            logger.info(f"Skip {timeframe.value}m: {reason}")
            return []

        df = self.fetch_candles(timeframe, lookback_days=1)
        if df is None or len(df) < 3:
            return []

        pairs = self.detect_candle_pairs(df, timeframe)
        if not pairs:
            logger.info(f"No valid pairs on {timeframe.value}m")
            return []

        latest_pair = pairs[-1]

        # Skip if this pair was already traded
        pair_key = (timeframe.value, latest_pair.candle2_time.strftime("%Y-%m-%d %H:%M"))
        if pair_key in self.day_state.traded_pairs:
            return pairs

        # Get live spot price
        quote = self.fyers.quotes(data={"symbols": self.config["spot_symbol"]})
        if quote.get('s') != 'ok':
            return pairs

        spot_price = quote['d'][0]['v']['lp']

        direction = self.check_breakout(latest_pair, spot_price)
        if direction is None:
            logger.info(
                f"No breakout. Price {spot_price:.1f} in range "
                f"[{latest_pair.range_low:.1f} - {latest_pair.range_high:.1f}]"
            )
            return pairs

        # STALE BREAKOUT CHECK: skip if price has already moved too far beyond the range
        # Max entry distance = 30% of the range (min 3 pts) — must catch the move early
        if direction == TradeDirection.CE:
            distance_past = spot_price - latest_pair.range_high
        else:
            distance_past = latest_pair.range_low - spot_price

        max_entry_distance = max(latest_pair.range_points * 0.3, 3)
        if distance_past > max_entry_distance:
            logger.warning(
                f"STALE BREAKOUT — skipping {direction.value}. "
                f"Spot {spot_price:.1f} is {distance_past:.1f} pts past range "
                f"(max allowed: {max_entry_distance:.1f} pts). Move already happened."
            )
            self.day_state.traded_pairs.add(pair_key)
            return pairs

        # SL = opposite side of the pair range
        if direction == TradeDirection.CE:
            sl_spot = latest_pair.range_low
        else:
            sl_spot = latest_pair.range_high

        logger.info(
            f"{tag} BREAKOUT {direction.value}! Spot: {spot_price:.1f} | "
            f"SL: {sl_spot:.1f} ({latest_pair.range_points:.1f} pts risk)"
        )

        symbol, strike = self.get_option_symbol(spot_price, direction, strike_type)
        if not symbol:
            logger.error(f"Could not find option symbol for {direction.value} at spot {spot_price:.1f}")
            self.day_state.traded_pairs.add(pair_key)
            return pairs
        qty = lots * self.config["lot_size"]

        # Fetch the option's actual LTP (premium)
        option_ltp = 0.0
        try:
            opt_quote = self.fyers.quotes(data={"symbols": symbol})
            if opt_quote.get('s') == 'ok' and 'd' in opt_quote:
                quote_data = opt_quote['d'][0].get('v', {})
                option_ltp = quote_data.get('lp', 0.0)
                logger.info(f"Option LTP: {symbol} = Rs.{option_ltp:.2f}")

                # Validate premium range per strategy rules
                if strike_type == StrikeType.ATM and (option_ltp < 100 or option_ltp > 400):
                    logger.warning(
                        f"ATM premium Rs.{option_ltp:.2f} outside ideal range (Rs.100-400). "
                        f"Consider adjusting strike."
                    )
                elif strike_type == StrikeType.OTM and (option_ltp < 30 or option_ltp > 200):
                    logger.warning(
                        f"OTM premium Rs.{option_ltp:.2f} outside ideal range (Rs.30-200). "
                        f"Consider adjusting strike."
                    )
            else:
                logger.warning(f"Could not fetch option LTP for {symbol}: {opt_quote.get('message', 'unknown error')}")
        except Exception as e:
            logger.warning(f"Option quote error for {symbol}: {e}")

        # Mark this pair as traded IMMEDIATELY
        self.day_state.traded_pairs.add(pair_key)

        trade = Trade(
            entry_time=datetime.datetime.now(),
            direction=direction, pair=latest_pair,
            strike_price=strike, option_symbol=symbol,
            entry_price=option_ltp,
            spot_price=spot_price,
            stop_loss=sl_spot,         # SL in spot terms (opposite side of range)
            is_paper=paper,
            qty=qty,
        )

        if paper:
            logger.info(
                f"{tag} TRADE: {direction.value} | {symbol} x {qty} "
                f"@ Rs.{option_ltp:.2f} (Spot: {spot_price:.1f}, SL: {sl_spot:.1f})"
            )
        else:
            response = self.place_option_order(symbol, qty)
            if not response or response.get('s') != 'ok':
                msg = response.get('message', '') if response else ''
                logger.error(f"Order failed for {symbol}: {msg}")
                # MARGIN SHORTFALL → stop all trading
                if response and 'margin' in msg.lower():
                    self.day_state.is_trading_stopped = True
                    logger.warning("TRADING STOPPED — insufficient margin")
                return pairs
            logger.info(
                f"{tag} TRADE: {direction.value} | {symbol} x {qty} "
                f"@ Rs.{option_ltp:.2f} (SL: {sl_spot:.1f})"
            )

        self.day_state.active_trades.append(trade)
        if timeframe == Timeframe.ONE_MIN:
            self.day_state.onemin_trade_count += 1

        self._save_trade_csv(trade, timeframe, paper)

        return pairs

    # ─── Live Runner ─────────────────────────────────────────────────────

    def run_live(self, timeframes: List[Timeframe] = None,
                 strike_type: StrikeType = StrikeType.ATM,
                 lots: int = DEFAULT_LOTS,
                 poll_interval: int = 5,
                 afternoon_mode: bool = False,
                 paper: bool = False):
        """Run the strategy live with continuous polling during market hours"""
        if timeframes is None:
            timeframes = [Timeframe.ONE_MIN, Timeframe.FIVE_MIN, Timeframe.FIFTEEN_MIN]

        if not self.connect():
            logger.error("Cannot start — connection failed")
            return

        self.day_state = DayState()

        mode_label = "PAPER TRADE" if paper else "LIVE"
        print(f"\n{'='*60}")
        print(f"  RG CANDLE BREAKOUT — {mode_label}")
        print(f"  Index: {self.index} | TF: {[t.value+'m' for t in timeframes]}")
        print(f"  Strike: {strike_type.value} | Lots: {lots}")
        if afternoon_mode:
            print(f"  Afternoon mode: ON (starts 1:00 PM)")
        print(f"{'='*60}\n")

        try:
            while True:
                now = datetime.datetime.now()
                mkt_open = now.replace(hour=9, minute=15, second=0)
                mkt_close = now.replace(hour=15, minute=25, second=0)

                if now < mkt_open or now > mkt_close:
                    if now > mkt_close:
                        self._print_day_summary()
                        break
                    time.sleep(10)
                    continue

                if afternoon_mode and now < now.replace(hour=13, minute=0, second=0):
                    time.sleep(30)
                    continue

                if self.day_state.is_trading_stopped:
                    logger.info("Stopped for today. Waiting for close.")
                    time.sleep(60)
                    continue

                for tf in timeframes:
                    can, _ = self.can_trade(tf)
                    if can:
                        try:
                            self.scan_and_trade(tf, strike_type, lots, paper=paper)
                        except Exception as e:
                            logger.error(f"Error on {tf.value}m: {e}")

                    if tf == Timeframe.ONE_MIN and self.day_state.onemin_disabled:
                        if Timeframe.FIVE_MIN not in timeframes:
                            timeframes.append(Timeframe.FIVE_MIN)

                time.sleep(poll_interval)

        except KeyboardInterrupt:
            logger.info("Stopped by user (Ctrl+C)")
            self._print_day_summary()

    # ─── Backtest ────────────────────────────────────────────────────────

    def backtest(self, timeframe: Timeframe, days: int = 7) -> pd.DataFrame:
        """Run a historical backtest with full trade lifecycle simulation.

        Matches live trading logic:
        - One trade at a time (no overlapping positions)
        - Stale breakout filter (skip if price moved >30% of range)
        - Trailing SL (after 1R move, SL moves to breakeven)
        - Market close auto-exit at 3:15 PM
        - Daily SL limits (max 3 per day)
        - 1-min specific: max 2 trades, disable after 2 SLs
        """
        logger.info(f"Backtesting: {self.index} | {timeframe.value}m | {days} days")

        df = self.fetch_candles(timeframe, lookback_days=days)
        if df is None or len(df) < 10:
            logger.error("Insufficient data")
            return pd.DataFrame()

        pairs = self.detect_candle_pairs(df, timeframe)
        results = []
        day_states = {}  # per-day tracking

        def get_ds(day):
            if day not in day_states:
                day_states[day] = {
                    "sl_count": 0,
                    "onemin_sl": 0,
                    "onemin_trades": 0,
                    "onemin_disabled": False,
                    "stopped": False,
                    "trade_exit_idx": -1,  # df index where active trade exits
                }
            return day_states[day]

        for pair in pairs:
            day = pair.candle2_time.date()
            ds = get_ds(day)

            # Daily limits
            if ds["stopped"]:
                continue
            if ds["sl_count"] >= MAX_SL_PER_DAY:
                ds["stopped"] = True
                continue

            # 1-min specific limits
            if timeframe == Timeframe.ONE_MIN:
                if ds["onemin_disabled"]:
                    continue
                if ds["onemin_trades"] >= MAX_1MIN_TRADES:
                    continue

            pair_idx = df.index.get_loc(pair.candle2_time)
            if pair_idx >= len(df) - 1:
                continue

            # One-trade-at-a-time: skip if previous trade hasn't exited
            if ds["trade_exit_idx"] >= pair_idx + 1:
                continue

            # Simulate the full trade lifecycle
            result = self._simulate_backtest_trade(df, pair, pair_idx, timeframe)
            if result is None:
                continue

            results.append(result)

            # Update day state
            ds["trade_exit_idx"] = result.pop("_exit_idx")

            if timeframe == Timeframe.ONE_MIN:
                ds["onemin_trades"] += 1

            if result["exit_type"] == "SL":
                ds["sl_count"] += 1
                if timeframe == Timeframe.ONE_MIN:
                    ds["onemin_sl"] += 1
                    if ds["onemin_sl"] >= MAX_1MIN_SL:
                        ds["onemin_disabled"] = True
                        logger.info(f"Backtest: 1-min disabled on {day} after {MAX_1MIN_SL} SLs")
                if ds["sl_count"] >= MAX_SL_PER_DAY:
                    ds["stopped"] = True
                    logger.info(f"Backtest: trading stopped on {day} after {MAX_SL_PER_DAY} SLs")

        results_df = pd.DataFrame(results)
        if len(results_df) > 0:
            self._print_backtest_summary(results_df, timeframe)
        return results_df

    def _simulate_backtest_trade(self, df: pd.DataFrame, pair: CandlePair,
                                  pair_idx: int, timeframe: Timeframe) -> Optional[Dict]:
        """Simulate a single trade from pair detection through exit.

        Walks candle-by-candle after the pair to find breakout, then simulates:
        - Entry at breakout level
        - SL at opposite side of range
        - Trailing SL to breakeven after 1R move
        - Market close auto-exit at 3:15 PM
        - Stale breakout filter

        Returns result dict with '_exit_idx' key, or None if no breakout.
        """
        day = pair.candle2_time.date()

        # Scan subsequent candles for breakout
        for j in range(pair_idx + 1, len(df)):
            candle = df.iloc[j]
            candle_time = df.index[j]

            # Don't look past end of day
            if candle_time.date() != day:
                return None

            # Check for breakout
            direction = None
            if candle['high'] > pair.range_high:
                direction = "CE"
            elif candle['low'] < pair.range_low:
                direction = "PE"

            if direction is None:
                continue

            # STALE BREAKOUT CHECK — use candle open as proxy for spot price
            if direction == "CE":
                distance_past = max(0, candle['open'] - pair.range_high)
            else:
                distance_past = max(0, pair.range_low - candle['open'])

            max_entry_distance = max(pair.range_points * 0.3, 3)
            if distance_past > max_entry_distance:
                return None  # Stale breakout — skip this pair

            # ── Entry established ──
            entry_spot = pair.range_high if direction == "CE" else pair.range_low
            original_sl = pair.range_low if direction == "CE" else pair.range_high
            current_sl = original_sl
            trailing_sl = False

            def _make_result(exit_idx, exit_time_str, sl_hit, exit_type, profit):
                return {
                    "date": day,
                    "pair_time": pair.candle2_time.strftime("%H:%M"),
                    "pattern": pair.pattern,
                    "timeframe": timeframe.value + "m",
                    "range_high": pair.range_high,
                    "range_low": pair.range_low,
                    "range_points": pair.range_points,
                    "direction": direction,
                    "breakout_time": candle_time.strftime("%H:%M"),
                    "exit_time": exit_time_str,
                    "stop_loss": original_sl,
                    "sl_hit": sl_hit,
                    "trailing_sl": trailing_sl,
                    "exit_type": exit_type,
                    "profit_pts": round(profit, 1),
                    "_exit_idx": exit_idx,
                }

            # Check if SL hit on the same breakout candle (worst case)
            sl_on_entry = False
            if direction == "CE" and candle['low'] <= current_sl:
                sl_on_entry = True
            elif direction == "PE" and candle['high'] >= current_sl:
                sl_on_entry = True

            if sl_on_entry:
                return _make_result(j, candle_time.strftime("%H:%M"),
                                    True, "SL", -pair.range_points)

            # Check trailing SL trigger on entry candle
            if direction == "CE" and candle['high'] >= pair.range_high + pair.range_points:
                trailing_sl = True
                current_sl = pair.range_high
            elif direction == "PE" and candle['low'] <= pair.range_low - pair.range_points:
                trailing_sl = True
                current_sl = pair.range_low

            # ── Walk forward candle-by-candle to simulate trade ──
            for k in range(j + 1, len(df)):
                tc = df.iloc[k]
                tt = df.index[k]

                # End of day (next day's candles)
                if tt.date() != day:
                    prev = df.iloc[k - 1]
                    profit = (prev['close'] - entry_spot) if direction == "CE" else (entry_spot - prev['close'])
                    return _make_result(k - 1, df.index[k - 1].strftime("%H:%M"),
                                        False, "EOD", profit)

                # Market close auto-exit at 3:15 PM
                if tt.time() >= datetime.time(15, 15):
                    profit = (tc['close'] - entry_spot) if direction == "CE" else (entry_spot - tc['close'])
                    return _make_result(k, tt.strftime("%H:%M"),
                                        False, "MARKET_CLOSE", profit)

                # Check SL
                sl_hit = False
                if direction == "CE" and tc['low'] <= current_sl:
                    sl_hit = True
                elif direction == "PE" and tc['high'] >= current_sl:
                    sl_hit = True

                if sl_hit:
                    if trailing_sl:
                        return _make_result(k, tt.strftime("%H:%M"),
                                            True, "TRAILING_SL", 0)
                    else:
                        return _make_result(k, tt.strftime("%H:%M"),
                                            True, "SL", -pair.range_points)

                # Check trailing SL trigger
                if not trailing_sl:
                    if direction == "CE" and tc['high'] >= pair.range_high + pair.range_points:
                        trailing_sl = True
                        current_sl = pair.range_high
                    elif direction == "PE" and tc['low'] <= pair.range_low - pair.range_points:
                        trailing_sl = True
                        current_sl = pair.range_low

            # Reached end of available data
            last = df.iloc[-1]
            profit = (last['close'] - entry_spot) if direction == "CE" else (entry_spot - last['close'])
            return _make_result(len(df) - 1, df.index[-1].strftime("%H:%M"),
                                False, "END_OF_DATA", profit)

        return None  # No breakout found before end of day

    # ─── Reports ─────────────────────────────────────────────────────────

    def _print_backtest_summary(self, df: pd.DataFrame, tf: Timeframe):
        total = len(df)
        wins = len(df[~df['sl_hit']])
        losses = len(df[df['sl_hit']])
        print(f"\n{'='*60}")
        print(f"  BACKTEST: {self.index} | {tf.value}-min | {total} trades")
        print(f"{'='*60}")
        print(f"  Wins: {wins} | Losses: {losses} | Win Rate: {wins/total*100:.1f}%")
        print(f"  CE trades: {len(df[df['direction']=='CE'])} | PE: {len(df[df['direction']=='PE'])}")
        print(f"  Avg range: {df['range_points'].mean():.1f} pts")
        print(f"  Avg profit: {df['profit_pts'].mean():.1f} pts")
        print(f"  SL hit rate: {df['sl_hit'].mean()*100:.1f}%")
        if 'exit_type' in df.columns:
            for et, cnt in df['exit_type'].value_counts().items():
                print(f"  {et}: {cnt}")
        if 'trailing_sl' in df.columns:
            tsl = df['trailing_sl'].sum()
            print(f"  Trailing SL triggered: {int(tsl)}/{total}")
        if 'date' in df.columns:
            print(f"\n  Daily:")
            for day, g in df.groupby('date'):
                w = len(g[~g['sl_hit']])
                l = len(g[g['sl_hit']])
                print(f"    {day}: {len(g)} trades (W:{w} L:{l})")
        print(f"{'='*60}\n")

    def _print_day_summary(self):
        s = self.day_state
        print(f"\n{'='*60}")
        print(f"  DAY SUMMARY: {s.date}")
        print(f"{'='*60}")
        print(f"  Active: {len(s.active_trades)} | Done: {len(s.completed_trades)}")
        print(f"  SLs: {s.total_sl_count}/{MAX_SL_PER_DAY} | 1-min SLs: {s.onemin_sl_count}/{MAX_1MIN_SL}")
        print(f"  1-min trades: {s.onemin_trade_count}/{MAX_1MIN_TRADES} | Disabled: {s.onemin_disabled}")
        print(f"{'='*60}\n")
