# Strategy Performance Analytics Layer

## 1. What's Missing Today

Current schema gaps that block profitability analysis:

| Gap | Impact |
|---|---|
| `exit_reason` not on `positions` — only in `bot_logs.data` JSONB | Can't query PnL by exit reason (SL vs TP vs trailing vs strategy) |
| `regime` not persisted on `signals` | Can't measure strategy performance per regime |
| `bars_held` / `mae_pct` / `mfe_pct` not on `positions` | No holding-time or excursion analysis |
| `strategy_version` not on `positions` | Can't correlate PnL to code changes |
| No equity snapshots | Equity curve only reconstructable from closed positions (misses open drawdown) |
| `confidence` on signals always NULL | No signal-quality scoring |

## 2. Schema Changes

### 2a. Enrich existing tables

```sql
-- signals: persist regime (already computed every bar, just not stored)
ALTER TABLE signals ADD COLUMN regime VARCHAR(16);  -- TREND_UP / TREND_DOWN / RANGE

-- positions: capture exit metadata and excursion
ALTER TABLE positions ADD COLUMN exit_reason VARCHAR(32);      -- STOP_LOSS / TAKE_PROFIT / TRAILING_STOP / REGIME_FLIP / TIME_EXIT / STRATEGY_EXIT
ALTER TABLE positions ADD COLUMN bars_held INTEGER;            -- number of candles position was open
ALTER TABLE positions ADD COLUMN mae_pct DOUBLE PRECISION;     -- max adverse excursion (% from entry)
ALTER TABLE positions ADD COLUMN mfe_pct DOUBLE PRECISION;     -- max favorable excursion (% from entry)
ALTER TABLE positions ADD COLUMN strategy_version VARCHAR(16); -- git short hash at open time
```

### 2b. New analytics tables

```sql
-- Periodic portfolio snapshot for equity curve reconstruction
CREATE TABLE equity_snapshots (
    id             BIGSERIAL PRIMARY KEY,
    ts             TIMESTAMPTZ NOT NULL DEFAULT now(),
    balance        DOUBLE PRECISION NOT NULL,       -- free USDT
    locked_value   DOUBLE PRECISION NOT NULL,       -- sum(qty * current_price) across open positions
    total_equity   DOUBLE PRECISION NOT NULL,       -- balance + locked_value
    open_positions INTEGER NOT NULL,
    source         VARCHAR(16) NOT NULL DEFAULT 'tick'  -- 'tick' / 'startup' / 'manual'
);

CREATE INDEX equity_snapshots_ts ON equity_snapshots (ts);

-- Daily aggregated analytics
CREATE TABLE analytics_daily (
    day                  DATE NOT NULL,
    symbol               VARCHAR(16) NOT NULL DEFAULT '*',

    -- signal stats
    signals_total        INTEGER NOT NULL DEFAULT 0,
    signals_buy          INTEGER NOT NULL DEFAULT 0,
    signals_sell         INTEGER NOT NULL DEFAULT 0,
    signals_hold         INTEGER NOT NULL DEFAULT 0,

    -- decision stats
    decisions_approved   INTEGER NOT NULL DEFAULT 0,
    decisions_rejected   INTEGER NOT NULL DEFAULT 0,
    decisions_no_action  INTEGER NOT NULL DEFAULT 0,

    -- trade stats
    trades_opened        INTEGER NOT NULL DEFAULT 0,
    trades_closed        INTEGER NOT NULL DEFAULT 0,
    volume_traded        DOUBLE PRECISION NOT NULL DEFAULT 0,

    -- PnL
    realized_pnl         DOUBLE PRECISION NOT NULL DEFAULT 0,
    total_fees           DOUBLE PRECISION NOT NULL DEFAULT 0,

    -- derived
    win_rate             DOUBLE PRECISION,        -- NULL if no closed trades
    avg_pnl_per_trade    DOUBLE PRECISION,
    profit_factor        DOUBLE PRECISION,        -- gross_profit / |gross_loss|

    PRIMARY KEY (day, symbol)
);

CREATE INDEX analytics_daily_day ON analytics_daily (day DESC);
```

## 3. Metric Definitions & SQL

### 3a. Exit Reason Performance

After adding `exit_reason` to `positions`:

```sql
SELECT
    exit_reason,
    COUNT(*)                                    AS trades,
    ROUND(AVG(realized_pnl)::numeric, 4)        AS avg_pnl,
    ROUND(SUM(realized_pnl)::numeric, 4)        AS total_pnl,
    ROUND((COUNT(*) FILTER (WHERE realized_pnl > 0) * 100.0 / COUNT(*))::numeric, 2) AS win_rate_pct,
    ROUND(AVG(EXTRACT(EPOCH FROM (closed_at - opened_at)) / 3600)::numeric, 2) AS avg_hold_hours
FROM positions
WHERE status = 'closed'
  AND closed_at IS NOT NULL
GROUP BY exit_reason
ORDER BY total_pnl DESC;
```

### 3b. Regime-Based Performance

After adding `regime` to `signals`, join signals -> decisions -> trades -> positions:

