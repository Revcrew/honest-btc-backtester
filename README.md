# Honest BTC Backtester

By **Alexander Khlystun** — a QA engineer with an AI focus from Lviv, Ukraine.
Seven years in QA, and the rule I bring to trading ideas is the same one I
bring to software: a negative test result is a result, not a reason to refit
until the numbers look good.

## The strategy (v1, exactly as specified)

- Asset: BTCUSDT, 4h candles. Long only.
- Entry: price above EMA200, pullback to EMA50, then a bullish candle.
  Signal on the close of candle *i*, entry at the open of *i+1* — no lookahead.
- Stop: low of the entry candle minus 0.5 × ATR14.
- Take profit: 2R (v1). Time exit: 30 candles, at close.
- Risk: 1% per trade, position capped at 100% of equity (spot, no leverage).
- Costs: 0.10% of notional per side, all-in (fee + slippage).
- If stop and take are both hit in one candle, the stop is assumed first
  (conservative).

**v2 variant:** the fixed 2R take profit is replaced by a trailing stop at
the highest high minus 1.5 × ATR14. The stop only ever moves up.

## Results (reference run, Binance Vision data, Jan 2022 – Sep 2026, 10,404 candles, no gaps)

| Version | Trades | Winrate | Profit factor | Return from $10,000 | Max drawdown |
|---|---|---|---|---|---|
| v1 | 151 | 38.4% | 0.88 | −9.8% | −21.9% |
| v2 (trailing) | 199 | 34.7% | 0.98 | −2.0% | −13.9% |

Split for v1: in-sample 2022–2024 **−19.5%**, out-of-sample 2025–2026
**+12.0%**. That out-of-sample plus is a small sample (53 trades) that
contradicts the in-sample result — it is **not** proof of an edge, especially
against buy&hold at **+127%** over the same period. A sensitivity grid
(take profit 1.5R–3R × stop 0.3–1.0 ATR) is mostly negative; the best
post-hoc cell (+10.2%) was chosen after the fact and is labelled as such.

**Verdict, in plain words: neither version is tradable. Do not trade it.**

## What this repo does NOT do

No live trading, no exchange keys, no order code. Historical data only.

## Reproduce it

The monthly Binance Vision klines are **not** included in this repo (size).
Download BTCUSDT 4h spot klines for 2022-01 … 2026-09 from Binance Vision
into `data/` as `BTCUSDT-4h-YYYY-MM.zip`, then:

```bash
pip install -r requirements.txt
python3 backtest_v1.py            # -> trades_v1.csv, results_v1.json
python3 backtest_v2_trailing.py   # -> trades_v2_trailing.csv, results_v2_trailing.json
```

The `trades_*.csv` and `results_*.json` files in this repo are the reference
outputs, so you can check every trade without re-downloading the data.

## Rules for changing the strategy

No silent refits. Changing one parameter at a time creates a new, labelled
variant — never an edit of v1/v2 after seeing their results.
