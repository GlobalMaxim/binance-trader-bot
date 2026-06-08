# System Architecture

## Pipeline

```
candles → signals → decisions → trades → positions
                                    └──────────────▸ bot_logs (every step)
```

Each tick, `TradingEngine` runs the full chain per symbol:

```
fetch_candles()             → upsert_candles()        [candles table]
compute_all_indicators()    → generate_signals()
INSERT signal row                                      [signals table]
risk.evaluate()             → INSERT decision row      [decisions table]
  APPROVED → execute_market_*() → INSERT trade row    [trades table]
  APPROVED → portfolio.open/close_position()
           → INSERT / UPDATE position row             [positions table]
every event → INSERT log row                          [bot_logs table]
```

## Module → Table Map

| Module                      | Reads                   | Writes              |
|-----------------------------|-------------------------|---------------------|
| `collector/ohlcv.py`        | —                       | candles             |
| `features/indicators.py`    | candles (in-memory)     | —                   |
| `strategy/signals.py`       | indicators (in-memory)  | —                   |
| `storage/candle_repo.py`    | —                       | candles             |
| `engine/trading_engine.py`  | candles, positions      | signals, decisions, positions, bot_logs |
| `risk/risk.py`              | —                       | —  (pure function)  |
| `execution/executor.py`     | —                       | trades              |

## Table Relationships

```
candles (symbol, timeframe, ts) ──▸ signals  (JOIN on symbol/timeframe/ts)
signals.id  ──▸  decisions.signal_id   (1:1)
decisions.id ──▸  trades.decision_id   (1:1, APPROVED only)
trades.id   ──▸  positions.buy_trade_id / sell_trade_id
```

## TradingEngine: Startup Sequence

1. `SELECT * FROM positions WHERE status = 'open'` — restore `PortfolioState`
2. For each open position: fetch fill price/qty from linked `trades` row
3. signals / decisions / trades: write-only during live operation

## TradingEngine: Per-Tick Writes

| Step | Table | Operation |
|------|-------|-----------|
| After fetch | candles | `INSERT … ON CONFLICT DO UPDATE` |
| After strategy | signals | `INSERT` — always, including HOLD |
| After risk | decisions | `INSERT` — always, including REJECTED |
| After execution | trades | `INSERT` — APPROVED only |
| After BUY fill | positions | `INSERT` (status=open) |
| After SELL fill | positions | `UPDATE` (status=closed, fill exit data) |
| Every event | bot_logs | `INSERT` |

**Insert HOLD and REJECTED rows** — gaps in these tables mean the pipeline didn't run, not that it chose inaction.

## Crash Recovery

- Restore open positions: `SELECT * FROM positions WHERE status = 'open'`
- Candles: re-fetch from exchange on restart; upsert handles duplicates
- signals: use `ON CONFLICT DO NOTHING` on `(symbol, timeframe, ts)` for live restarts

## Naming Conventions

- Tables: plural, lowercase, `snake_case`
- Columns: singular, lowercase, `snake_case`
- Indexes: `{table}_{descriptive_suffix}`
- Enum values: `UPPERCASE_WITH_UNDERSCORES`
- Timestamps: always `TIMESTAMPTZ` / UTC; event time → `ts`; wall clock → `*_at`

## Key Analysis Queries

**Win rate per symbol**
```sql
SELECT symbol,
       count(*) AS closed,
       count(*) FILTER (WHERE realized_pnl > 0) AS winners,
       round(100.0 * count(*) FILTER (WHERE realized_pnl > 0) / count(*), 1) AS win_pct,
       round(avg(realized_pnl), 4) AS avg_pnl
FROM positions WHERE status = 'closed'
GROUP BY symbol ORDER BY avg_pnl DESC;
```

**Rejection breakdown**
```sql
SELECT reject_reason, count(*) AS n,
       round(100.0 * count(*) / (SELECT count(*) FROM decisions), 1) AS pct
FROM decisions WHERE decision = 'REJECTED'
GROUP BY reject_reason ORDER BY n DESC;
```

**Slippage: decision price vs fill price**
```sql
SELECT t.symbol, t.side,
       round(avg(t.fill_price - s.close_price), 4) AS avg_slippage,
       round(max(t.fill_price - s.close_price), 4) AS max_slippage
FROM trades t
JOIN decisions d ON d.id = t.decision_id
JOIN signals  s ON s.id = d.signal_id
GROUP BY 1, 2;
```

**Full lifecycle trace**
```sql
SELECT s.signal, s.reason, d.decision, d.reject_reason,
       t.side, t.fill_price, p.realized_pnl, p.status
FROM signals s
JOIN decisions d ON d.signal_id = s.id
LEFT JOIN trades    t ON t.decision_id = d.id
LEFT JOIN positions p ON p.buy_trade_id = t.id OR p.sell_trade_id = t.id
WHERE s.symbol = 'BTC/USDT' ORDER BY s.ts DESC LIMIT 10;
```

**Signal distribution by strategy version**
```sql
SELECT strategy_version, signal, count(*)
FROM signals GROUP BY 1, 2 ORDER BY 1, 2;
```

## Summary

| Table | Purpose | Grows with |
|-------|---------|------------|
| [candles](database/candles.md) | Raw OHLCV from exchange | symbols × candles |
| [signals](database/signals.md) | Strategy output snapshot | every tick |
| [decisions](database/decisions.md) | Risk evaluation result | every tick |
| [trades](database/trades.md) | Executed orders | every fill |
| [positions](database/positions.md) | Portfolio holdings lifecycle | every round-trip |
| [bot_logs](database/logs.md) | Structured operational events | every event |
