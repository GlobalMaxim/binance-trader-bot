# candles

Raw OHLCV market data from Binance. Single source of truth for all price data. All indicators, signals, and backtests derive from this table.

## Fields

| Column    | Type              | Description                                    |
|-----------|-------------------|------------------------------------------------|
| symbol    | TEXT              | Trading pair: `BTC/USDT`, `ETH/USDT`          |
| timeframe | TEXT              | Candle interval: `1m`, `15m`, `1h`            |
| ts        | TIMESTAMPTZ       | Candle open timestamp (UTC), from exchange     |
| open      | DOUBLE PRECISION  | Opening price                                  |
| high      | DOUBLE PRECISION  | Highest price in interval                      |
| low       | DOUBLE PRECISION  | Lowest price in interval                       |
| close     | DOUBLE PRECISION  | Closing price                                  |
| volume    | DOUBLE PRECISION  | Base asset volume traded                       |

## Constraints

- **Primary key**: `(symbol, timeframe, ts)` — composite natural key, no surrogate needed

## Indexes

| Name                | Columns                      | Purpose                            |
|---------------------|------------------------------|------------------------------------|
| `candles_pk`        | (symbol, timeframe, ts)      | Primary key (automatic)            |
| `candles_sym_tf_ts` | (symbol, timeframe, ts DESC) | Latest-N lookup for indicator warmup |

## Upsert Semantics

`INSERT … ON CONFLICT (symbol, timeframe, ts) DO UPDATE` — re-fetched candles overwrite OHLCV in place. Volume may grow if exchange reports late trades. Latest data wins by design.

## Relationships

- → **signals**: JOIN on `(symbol, timeframe, ts)`

## Example

```
symbol    | BTC/USDT
timeframe | 15m
ts        | 2026-06-07 14:00:00+00
open      | 87250.00
high      | 87310.50
low       | 87240.00
close     | 87295.75
volume    | 12.453
```
