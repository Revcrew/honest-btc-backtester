#!/usr/bin/env python3
"""
Trading System v2 (single-parameter change vs v1) — BTCUSDT, 4h, long-only.
Everything identical to v1 EXCEPT the exit: the fixed 2R take is replaced by
a trailing stop (Chandelier-style), to test v1's stated hypothesis that the
fixed 2R take cuts trending moves short.

Rules (no lookahead: signal on close of candle i, entry at open of i+1):
  - Trend filter: close_i > EMA200_i
  - Pullback: low_i <= EMA50_i AND close_i > EMA50_i AND close_i > open_i
  - Initial stop: low_i - 0.5 * ATR14_i (unchanged from v1)
  - Trailing stop: max(high since entry, up to previous candle) - 1.5 * ATR14_i;
    the stop only ever moves up, never below the initial stop.
    The trail for candle j is computed from highs before j (no intra-candle
    lookahead); if low_j <= trail_j, exit at trail_j.
  - Time exit: 30 candles after entry, at close (unchanged from v1)
  - Risk: 1% of equity per trade, position capped at 100% of equity (spot)
  - Costs: 0.10% of notional per side, all-in (unchanged from v1)
  - No overlapping positions; next signal searched after exit (unchanged).
"""
import json
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from backtest_v1 import load_data, add_indicators, metrics  # noqa: E402

BASE = os.path.dirname(os.path.abspath(__file__))


def run_v2(df, atr_mult=0.5, trail_mult=1.5, max_hold=30, risk_pct=0.01,
           cost=0.001, capital=10000.0, start=None, end=None):
    equity = capital
    trades = []
    equity_curve = [(df["time"].iloc[200], capital)]
    i = 200
    n = len(df)
    while i < n - 2:
        sig_time = df["time"].iloc[i]
        if start and sig_time < start:
            i += 1
            continue
        if end and sig_time >= end:
            break
        row = df.iloc[i]
        if not (row["close"] > row["ema200"] and row["low"] <= row["ema50"]
                and row["close"] > row["ema50"] and row["close"] > row["open"]):
            i += 1
            continue
        entry = float(df["open"].iloc[i + 1])
        stop = float(row["low"] - atr_mult * row["atr14"])
        if stop >= entry:
            i += 1
            continue
        risk_dist = entry - stop
        risk_amt = equity * risk_pct
        qty = min(risk_amt / risk_dist, equity / entry)
        trail_dist = trail_mult * float(row["atr14"])
        exit_price, reason, exit_idx = None, None, None
        highest = None  # highest high of candles strictly before candle j
        for j in range(i + 1, min(n, i + 1 + max_hold)):
            # Trail from highs strictly before candle j; on the entry candle
            # itself only the initial stop applies (no intra-candle lookahead).
            trail = stop if highest is None else max(stop, highest - trail_dist)
            h, l, c = (float(df["high"].iloc[j]), float(df["low"].iloc[j]),
                       float(df["close"].iloc[j]))
            if l <= trail:
                exit_price, reason, exit_idx = trail, "trail", j
                break
            highest = h if highest is None else max(highest, h)
            if j == i + max_hold:
                exit_price, reason, exit_idx = c, "time", j
                break
        if exit_price is None:
            break
        gross = qty * (exit_price - entry)
        fees = qty * entry * cost + qty * exit_price * cost
        net = gross - fees
        equity += net
        trades.append({
            "signal_time": str(sig_time),
            "entry_time": str(df["time"].iloc[i + 1]),
            "exit_time": str(df["time"].iloc[exit_idx]),
            "entry": round(entry, 2), "exit": round(exit_price, 2),
            "stop": round(stop, 2), "reason": reason,
            "qty": round(qty, 6), "net_usd": round(net, 2),
            "r_net": round(net / (qty * risk_dist), 3) if qty else 0,
            "equity_after": round(equity, 2),
        })
        equity_curve.append((df["time"].iloc[exit_idx], equity))
        i = exit_idx + 1
    return trades, equity_curve, equity


def main():
    df = add_indicators(load_data())
    print(f"Data: {len(df)} candles, {df['time'].min()} .. {df['time'].max()}")
    periods = {
        "full_2022-2026-09": (None, None),
        "in_sample_2022-2024": (pd.Timestamp("2022-01-01", tz="UTC"),
                                pd.Timestamp("2025-01-01", tz="UTC")),
        "out_of_sample_2025-2026-09": (pd.Timestamp("2025-01-01", tz="UTC"), None),
    }
    results = {}
    all_trades = {}
    for name, (s, e) in periods.items():
        trades, curve, _ = run_v2(df, start=s, end=e)
        results[name] = metrics(trades, 10000.0, curve)
        all_trades[name] = trades
        print(f"\n== {name} ==\n{json.dumps(results[name], indent=2, ensure_ascii=False)}")
    with open(os.path.join(BASE, "results_v2_trailing.json"), "w") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    pd.DataFrame(all_trades["full_2022-2026-09"]).to_csv(
        os.path.join(BASE, "trades_v2_trailing.csv"), index=False)
    print("\nSaved: results_v2_trailing.json, trades_v2_trailing.csv")


if __name__ == "__main__":
    main()
