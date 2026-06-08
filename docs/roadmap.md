# Roadmap

## Short-Term

| Change | Rationale |
|--------|-----------|
| `exchange` column on `candles` | Multi-exchange support. Currently implicit as Binance. |
| `fee_asset` on `trades` | Fees may be in BNB, not quote currency. |
| `config` JSONB on `signals` | Freeze full strategy config (RSI period, EMA periods) per signal. Currently only `strategy_version`. |
| `latency_ms` on `decisions` | Measure risk evaluation time. |
| `latency_ms` on `trades` | Measure order placement round-trip. |

## Medium-Term

| Change | Rationale |
|--------|-----------|
| `market_snapshots` table | Order book depth at decision time for slippage modeling. |
| `strategy_configs` table | Versioned config parameters. JOIN to `signals.strategy_version`. |
| `daily_summary` materialized view | Pre-computed daily PnL, trade count, win rate for dashboards. |
| Partition `candles` by month | Performance at scale (millions of rows). |
| Partition `bot_logs` by week | Easy pruning: `DROP TABLE bot_logs_2026_w23`. |

## Long-Term

| Change | Rationale |
|--------|-----------|
| `portfolio_snapshots` table | Hourly balance + position snapshots for equity curve. |
| `signal_backtests` table | Store backtest results separately from live signals. Different unique constraint. |
| `strategy_name` on `signals` | Multi-strategy support. Run N strategies on same candles, compare. |
| `paper` boolean on `trades` | Paper trading mode. Same pipeline, simulated fills. |
| Event sourcing for `positions` | Replace mutable rows with append-only `position_events`. Full audit trail of position changes. |
