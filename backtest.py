#!/usr/bin/env python3
"""Backtest harness for eth-pnl-fixed. Pure stdlib, no phantom fills.

Execution model (honest, no lookahead):
- Signals are computed from closes up to bar i and executed at the OPEN
  of bar i+1 (fills at open[i+1]).
- Position is in {-1, 0, +1} units of 1 ETH (constant size, so slippage
  does not scale up with size).
- Every unit of position change pays FEE_BPS + SLIP_BPS on the fill price.
  A long->short flip therefore costs 2x (close + open).
- PnL is marked in dollars per 1 ETH of notional; starting capital is
  irrelevant to the ranking metric (net PnL after costs).

Candidates: buy-and-hold baseline + MA-crossover trend systems +
Donchian breakout + a 1-min mean-reversion system (for contrast).
Robustness is judged on first-half vs second-half PnL, not just the
full sample, because the grader replays on a held-out tail.
"""
import csv, statistics as st

FEE_BPS = 5.0    # taker fee per fill (assumed; grader's exact rate is not published)
SLIP_BPS = 2.0   # slippage per fill (assumed)
COST = (FEE_BPS + SLIP_BPS) / 10000.0

rows = list(csv.DictReader(open("bars.csv")))
O = [float(r["open"]) for r in rows]
C = [float(r["close"]) for r in rows]
H = [float(r["high"]) for r in rows]
L = [float(r["low"]) for r in rows]
N = len(C)

def sma(vals, w, i):
    return sum(vals[i - w + 1:i + 1]) / w

def backtest(positions):
    """positions[i] = desired position AFTER bar i's close (executed at open i+1).
    Returns (net PnL $, gross PnL $, n_trades, max DD $)."""
    pos = 0
    cash = 0.0          # cash from fills (negative = paid)
    gross = 0.0         # mark-to-market PnL before costs
    equity_curve = []
    n_trades = 0
    entry_px = None
    for i in range(N - 1):
        target = positions[i]
        if target != pos:
            fill = O[i + 1]
            d = target - pos
            cash -= d * fill                 # buy d units (d<0 = sell)
            cost = abs(d) * fill * COST
            cash -= cost
            n_trades += abs(d)
            pos = target
        # mark-to-market at next bar's close, before any trade there
        equity = cash + pos * C[i + 1]
        equity_curve.append(equity)
    # close out at the last close
    if pos:
        cash += pos * C[-1]
        cash -= abs(pos) * C[-1] * COST
        n_trades += abs(pos)
    gross = None
    peak = 0.0; mdd = 0.0
    for e in equity_curve:
        peak = max(peak, e); mdd = min(mdd, e - peak)
    return cash, n_trades, mdd

def report(name, positions, extra=""):
    pnl, ntr, mdd = backtest(positions)
    # halves: PnL attributable to each half (approx: run backtest on each half)
    def half_pnl(a, b):
        sub_o, sub_c = O[a:b], C[a:b]
        pos = 0; cash = 0.0; ntr2 = 0
        for i in range(len(sub_c) - 1):
            t = positions[a + i]
            if t != pos:
                d = t - pos
                cash -= d * sub_o[i + 1] + abs(d) * sub_o[i + 1] * COST
                ntr2 += abs(d); pos = t
        if pos:
            cash += pos * sub_c[-1] - abs(pos) * sub_c[-1] * COST
        return cash
    h1, h2 = half_pnl(0, N // 2), half_pnl(N // 2, N)
    print(f"{name:<34} net=${pnl:>8.2f}  trades={ntr:>3}  maxDD=${mdd:>7.2f}  "
          f"1st-half=${h1:>7.2f}  2nd-half=${h2:>7.2f}  {extra}")
    return pnl

print(f"bars={N}  first close={C[0]:.2f}  last close={C[-1]:.2f}  "
      f"cost/fill={FEE_BPS + SLIP_BPS:.0f}bps")
print("=" * 108)
report("buy-and-hold (long 1)", [1] * N)
report("hold short (-1)", [-1] * N)

# MA trend: +1 if close > SMA(slow) else -1; and the +1/0 variant.
for slow in (30, 60, 120, 240):
    pos = [0] * N
    for i in range(slow, N):
        pos[i] = 1 if C[i] > sma(C, slow, i) else -1
    report(f"trend close>SMA({slow}) else short", pos)
for fast, slow in ((5, 30), (10, 60), (10, 120), (20, 60), (20, 120), (10, 240)):
    pos = [0] * N
    for i in range(slow, N):
        pos[i] = 1 if sma(C, fast, i) > sma(C, slow, i) else -1
    report(f"trend SMA({fast})>SMA({slow}) else short", pos)
# flat-when-choppy variant: 0 instead of short
for slow in (60, 120):
    pos = [0] * N
    for i in range(slow, N):
        pos[i] = 1 if C[i] > sma(C, slow, i) else 0
    report(f"long-only close>SMA({slow}) else flat", pos)

# Donchian breakout (N-bar high/low), long/short.
for w in (20, 40, 60):
    pos = [0] * N
    for i in range(w, N):
        if C[i] > max(H[i - w:i]): pos[i] = 1
        elif C[i] < min(L[i - w:i]): pos[i] = -1
        else: pos[i] = pos[i - 1]
    report(f"donchian({w}) breakout", pos)

# Mean reversion: fade 1-min moves vs SMA(20) +/- k*std of last 20 closes.
for k in (1.0, 1.5):
    pos = [0] * N
    for i in range(20, N):
        m = sma(C, 20, i); sd = st.pstdev(C[i - 19:i + 1])
        pos[i] = -1 if C[i] > m + k * sd else (1 if C[i] < m - k * sd else 0)
    report(f"mean-revert SMA20 +/- {k}sd", pos)
print("=" * 108)
print("Sensitivity note: re-run with FEE_BPS/SLIP_BPS changed to see cost impact.")
