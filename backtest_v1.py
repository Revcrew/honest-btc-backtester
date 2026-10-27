#!/usr/bin/env python3
"""
Trading System v1 — BTCUSDT, 4h, long-only trend pullback.
Rules (no lookahead: signal on close of candle i, entry at open of i+1):
  - Trend filter: close_i > EMA200_i
  - Pullback: low_i <= EMA50_i (touch) AND close_i > EMA50_i (held) AND close_i > open_i
  - Stop: low_i - atr_mult * ATR14_i
  - Take: entry + RR * (entry - stop)
  - Time exit: 30 candles after entry, at close
  - Risk: 1% of equity per trade, position capped at 100% of equity (spot, no leverage)
  - Costs: 0.10% of notional per side (fee + slippage, all-in)
  - If stop and take are both hit in one candle, stop is assumed first (conservative).
Data: Binance Vision monthly spot klines, normalised ms/us timestamps.
"""
import zipfile, glob, json, os
import pandas as pd
import numpy as np

BASE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(BASE, "data")

def load_data():
    frames = []
    for f in sorted(glob.glob(os.path.join(DATA, "BTCUSDT-4h-*.zip"))):
        z = zipfile.ZipFile(f)
        df = pd.read_csv(z.open(z.namelist()[0]), header=None, usecols=[0, 1, 2, 3, 4, 5])
        df.columns = ["ts", "open", "high", "low", "close", "volume"]
        frames.append(df)
    df = pd.concat(frames).sort_values("ts").drop_duplicates("ts").reset_index(drop=True)
    # Binance switched ms -> us timestamps in 2025
    df["ts"] = np.where(df["ts"] > 10**15, df["ts"] // 1000, df["ts"])
    df["time"] = pd.to_datetime(df["ts"], unit="ms", utc=True)
    return df

def add_indicators(df):
    df = df.copy()
    df["ema50"] = df["close"].ewm(span=50, adjust=False).mean()
    df["ema200"] = df["close"].ewm(span=200, adjust=False).mean()
    prev_close = df["close"].shift(1)
    tr = pd.concat([
        df["high"] - df["low"],
        (df["high"] - prev_close).abs(),
        (df["low"] - prev_close).abs(),
    ], axis=1).max(axis=1)
    df["atr14"] = tr.ewm(alpha=1/14, adjust=False).mean()
    return df

def run_backtest(df, rr=2.0, atr_mult=0.5, max_hold=30, risk_pct=0.01,
                 cost=0.001, capital=10000.0, start=None, end=None):
    equity = capital
    trades = []
    equity_curve = [(df["time"].iloc[200], capital)]
    i = 200
    n = len(df)
    while i < n - 2:
        sig_time = df["time"].iloc[i]
        if start and sig_time < start:
            i += 1; continue
        if end and sig_time >= end:
            break
        row = df.iloc[i]
        if not (row["close"] > row["ema200"] and row["low"] <= row["ema50"]
                and row["close"] > row["ema50"] and row["close"] > row["open"]):
            i += 1; continue
        entry = float(df["open"].iloc[i + 1])
        stop = float(row["low"] - atr_mult * row["atr14"])
        if stop >= entry or entry - stop <= 0:
            i += 1; continue
        take = entry + rr * (entry - stop)
        risk_dist = entry - stop
        risk_amt = equity * risk_pct
        qty = risk_amt / risk_dist
        qty = min(qty, equity / entry)  # spot cap, no leverage
        exit_price, reason, exit_idx = None, None, None
        for j in range(i + 1, min(n, i + 1 + max_hold)):
            h, l, c = float(df["high"].iloc[j]), float(df["low"].iloc[j]), float(df["close"].iloc[j])
            if l <= stop:
                exit_price, reason, exit_idx = stop, "stop", j; break
            if h >= take:
                exit_price, reason, exit_idx = take, "take", j; break
            if j == i + max_hold:  # last allowed candle
                exit_price, reason, exit_idx = c, "time", j; break
        if exit_price is None:  # ran out of data
            break
        gross = qty * (exit_price - entry)
        fees = qty * entry * cost + qty * exit_price * cost
        net = gross - fees
        equity += net
        trades.append({
            "signal_time": str(sig_time), "entry_time": str(df["time"].iloc[i + 1]),
            "exit_time": str(df["time"].iloc[exit_idx]), "entry": round(entry, 2),
            "exit": round(exit_price, 2), "stop": round(stop, 2), "take": round(take, 2),
            "reason": reason, "qty": round(qty, 6), "net_usd": round(net, 2),
            "r_net": round(net / (qty * risk_dist), 3) if qty else 0,
            "equity_after": round(equity, 2),
        })
        equity_curve.append((df["time"].iloc[exit_idx], equity))
        i = exit_idx + 1  # no overlapping positions; next signal after exit
    return trades, equity_curve, equity

def metrics(trades, capital, equity_curve):
    if not trades:
        return {"trades": 0}
    t = pd.DataFrame(trades)
    wins = t[t["net_usd"] > 0]; losses = t[t["net_usd"] <= 0]
    eq = pd.Series([v for _, v in equity_curve])
    dd = (eq / eq.cummax() - 1).min()
    return {
        "trades": int(len(t)),
        "winrate_pct": round(100 * len(wins) / len(t), 1),
        "wins": int(len(wins)), "losses": int(len(losses)),
        "net_usd": round(float(t["net_usd"].sum()), 2),
        "total_return_pct": round(100 * (float(equity_curve[-1][1]) / capital - 1), 1),
        "final_equity": round(float(equity_curve[-1][1]), 2),
        "profit_factor": round(float(wins["net_usd"].sum() / abs(losses["net_usd"].sum())), 2) if len(losses) and losses["net_usd"].sum() != 0 else None,
        "avg_win_usd": round(float(wins["net_usd"].mean()), 2) if len(wins) else 0,
        "avg_loss_usd": round(float(losses["net_usd"].mean()), 2) if len(losses) else 0,
        "expectancy_R_per_trade": round(float(t["r_net"].mean()), 3),
        "max_drawdown_pct": round(100 * float(dd), 1),
        "by_reason": t["reason"].value_counts().to_dict(),
    }

def main():
    df = add_indicators(load_data())
    print(f"Data: {len(df)} candles, {df['time'].min()} .. {df['time'].max()}")
    gaps = int((df["time"].diff().dt.total_seconds() != 14400).sum() - 1)
    print(f"4h gaps (excl. first row): {gaps}")
    bh_start = float(df["close"].iloc[200]); bh_end = float(df["close"].iloc[-1])
    print(f"Buy&hold from first tradable close: {100*(bh_end/bh_start-1):.1f}% "
          f"({bh_start:.0f} -> {bh_end:.0f})")

    periods = {
        "full_2022-2026-09": (None, None),
        "in_sample_2022-2024": (pd.Timestamp("2022-01-01", tz="UTC"), pd.Timestamp("2025-01-01", tz="UTC")),
        "out_of_sample_2025-2026-09": (pd.Timestamp("2025-01-01", tz="UTC"), None),
    }
    results = {}
    all_trades = {}
    for name, (s, e) in periods.items():
        trades, curve, _ = run_backtest(df, start=s, end=e)
        results[name] = metrics(trades, 10000.0, curve)
        all_trades[name] = trades
        print(f"\n== {name} ==\n{json.dumps(results[name], indent=2, ensure_ascii=False)}")

    print("\n== Sensitivity (full period) ==")
    sens = []
    for rr in [1.5, 2.0, 2.5, 3.0]:
        for am in [0.3, 0.5, 1.0]:
            trades, curve, _ = run_backtest(df, rr=rr, atr_mult=am)
            m = metrics(trades, 10000.0, curve)
            sens.append({"rr": rr, "atr_mult": am, **m})
            print(f"RR={rr} ATRx={am}: trades={m['trades']} win={m['winrate_pct']}% "
                  f"PF={m['profit_factor']} expR={m['expectancy_R_per_trade']} "
                  f"ret={m['total_return_pct']}% maxDD={m['max_drawdown_pct']}%")
    results["sensitivity"] = sens

    with open(os.path.join(BASE, "results_v1.json"), "w") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    pd.DataFrame(all_trades["full_2022-2026-09"]).to_csv(os.path.join(BASE, "trades_v1.csv"), index=False)
    print("\nSaved: results_v1.json, trades_v1.csv")

if __name__ == "__main__":
    main()
