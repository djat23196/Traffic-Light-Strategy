#!/usr/bin/env python3
"""
Main Entry Point — Red-Green Candle Pair Breakout Strategy
===========================================================

Quick Start:
    python run.py                          # Scan NIFTY for pairs (default)
    python run.py --mode live              # Go live on NIFTY
    python run.py --mode backtest          # Backtest last 7 days
    python run.py --index BANKNIFTY        # Trade BANKNIFTY instead
    python run.py --afternoon              # Start at 1:00 PM (job holders)

Full Options:
    python run.py --help
"""

import argparse
import sys
import os

# Add current directory to path (so imports work from anywhere)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from strategy import RGCandleBreakoutStrategy, Timeframe, StrikeType
from config import CAPITAL, DEFAULT_INDEX, DEFAULT_LOTS, DEFAULT_STRIKE


def main():
    parser = argparse.ArgumentParser(
        description="RG Candle Pair Breakout Strategy — NIFTY & BANKNIFTY Options",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python run.py                                    Scan NIFTY (all timeframes)
  python run.py --mode live --index NIFTY          Live trade NIFTY
  python run.py --mode live --index BANKNIFTY      Live trade BANKNIFTY
  python run.py --mode backtest --days 7           Backtest last 7 days
  python run.py --timeframe 5                      Only use 5-min chart
  python run.py --strike OTM                       Use OTM options (big trends)
  python run.py --afternoon                        Start at 1:00 PM
  python run.py --mode live --timeframe 1 --lots 2 Live scalp, 2 lots, 1-min
        """
    )

    parser.add_argument("--index", choices=["NIFTY", "BANKNIFTY"],
                        default=DEFAULT_INDEX,
                        help=f"Index to trade (default: {DEFAULT_INDEX})")

    parser.add_argument("--mode", choices=["scan", "live", "backtest"],
                        default="scan",
                        help="scan = detect pairs, live = auto-trade, backtest = historical test")

    parser.add_argument("--timeframe", choices=["1", "5", "15", "all"],
                        default="all",
                        help="1 = 1-min scalp, 5 = 5-min intraday, 15 = 15-min selling, all = all three")

    parser.add_argument("--strike", choices=["ATM", "OTM"],
                        default=DEFAULT_STRIKE,
                        help="ATM = Rs.200-300 premium (scalp), OTM = Rs.50-150 (big trends)")

    parser.add_argument("--lots", type=int, default=DEFAULT_LOTS,
                        help=f"Number of lots per trade (default: {DEFAULT_LOTS})")

    parser.add_argument("--days", type=int, default=7,
                        help="Days of history for backtest (default: 7)")

    parser.add_argument("--capital", type=float, default=CAPITAL,
                        help=f"Trading capital in INR (default: {CAPITAL})")

    parser.add_argument("--afternoon", action="store_true",
                        help="Afternoon mode: start scanning at 1:00 PM (for job holders)")

    parser.add_argument("--poll", type=int, default=5,
                        help="Seconds between scans in live mode (default: 5)")

    parser.add_argument("--paper", action="store_true",
                        help="Paper trade mode: simulate trades without placing real orders")

    args = parser.parse_args()

    # ─── Banner ──────────────────────────────────────────────────────────
    print()
    print("  ╔════════════════════════════════════════════════════════╗")
    print("  ║  RG CANDLE PAIR BREAKOUT STRATEGY                    ║")
    print("  ║  NIFTY & BANKNIFTY Options Trading                   ║")
    print("  ╚════════════════════════════════════════════════════════╝")
    print()
    mode_label = f"{args.mode} (PAPER)" if args.paper else args.mode
    print(f"  Index     : {args.index}")
    print(f"  Mode      : {mode_label}")
    print(f"  Timeframe : {args.timeframe}")
    print(f"  Strike    : {args.strike}")
    print(f"  Lots      : {args.lots}")
    if args.afternoon:
        print(f"  Afternoon : ON (starts 1:00 PM)")
    print()

    # ─── Initialize ──────────────────────────────────────────────────────
    strategy = RGCandleBreakoutStrategy(index=args.index, capital=args.capital)

    if not strategy.connect():
        print("  Failed to connect. Check config.py credentials.")
        print("  Run: python auth.py   to test authentication")
        sys.exit(1)

    # Parse timeframes
    if args.timeframe == "all":
        timeframes = [Timeframe.ONE_MIN, Timeframe.FIVE_MIN, Timeframe.FIFTEEN_MIN]
    else:
        timeframes = [Timeframe(args.timeframe)]

    strike_type = StrikeType.ATM if args.strike == "ATM" else StrikeType.OTM

    # ─── Execute ─────────────────────────────────────────────────────────

    if args.mode == "scan":
        print(f"  Scanning {args.index} for Red-Green candle pairs...\n")
        for tf in timeframes:
            pairs = strategy.scan_and_trade(tf, strike_type, args.lots, paper=args.paper)
            status = f"{len(pairs)} valid pairs" if pairs else "No pairs found"
            print(f"  [{tf.value}m] {status}")
        print()

    elif args.mode == "live":
        strategy.run_live(
            timeframes=timeframes,
            strike_type=strike_type,
            lots=args.lots,
            poll_interval=args.poll,
            afternoon_mode=args.afternoon,
            paper=args.paper,
        )

    elif args.mode == "backtest":
        for tf in timeframes:
            results = strategy.backtest(tf, days=args.days)
            if len(results) > 0:
                filename = f"backtest_{args.index}_{tf.value}m.csv"
                results.to_csv(filename, index=False)
                print(f"  Saved: {filename}")


if __name__ == "__main__":
    main()