```sql
SELECT
    s.regime,
    s.signal,
    COUNT(DISTINCT p.id)                                AS closed_positions,
    ROUND(AVG(p.realized_pnl)::numeric, 4)              AS avg_pnl,
    ROUND(SUM(p.realized_pnl)::numeric, 4)              AS total_pnl,
    ROUND((COUNT(*) FILTER (WHERE p.realized_pnl > 0) * 100.0 / NULLIF(COUNT(*), 0))::numeric, 2) AS win_rate_pct
FROM signals s
JOIN decisions d ON d.signal_id = s.id
JOIN trades t ON t.decision_id = d.id AND t.side = 'buy'
JOIN positions p ON p.buy_trade_id = t.id AND p.status = 'closed'
GROUP BY s.regime, s.signal
ORDER BY s.regime, total_pnl DESC;
```

### 3c. Signal-to-Trade Conversion Funnel

Already computable from existing data:

```sql
WITH signal_counts AS (
    SELECT symbol, signal, COUNT(*) AS cnt
    FROM signals
    WHERE ts >= now() - INTERVAL '7 days'
    GROUP BY symbol, signal
),
decision_counts AS (
    SELECT s.symbol, s.signal,
           COUNT(*) FILTER (WHERE d.decision = 'APPROVED')  AS approved,
           COUNT(*) FILTER (WHERE d.decision = 'REJECTED')  AS rejected,
           COUNT(*) FILTER (WHERE d.decision = 'NO_ACTION') AS no_action
    FROM signals s
    JOIN decisions d ON d.signal_id = s.id
    WHERE s.ts >= now() - INTERVAL '7 days'
    GROUP BY s.symbol, s.signal
),
trade_counts AS (
    SELECT s.symbol, s.signal, COUNT(t.id) AS filled
    FROM signals s
    JOIN decisions d ON d.signal_id = s.id
    JOIN trades t ON t.decision_id = d.id
    WHERE s.ts >= now() - INTERVAL '7 days'
    GROUP BY s.symbol, s.signal
)
SELECT
    sc.symbol,
    sc.signal,
    sc.cnt                                              AS signals,
    COALESCE(dc.approved, 0)                            AS approved,
    COALESCE(dc.rejected, 0)                            AS rejected,
    COALESCE(dc.no_action, 0)                           AS no_action,
    COALESCE(tc.filled, 0)                              AS filled,
    ROUND((COALESCE(dc.approved, 0) * 100.0 / sc.cnt)::numeric, 1) AS approval_rate_pct,
    ROUND((COALESCE(tc.filled, 0) * 100.0 / NULLIF(COALESCE(dc.approved, 0), 0))::numeric, 1) AS fill_rate_pct
FROM signal_counts sc
LEFT JOIN decision_counts dc ON dc.symbol = sc.symbol AND dc.signal = sc.signal
LEFT JOIN trade_counts tc ON tc.symbol = sc.symbol AND tc.signal = sc.signal
ORDER BY sc.signal, sc.symbol;
```

### 3d. Holding Time Distribution

After adding `bars_held`:

```sql
SELECT
    exit_reason,
    COUNT(*)                                                     AS n,
    ROUND(AVG(bars_held)::numeric, 1)                            AS avg_bars,
    ROUND((PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY bars_held))::numeric, 1) AS p50_bars,
    ROUND((PERCENTILE_CONT(0.9) WITHIN GROUP (ORDER BY bars_held))::numeric, 1) AS p90_bars,
    MIN(bars_held)                                               AS min_bars,
    MAX(bars_held)                                               AS max_bars
FROM positions
WHERE status = 'closed' AND bars_held IS NOT NULL
GROUP BY exit_reason
ORDER BY avg_bars DESC;
```

MAE/MFE analysis:

```sql
SELECT
    exit_reason,
    ROUND(AVG(mae_pct)::numeric, 4)  AS avg_mae_pct,
    ROUND(AVG(mfe_pct)::numeric, 4)  AS avg_mfe_pct,
    ROUND(AVG(mfe_pct / NULLIF(ABS(mae_pct), 0))::numeric, 2) AS mfe_mae_ratio
FROM positions
WHERE status = 'closed' AND mae_pct IS NOT NULL
GROUP BY exit_reason;
```

### 3e. Equity Curve Reconstruction

From snapshots (requires `equity_snapshots` table):

```sql
SELECT ts, total_equity, balance, locked_value
FROM equity_snapshots
ORDER BY ts;
```

Reconstructed from closed positions (no new table needed):

```sql
WITH daily_pnl AS (
    SELECT
        closed_at::date AS day,
        SUM(realized_pnl) AS day_pnl
    FROM positions
    WHERE status = 'closed'
    GROUP BY closed_at::date
),
cumulative AS (
    SELECT
        day,
        day_pnl,
        SUM(day_pnl) OVER (ORDER BY day) AS cumulative_pnl
    FROM daily_pnl
)
SELECT day, day_pnl, cumulative_pnl
FROM cumulative
ORDER BY day;
```

### 3f. Strategy Version Performance

After adding `strategy_version` to `positions`:

