# signals

Frozen snapshot of strategy output per candle. Stores signal (BUY/SELL/HOLD) and all indicator values at decision time — enough to debug *why* the strategy fired without recomputing from candles.

## Fields

| Column           | Type              | Description                                              |
|------------------|-------------------|----------------------------------------------------------|
| id               | BIGSERIAL         | Surrogate PK                                             |
| symbol           | TEXT              | Trading pair                                             |
| timeframe        | TEXT              | Candle interval                                          |
| ts               | TIMESTAMPTZ       | Candle timestamp that triggered this signal              |
| created_at       | TIMESTAMPTZ       | Wall clock when signal was computed. Default `now()`.    |
| signal           | TEXT              | `BUY`, `SELL`, or `HOLD`                                 |
| rsi              | DOUBLE PRECISION  | RSI-14 at decision time                                  |
| ema_fast         | DOUBLE PRECISION  | EMA-20 at decision time                                  |
| ema_slow         | DOUBLE PRECISION  | EMA-50 at decision time                                  |
| macd             | DOUBLE PRECISION  | MACD line                                                |
| macd_signal      | DOUBLE PRECISION  | MACD signal line                                         |
| macd_hist        | DOUBLE PRECISION  | MACD histogram                                           |
| bb_upper         | DOUBLE PRECISION  | Bollinger Band upper                                     |
| bb_middle        | DOUBLE PRECISION  | Bollinger Band middle (SMA-20)                           |
| bb_lower         | DOUBLE PRECISION  | Bollinger Band lower                                     |
| close_price      | DOUBLE PRECISION  | Close price at decision time (source for slippage calc)  |
| strategy_version | TEXT              | Git tag or commit hash of strategy code                  |
| reason           | TEXT              | Rule tag that fired: e.g. `rsi_oversold+ema_cross`       |
| confidence       | DOUBLE PRECISION  | 0–1 signal strength (reserved)                           |

## Constraints

- **Primary key**: `id` (BIGSERIAL)
- **Unique**: `(symbol, timeframe, ts)` — one signal per candle in live trading. Relax for backtest replays.

## Indexes

| Name                  | Columns                 | Purpose                             |
|-----------------------|-------------------------|-------------------------------------|
| `signals_pk`          | (id)                    | Primary key                         |
| `signals_symbol_ts`   | (symbol, timeframe, ts) | JOIN to candles; time-range queries |
| `signals_signal_ts`   | (signal, ts)            | Count BUY/SELL/HOLD by time window  |
| `signals_version_ts`  | (strategy_version, ts)  | Compare versions by signal output   |

## Relationships

- ← **candles**: JOIN on `(symbol, timeframe, ts)`
- → **decisions**: `signals.id` → `decisions.signal_id` (1:1)

## Implementation Notes

- **Always insert HOLD rows.** A missing row means the pipeline didn't run. A HOLD row proves it ran and chose inaction.
- **Freeze indicator values.** Recomputing from candles risks drift if parameters change. `signals` is the authoritative record of what the strategy saw.
- **`reason` field**: `SELECT reason, count(*) WHERE signal='BUY' GROUP BY reason` shows which rules dominate. One rule firing 90% of the time indicates overfitted thresholds.
- **`strategy_version`**: Required for A/B comparison between deploys. `GROUP BY strategy_version, signal` reveals distribution shifts.

## Example

```
id               | 1423
symbol           | BTC/USDT
timeframe        | 15m
ts               | 2026-06-07 14:15:00+00
created_at       | 2026-06-07 14:15:02+00
signal           | BUY
rsi              | 32.5
ema_fast         | 87150.30
ema_slow         | 86980.10
macd             | -45.20
macd_signal      | -50.10
macd_hist        | 4.90
bb_upper         | 87500.00
bb_middle        | 87200.00
bb_lower         | 86900.00
close_price      | 87295.75
strategy_version | v1.2.0
reason           | rsi_oversold+macd_turning
confidence       | NULL
```
