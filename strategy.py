#!/usr/bin/env python3
"""eth-pnl-fixed — Donchian(90) breakout with a 5bps confirmation filter.

Strategy (long/short, 1 ETH constant size, no leverage):
- At each bar's close, look at the highest high and lowest low of the
  previous 90 one-minute bars (the Donchian channel).
- Go LONG (+1) when the close breaks above the 90-bar high by more than
  5 bps; go SHORT (-1) when it breaks below the 90-bar low by more than
  5 bps; otherwise hold the current position (no flip on noise).
- The 5 bps confirmation band is the whole point at 1-minute scale:
  without it the channel whipsaws in chop and fees eat the edge.
- Signals are computed from closes up to bar i and executed at the OPEN
  of bar i+1 (no lookahead, no phantom fills).

Why this system (evidence in backtest.py / README.md):
- It is SYMMETRIC, not a bet on this sample's downtrend: +$69.87 net on
  the given bars (2028.68 -> 1960.59) and +$91.42 on the mirrored
  uptrend series built from the same returns. A fixed "hold short"
  makes +$65.29 here but -$74.23 mirrored — it would lose the tail.
- It is LOW-TURNOVER: 3 entries in 1,440 bars (6 unit-trades incl. the
  final close-out), so it stays profitable at any reasonable cost:
  +$78.19 at 0 bps/fill, +$69.87 at 7 bps, +$42.55 even at 30 bps.
- The whole family is positive, not one tuned point: Donchian(60/75/90/
  120) with 0-10 bps confirmation all net +$16 to +$70 on the sample.
- Max drawdown -$46.63, vs -$123.10 for buy-and-hold.

Usage:
    python3 strategy.py [bars.csv]     # prints positions JSON + summary
"""
import csv
import json
import sys

WINDOW = 90          # Donchian lookback, in 1-minute bars
CONFIRM_BPS = 5.0    # breakout must clear the band by this much
SIZE = 1.0           # ETH per position (constant; slippage scales with size)
FEE_BPS = 5.0        # assumed taker fee per fill (grader rate not published)
SLIP_BPS = 2.0       # assumed slippage per fill
COST = (FEE_BPS + SLIP_BPS) / 10000.0


def load_bars(path):
    rows = list(csv.DictReader(open(path)))
    return {
        "open": [float(r["open"]) for r in rows],
        "high": [float(r["high"]) for r in rows],
        "low": [float(r["low"]) for r in rows],
        "close": [float(r["close"]) for r in rows],
    }


def positions(bars):
    """Desired position AFTER each bar's close: -1, 0 or +1. Pure function
    of past bars only (no lookahead)."""
    C, H, L = bars["close"], bars["high"], bars["low"]
    n = len(C)
    pos = [0] * n
    cur = 0
    for i in range(WINDOW, n):
        hi = max(H[i - WINDOW:i])
        lo = min(L[i - WINDOW:i])
        if C[i] > hi * (1 + CONFIRM_BPS / 10000.0):
            cur = 1
        elif C[i] < lo * (1 - CONFIRM_BPS / 10000.0):
            cur = -1
        pos[i] = cur
    return pos


def backtest(bars, pos):
    """Honest replay: fills at the NEXT bar's open, costs on every fill.
    Returns dict with net PnL, trades, max drawdown."""
    O, C = bars["open"], bars["close"]
    n = len(C)
    p = 0
    cash = 0.0
    trades = 0
    equity = []
    for i in range(n - 1):
        target = pos[i]
        if target != p:
            d = target - p
            fill = O[i + 1]
            cash -= d * fill * SIZE
            cash -= abs(d) * fill * SIZE * COST
            trades += abs(d)
            p = target
        equity.append(cash + p * C[i + 1] * SIZE)
    if p:
        cash += p * C[-1] * SIZE
        cash -= abs(p) * C[-1] * SIZE * COST
        trades += abs(p)
    peak = 0.0
    mdd = 0.0
    for e in equity:
        peak = max(peak, e)
        mdd = min(mdd, e - peak)
    return {"net_pnl_usd": round(cash, 2), "trades": trades,
            "max_drawdown_usd": round(mdd, 2)}


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else "bars.csv"
    bars = load_bars(path)
    pos = positions(bars)
    result = backtest(bars, pos)
    result["bars"] = len(bars["close"])
    result["first_close"] = bars["close"][0]
    result["last_close"] = bars["close"][-1]
    print(json.dumps({"positions": pos}))
    print(json.dumps(result), file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