```sql
SELECT
    strategy_version,
    COUNT(*)                                               AS trades,
    ROUND(AVG(realized_pnl)::numeric, 4)                   AS avg_pnl,
    ROUND(SUM(realized_pnl)::numeric, 4)                   AS total_pnl,
    ROUND((COUNT(*) FILTER (WHERE realized_pnl > 0) * 100.0 / COUNT(*))::numeric, 2) AS win_rate_pct
FROM positions
WHERE status = 'closed'
GROUP BY strategy_version
ORDER BY MIN(opened_at) DESC;
```

### 3g. Reject Reason Distribution

Already computable:

```sql
SELECT
    reject_reason,
    COUNT(*)                                              AS n,
    ROUND(AVG(proposed_qty)::numeric, 6)                  AS avg_qty,
    ROUND(AVG(available_balance)::numeric, 2)             AS avg_balance
FROM decisions
WHERE decision = 'REJECTED'
GROUP BY reject_reason
ORDER BY n DESC;
```

### 3h. Slippage Analysis

Signal price vs actual fill price:

```sql
SELECT
    t.side,
    COUNT(*)                                                    AS n,
    ROUND(AVG(t.fill_price - s.close_price)::numeric, 6)       AS avg_slippage_abs,
    ROUND(AVG((t.fill_price - s.close_price) / s.close_price * 100)::numeric, 4) AS avg_slippage_pct
FROM trades t
JOIN decisions d ON d.id = t.decision_id
JOIN signals s ON s.id = d.signal_id
WHERE s.close_price IS NOT NULL
GROUP BY t.side;
```

## 4. Materialized View (Daily Rollup)

```sql
CREATE MATERIALIZED VIEW mv_daily_stats AS
SELECT
    s.ts::date                                                      AS day,
    s.symbol,
    COUNT(*) FILTER (WHERE s.signal = 'BUY')                       AS buy_signals,
    COUNT(*) FILTER (WHERE s.signal = 'SELL')                      AS sell_signals,
    COUNT(*) FILTER (WHERE d.decision = 'APPROVED')                AS approved,
    COUNT(*) FILTER (WHERE d.decision = 'REJECTED')                AS rejected,
    COUNT(DISTINCT t.id) FILTER (WHERE t.side = 'buy')             AS buys_filled,
    COUNT(DISTINCT t.id) FILTER (WHERE t.side = 'sell')            AS sells_filled,
    COUNT(DISTINCT p.id) FILTER (WHERE p.status = 'closed')        AS positions_closed,
    COALESCE(SUM(p.realized_pnl) FILTER (WHERE p.status = 'closed'), 0) AS realized_pnl,
    COALESCE(SUM(t.fee) FILTER (WHERE t.fee IS NOT NULL), 0)       AS total_fees
FROM signals s
LEFT JOIN decisions d ON d.signal_id = s.id
LEFT JOIN trades t ON t.decision_id = d.id
LEFT JOIN positions p ON (p.buy_trade_id = t.id OR p.sell_trade_id = t.id)
GROUP BY s.ts::date, s.symbol;

CREATE UNIQUE INDEX mv_daily_stats_day_symbol ON mv_daily_stats (day, symbol);
```

Refresh: `REFRESH MATERIALIZED VIEW CONCURRENTLY mv_daily_stats;`

## 5. Code Changes Required

Only 3 files touched, no trading logic changed:

### `src/database/orm.py`
- `SignalORM.regime` (String, nullable)
- `PositionORM.exit_reason` (String, nullable)
- `PositionORM.bars_held` (Integer, nullable)
- `PositionORM.mae_pct` (Double, nullable)
- `PositionORM.mfe_pct` (Double, nullable)
- `PositionORM.strategy_version` (String, nullable)

### `src/engine/trading_engine.py`
- Pass `regime=str(row["regime"])` into `SignalRecord`
- Pass `exit_reason`, `bars_held`, `mae_pct`, `mfe_pct`, `strategy_version` into `open_position()`/`close_position()` calls
- Compute MAE/MFE from `portfolio.position_extreme` at close time

### `src/storage/position_repo.py`
- `open_position()`: accept `strategy_version` param
- `close_position()`: accept `exit_reason`, `bars_held`, `mae_pct`, `mfe_pct` params

### New migration
Alembic autogenerate for 6 new columns + 2 new tables.

### Optional: `src/storage/analytics_repo.py` (new)
- `insert_equity_snapshot()` — called once per tick from engine
- `upsert_daily_analytics()` — called end-of-day or via cron

## 6. Summary: What Each Table Gains

| Table | New Columns | Enables |
|---|---|---|
| `signals` | `regime` | Regime-based performance, signal quality by market condition |
| `positions` | `exit_reason`, `bars_held`, `mae_pct`, `mfe_pct`, `strategy_version` | Exit reason PnL, holding time stats, excursion analysis, version attribution |
| `equity_snapshots` | (new table) | Real-time equity curve, max drawdown, Sharpe-adjacent ratios |
| `analytics_daily` | (new table) | Pre-computed daily dashboards, no heavy joins at query time |

All metrics computable with zero trading logic changes. Only data already in memory at decision time gets persisted.
