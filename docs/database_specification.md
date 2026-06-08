# Trading Bot Database Specification

Version 1.0 — 2026-06-07

---

## Architecture Overview

```
┌──────────┐     ┌──────────┐     ┌───────────┐     ┌──────────┐     ┌───────────┐
│ candles  │────▸│ signals  │────▸│ decisions  │────▸│  trades  │────▸│ positions │
│ (market  │     │ (strategy│     │ (risk      │     │(execution│     │ (portfolio│
│  data)   │     │  output) │     │  evaluate) │     │  result) │     │  state)   │
└──────────┘     └──────────┘     └───────────┘     └──────────┘     └───────────┘
                                                            
                    ┌───────────┐                            
                    │ bot_logs  │                            
                    │(structured│                            
                    │  events)  │                            
                    └───────────┘                            
```

**Flow direction:** Each tick, TradingEngine reads latest candles, runs strategy to produce a signal, passes signal through risk to produce a decision, sends approved decisions to execution to produce a trade, and updates portfolio positions. Every step writes its output to its own table. Nothing is in-memory-only across ticks except the live `PortfolioState` object (which is backed by the `positions` table for recovery).

---

## Table Relationships

```
candles (symbol, timeframe, ts) ──┐
                                  │ 1:1 (same symbol/timeframe/ts)
                                  ▼
                            signals.symbol, signals.timeframe, signals.ts
                                  │
                                  │ 1:1 (signal_id)
                                  ▼
                            decisions.signal_id
                                  │
                                  │ 1:1 (decision_id)
                                  ▼
                            trades.decision_id
                                  │
                                  │ updates on fill
                                  ▼
                            positions (symbol-level, open/closed)
```

- **candles → signals**: One signal per processed candle. JOIN on `(symbol, timeframe, ts)`.
- **signals → decisions**: One decision per signal. JOIN on `signal_id`.
- **decisions → trades**: One trade per approved decision. JOIN on `decision_id`. Rejected decisions have no trade row.
- **trades → positions**: Positions are symbol-level aggregates. Each BUY trade opens or adds to a position. Each SELL trade closes or reduces a position.

---

## candles

### Purpose
Raw OHLCV market data fetched from Binance. The single source of truth for all price data. Every downstream computation (indicators, signals, backtests) derives from this table.

### Fields

| Field      | Type              | Description                                          |
|------------|-------------------|------------------------------------------------------|
| symbol     | TEXT              | Trading pair, e.g. `BTC/USDT`, `ETH/USDT`            |
| timeframe  | TEXT              | Candle interval, e.g. `1m`, `15m`, `1h`              |
| ts         | TIMESTAMPTZ       | Candle open timestamp (UTC). From exchange.          |
| open       | DOUBLE PRECISION  | Opening price                                        |
| high       | DOUBLE PRECISION  | Highest price in interval                            |
| low        | DOUBLE PRECISION  | Lowest price in interval                             |
| close      | DOUBLE PRECISION  | Closing price (latest price in interval)             |
| volume     | DOUBLE PRECISION  | Base asset volume traded in interval                 |

### Primary Key
`(symbol, timeframe, ts)` — composite natural key. No surrogate needed. One row per candle per symbol per timeframe.

### Indexes

| Index                  | Columns                       | Purpose                                   |
|------------------------|-------------------------------|-------------------------------------------|
| `candles_pk`           | (symbol, timeframe, ts)       | Primary key (automatic)                   |
| `candles_sym_tf_ts`    | (symbol, timeframe, ts DESC)  | Latest-N lookup per symbol for indicator warmup |

### Upsert Semantics
`INSERT … ON CONFLICT (symbol, timeframe, ts) DO UPDATE` — re-fetched candles update OHLCV in place. Volume may grow if exchange reports late trades. This is intentional: latest data wins.

### Example Record

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

### Why This Table Matters
- **Backtesting foundation**: Replay historical candles through strategy to validate performance.
- **Indicator reproducibility**: All indicators derive from OHLCV. If you have candles, you can recompute any indicator with any parameters.
- **Data quality audit**: `SELECT symbol, timeframe, count(*), max(ts), min(ts)` shows data coverage gaps instantly.
- **Exchange-agnostic**: Standard OHLCV format. Swap Binance for any other exchange without schema changes.

---

## signals

### Purpose
Frozen snapshot of what the strategy decided at each candle close. Stores the signal (BUY/SELL/HOLD), all indicator values at decision time, and enough context to debug *why* the strategy made that call without recomputing from candles.

### Fields

| Field            | Type              | Description                                               |
|------------------|-------------------|-----------------------------------------------------------|
| id               | BIGSERIAL         | Surrogate PK for foreign key references                   |
| symbol           | TEXT              | Trading pair                                              |
| timeframe        | TEXT              | Candle interval                                           |
| ts               | TIMESTAMPTZ       | Candle close timestamp that triggered this signal         |
| created_at       | TIMESTAMPTZ       | When signal was computed (wall clock). Default `now()`.   |
| signal           | TEXT              | `BUY`, `SELL`, or `HOLD`                                  |
| rsi              | DOUBLE PRECISION  | RSI-14 value at decision time                             |
| ema_fast         | DOUBLE PRECISION  | Fast EMA value (period 20) at decision time               |
| ema_slow         | DOUBLE PRECISION  | Slow EMA value (period 50) at decision time               |
| macd             | DOUBLE PRECISION  | MACD line value                                           |
| macd_signal      | DOUBLE PRECISION  | MACD signal line value                                    |
| macd_hist        | DOUBLE PRECISION  | MACD histogram value                                      |
| bb_upper         | DOUBLE PRECISION  | Bollinger Band upper                                      |
| bb_middle        | DOUBLE PRECISION  | Bollinger Band middle (SMA-20)                            |
| bb_lower         | DOUBLE PRECISION  | Bollinger Band lower                                      |
| close_price      | DOUBLE PRECISION  | Close price used for decision (from candle)               |
| strategy_version | TEXT              | Git tag or commit hash of strategy code at runtime        |
| reason           | TEXT              | Rule tag that fired, e.g. `rsi_oversold+ema_cross`       |
| confidence       | DOUBLE PRECISION  | 0–1 signal strength (reserved for future use)             |

### Primary Key
`id` (BIGSERIAL) — surrogate key. The natural key `(symbol, timeframe, ts)` is guaranteed unique per candle but signals may be recomputed for the same candle during backtests or strategy iterations. Use `UNIQUE (symbol, timeframe, ts)` with a version discriminator if needed.

### Unique Constraint
`UNIQUE (symbol, timeframe, ts)` — one signal per candle in live trading. Drop or relax for backtesting replays.

### Indexes

| Index                    | Columns                     | Purpose                                       |
|--------------------------|-----------------------------|-----------------------------------------------|
| `signals_pk`             | (id)                        | Primary key                                   |
| `signals_symbol_ts`      | (symbol, timeframe, ts)     | JOIN to candles; time-range queries           |
| `signals_signal_ts`      | (signal, ts)                | Count BUY/SELL/HOLD over time windows         |
| `signals_version_ts`     | (strategy_version, ts)      | Compare strategy version performance          |

### Relationships
- **candles**: JOIN on `(symbol, timeframe, ts)` to get full OHLCV context.
- **decisions**: `signals.id` → `decisions.signal_id`. One signal produces one decision row.

### Example Record

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

### Why This Table Matters
- **Debugging without recomputation**: Indicator values frozen at decision time. No risk of lookback-window drift or parameter changes contaminating the analysis.
- **HOLD coverage**: `signal='HOLD'` rows prove the strategy evaluated a candle and chose inaction. Without HOLD rows, you can't distinguish "strategy ran and held" from "strategy wasn't running."
- **Strategy iteration**: `GROUP BY strategy_version, signal` shows how signal distribution changes across versions. If v1.3 suddenly emits 3x more BUYs, you see it immediately.
- **Reason distribution**: `SELECT reason, count(*) WHERE signal='BUY' GROUP BY reason` tells you which rules fire most. If one rule dominates, thresholds may be too loose.

---

## decisions

### Purpose
Records the output of the risk management layer. For every signal, risk evaluates position sizing, balance checks, and exposure limits. The decision row captures whether the signal was approved or rejected, and why.

### Fields

| Field             | Type              | Description                                             |
|-------------------|-------------------|---------------------------------------------------------|
| id                | BIGSERIAL         | Surrogate PK                                            |
| signal_id         | BIGINT            | FK to `signals.id`                                      |
| created_at        | TIMESTAMPTZ       | When risk evaluation completed. Default `now()`.        |
| decision          | TEXT              | `APPROVED` or `REJECTED`                                |
| reject_reason     | TEXT              | Enum: `NOTIONAL_TOO_LOW`, `INSUFFICIENT_BALANCE`, `MAX_POSITIONS`, or NULL if approved |
| proposed_qty      | DOUBLE PRECISION  | Position size risk calculated before checks             |
| capital_pct       | DOUBLE PRECISION  | Risk config `capital_pct` used (e.g. 0.02 = 2%)        |
| min_notional      | DOUBLE PRECISION  | Risk config `min_notional` threshold at evaluation time |
| available_balance | DOUBLE PRECISION  | Portfolio balance at evaluation time                    |
| open_positions    | INT               | Count of currently open positions                       |

### Primary Key
`id` (BIGSERIAL)

### Indexes

| Index                      | Columns                | Purpose                                    |
|----------------------------|------------------------|--------------------------------------------|
| `decisions_pk`             | (id)                   | Primary key                                |
| `decisions_signal_id`      | (signal_id)            | JOIN to signals; unique lookup             |
| `decisions_decision_ts`    | (decision, created_at) | Rejection rate over time                   |
| `decisions_reject_reason`  | (reject_reason)        | Group rejections by reason                 |

### Relationships
- **signals**: `decisions.signal_id` → `signals.id`. One-to-one.
- **trades**: `decisions.id` → `trades.decision_id`. One-to-one (only for APPROVED).

### Example Record (Rejected)

```
id                | 982
signal_id         | 1423
created_at        | 2026-06-07 14:15:02+00
decision          | REJECTED
reject_reason     | INSUFFICIENT_BALANCE
proposed_qty      | 0.0023
capital_pct       | 0.02
min_notional      | 10.00
available_balance | 8.50
open_positions    | 1
```

### Example Record (Approved)

```
id                | 983
signal_id         | 1500
created_at        | 2026-06-07 15:00:01+00
decision          | APPROVED
reject_reason     | NULL
proposed_qty      | 0.0023
capital_pct       | 0.02
min_notional      | 10.00
available_balance | 9876.50
open_positions    | 0
```

### Why This Table Matters
- **Risk calibration**: `SELECT reject_reason, count(*) GROUP BY reject_reason` shows which risk rule blocks most. If `NOTIONAL_TOO_LOW` fires constantly, raise `capital_pct` or lower `min_notional`.
- **Signal quality measurement**: A strategy with 100 BUY signals and 95 approvals is different from one with 100 signals and 10 approvals. Without this table, you can't distinguish "strategy is bad" from "risk rules are too tight."
- **Capital efficiency**: Track `available_balance` over time to see if the bot sits on too much idle cash.
- **Config audit trail**: `capital_pct` and `min_notional` frozen per decision. When you change risk config, you know exactly which decisions used which parameters.

---

## trades

### Purpose
Records every filled order sent to the exchange. This is the execution audit trail — one row per actual trade. Joins back through decisions → signals → candles for full lifecycle traceability.

### Fields

| Field        | Type              | Description                                               |
|--------------|-------------------|-----------------------------------------------------------|
| id           | BIGSERIAL         | Surrogate PK                                              |
| decision_id  | BIGINT            | FK to `decisions.id`                                      |
| exchange     | TEXT              | Exchange name, e.g. `binance`                             |
| order_id     | TEXT              | Exchange-assigned order ID                                |
| symbol       | TEXT              | Trading pair                                              |
| side         | TEXT              | `buy` or `sell`                                           |
| quantity     | DOUBLE PRECISION  | Base asset quantity filled                                |
| fill_price   | DOUBLE PRECISION  | Average fill price (from exchange)                        |
| cost         | DOUBLE PRECISION  | Quote asset cost (`quantity * fill_price`)                |
| fee          | DOUBLE PRECISION  | Trading fee in quote currency (reserved, currently 0 for demo) |
| status       | TEXT              | Order status: `open`, `closed`, `canceled`, `expired`     |
| created_at   | TIMESTAMPTZ       | When order was placed. Default `now()`.                   |
| filled_at    | TIMESTAMPTZ       | When order filled (from exchange `datetime` field)        |

### Primary Key
`id` (BIGSERIAL)

### Indexes

| Index                  | Columns            | Purpose                                    |
|------------------------|--------------------|--------------------------------------------|
| `trades_pk`            | (id)               | Primary key                                |
| `trades_decision_id`   | (decision_id)      | JOIN to decisions                          |
| `trades_symbol_ts`     | (symbol, created_at)| Trade history per symbol                  |
| `trades_order_id`      | (order_id)         | Lookup by exchange order ID                |

### Relationships
- **decisions**: `trades.decision_id` → `decisions.id`. One-to-one. Only APPROVED decisions have a trade row.
- **positions**: Trades are source events. Positions are derived by aggregating trades per symbol.

### Example Record

```
id          | 501
decision_id | 983
exchange    | binance
order_id    | 123456789
symbol      | BTC/USDT
side        | buy
quantity    | 0.0023
fill_price  | 87295.75
cost        | 200.78
fee         | 0.00
status      | closed
created_at  | 2026-06-07 15:00:02+00
filled_at   | 2026-06-07 15:00:03+00
```

### Why This Table Matters
- **Full audit trail**: Every order placed is recorded. If the exchange disputes a fill, you have your own record.
- **PnL calculation**: `SUM(cost) WHERE side='buy'` vs `SUM(cost) WHERE side='sell'` per symbol gives gross PnL. Join with signals for strategy-attributed PnL.
- **Slippage analysis**: Compare `fill_price` to `signals.close_price` (the price at decision time). Delta = slippage.
- **Execution quality**: `filled_at - created_at` = fill latency. Track over time to detect exchange or network degradation.
- **Fee tracking**: When moving to real trading, `fee` column captures actual costs for net PnL.

---

## positions

### Purpose
Tracks the current and historical state of portfolio positions. Each row represents one position lifecycle: opened by a BUY trade, closed by a SELL trade. This is the portfolio's persistent state — `PortfolioState` in the engine reconstructs from this table on startup.

### Fields

| Field         | Type              | Description                                             |
|---------------|-------------------|---------------------------------------------------------|
| id            | BIGSERIAL         | Surrogate PK                                            |
| symbol        | TEXT              | Trading pair                                            |
| buy_trade_id  | BIGINT            | FK to `trades.id` for the opening BUY                   |
| sell_trade_id | BIGINT            | FK to `trades.id` for the closing SELL (NULL if open)   |
| quantity      | DOUBLE PRECISION  | Position size in base asset                             |
| entry_price   | DOUBLE PRECISION  | Average entry price from BUY fill                       |
| exit_price    | DOUBLE PRECISION  | Average exit price from SELL fill (NULL if open)        |
| realized_pnl  | DOUBLE PRECISION  | `(exit_price - entry_price) * quantity` (NULL if open)  |
| status        | TEXT              | `open` or `closed`                                      |
| opened_at     | TIMESTAMPTZ       | When BUY trade was placed                               |
| closed_at     | TIMESTAMPTZ       | When SELL trade was placed (NULL if open)               |

### Primary Key
`id` (BIGSERIAL)

### Indexes

| Index                    | Columns              | Purpose                                   |
|--------------------------|----------------------|-------------------------------------------|
| `positions_pk`           | (id)                 | Primary key                               |
| `positions_symbol_status`| (symbol, status)     | Find open positions per symbol            |
| `positions_opened_at`    | (opened_at)          | Time-range PnL queries                   |
| `positions_buy_trade`    | (buy_trade_id)       | JOIN to trades                            |
| `positions_sell_trade`   | (sell_trade_id)      | JOIN to trades                            |

### Relationships
- **trades (buy)**: `positions.buy_trade_id` → `trades.id`
- **trades (sell)**: `positions.sell_trade_id` → `trades.id`

### Invariant
At most one row per symbol with `status = 'open'`. Enforced by application logic (TradingEngine checks `has_position()` before buying).

### Example Record (Open)

```
id           | 201
symbol       | BTC/USDT
buy_trade_id | 501
sell_trade_id| NULL
quantity     | 0.0023
entry_price  | 87295.75
exit_price   | NULL
realized_pnl | NULL
status       | open
opened_at    | 2026-06-07 15:00:02+00
closed_at    | NULL
```

### Example Record (Closed)

```
id           | 200
symbol       | ETH/USDT
buy_trade_id | 480
sell_trade_id| 495
quantity     | 0.15
entry_price  | 4120.50
exit_price   | 4180.25
realized_pnl | 8.96
status       | closed
opened_at    | 2026-06-07 12:30:05+00
closed_at    | 2026-06-07 14:45:10+00
```

### Why This Table Matters
- **Startup recovery**: If the bot crashes, `SELECT * FROM positions WHERE status='open'` restores `PortfolioState` exactly. No state lost.
- **PnL history**: `SELECT symbol, SUM(realized_pnl), count(*) FROM positions WHERE status='closed' GROUP BY symbol` = strategy performance report.
- **Win rate**: `count(*) FILTER (WHERE realized_pnl > 0)` / `count(*)` per symbol.
- **Hold time analysis**: `closed_at - opened_at` distribution. Are winning trades held longer or shorter than losers?
- **Position sizing audit**: Track whether `quantity` is consistent with risk config over time.

---

## bot_logs

### Purpose
Structured event log for all significant bot actions. Supplements Python `logging` (which goes to stdout/file) with queryable database records. Use for operational monitoring, alerting, and post-mortem debugging of bot behavior.

### Fields

| Field      | Type              | Description                                              |
|------------|-------------------|----------------------------------------------------------|
| id         | BIGSERIAL         | Surrogate PK                                             |
| ts         | TIMESTAMPTZ       | Event timestamp. Default `now()`.                        |
| level      | TEXT              | `INFO`, `WARNING`, `ERROR`                               |
| category   | TEXT              | Pipeline stage: `collector`, `strategy`, `risk`, `execution`, `engine`, `system` |
| event      | TEXT              | Short event name: `tick_start`, `signal_generated`, `risk_rejected`, `order_placed`, `order_filled`, `position_opened`, `position_closed`, `db_error`, `exchange_error` |
| symbol     | TEXT              | Trading pair (NULL for system-wide events)               |
| message    | TEXT              | Human-readable detail                                    |
| data        | JSONB             | Structured payload. Schema varies by event.              |
| trade_id   | BIGINT            | FK to `trades.id` (NULL if not trade-related)            |
| decision_id| BIGINT            | FK to `decisions.id` (NULL if not decision-related)      |

### Primary Key
`id` (BIGSERIAL)

### Indexes

| Index                  | Columns              | Purpose                                   |
|------------------------|----------------------|-------------------------------------------|
| `bot_logs_pk`          | (id)                 | Primary key                               |
| `bot_logs_ts`          | (ts DESC)            | Recent events first                       |
| `bot_logs_level_ts`    | (level, ts)          | Filter errors/warnings                    |
| `bot_logs_category_ts` | (category, ts)       | Filter by pipeline stage                  |
| `bot_logs_event_ts`    | (event, ts)          | Find specific event types                 |
| `bot_logs_symbol_ts`   | (symbol, ts)         | Per-symbol event history                  |

### JSONB Payloads by Event

Event names and their `data` shapes. Not enforced by schema — conventions documented here.

#### `tick_start`
```json
{"balance": 9876.50, "open_positions": ["BTC/USDT"], "symbols": ["BTC/USDT", "ETH/USDT"]}
```

#### `signal_generated`
```json
{"signal": "BUY", "rsi": 32.5, "close_price": 87295.75, "reason": "rsi_oversold+macd_turning"}
```

#### `risk_rejected`
```json
{"reason": "INSUFFICIENT_BALANCE", "available": 8.50, "required": 200.78}
```

#### `order_placed`
```json
{"side": "buy", "quantity": 0.0023, "order_id": "123456789", "status": "open"}
```

#### `order_filled`
```json
{"side": "buy", "quantity": 0.0023, "fill_price": 87295.75, "cost": 200.78, "order_id": "123456789"}
```

#### `position_opened`
```json
{"symbol": "BTC/USDT", "quantity": 0.0023, "entry_price": 87295.75}
```

#### `position_closed`
```json
{"symbol": "BTC/USDT", "realized_pnl": 45.20, "entry_price": 87295.75, "exit_price": 87491.50}
```

#### `exchange_error`
```json
{"error": "RequestTimeout", "endpoint": "createMarketBuyOrder", "symbol": "BTC/USDT", "retry": 2}
```

#### `db_error`
```json
{"error": "ConnectionRefusedError", "operation": "upsert_candles", "retry": 3}
```

### Example Record

```
id          | 10452
ts          | 2026-06-07 15:00:02+00
level       | INFO
category    | execution
event       | order_filled
symbol      | BTC/USDT
message     | BUY filled: 0.0023 BTC/USDT @ 87295.75
data        | {"side": "buy", "quantity": 0.0023, "fill_price": 87295.75, "cost": 200.78, "order_id": "123456789"}
trade_id    | 501
decision_id | 983
```

### Why This Table Matters
- **Operational visibility**: `SELECT * FROM bot_logs WHERE level='ERROR' AND ts > now() - interval '1 hour'` = what broke recently.
- **Structured alerting**: External monitoring can poll `bot_logs` for ERROR rows without parsing text log files.
- **Correlation**: `bot_logs.trade_id` and `bot_logs.decision_id` link events to the full lifecycle chain. When a trade goes wrong, trace every event from signal to fill.
- **Performance monitoring**: `SELECT event, count(*), avg(extract(epoch from …))` — measure how long each pipeline stage takes if you log start/end events.
- **Retention policy**: Unlike candles/signals/trades which you keep forever, `bot_logs` can be pruned (e.g. `DELETE WHERE ts < now() - interval '30 days'`).

---

## Data Flow: candles → signals → decisions → trades → positions

### Per Tick, Per Symbol

```
1. fetch_candles(exchange, symbol, timeframe, limit)
   │
   ▼
2. upsert_candles(pool, candles)
   → INSERT INTO candles … ON CONFLICT UPDATE
   │
   ▼
3. df = candles_to_dataframe(candles)
   df = compute_all_indicators(df)
   signals_series = generate_signals(df)
   signal = signals_series.iloc[-1]
   │
   ▼
4. INSERT INTO signals (
       symbol, timeframe, ts, signal, rsi, ema_fast, ema_slow,
       macd, macd_signal, macd_hist, bb_upper, bb_middle, bb_lower,
       close_price, reason, strategy_version
   ) VALUES (...)
   │
   ▼
5. If signal == BUY and not has_position(symbol):
       decision, qty, reason = risk.evaluate(...)
       │
       ▼
   INSERT INTO decisions (
       signal_id, decision, reject_reason, proposed_qty,
       capital_pct, min_notional, available_balance, open_positions
   ) VALUES (...)
   │
   ├── REJECTED → log, continue to next symbol
   │
   └── APPROVED →
       │
       ▼
   result = execute_market_buy(exchange, symbol, qty)
       │
       ▼
   INSERT INTO trades (
       decision_id, exchange, order_id, symbol, side,
       quantity, fill_price, cost, fee, status
   ) VALUES (...)
       │
       ▼
   portfolio.open_position(symbol, result.quantity, fill_price)
       │
       ▼
   INSERT INTO positions (
       symbol, buy_trade_id, quantity, entry_price,
       status, opened_at
   ) VALUES (...)

6. If signal == SELL and has_position(symbol):
       (same pattern — risk, execute, insert trades, close position, update positions)

7. Every significant action logs to bot_logs via INSERT
```

### Diagram (Compact)

```
candles ──persist──▸ [candles table]
   │
   │ (in-memory DataFrame)
   ▼
indicators ──compute──▸ generate_signals()
   │
   ▼
[signals table] ◀── INSERT signal row (BUY/SELL/HOLD)
   │
   │ (if BUY/SELL)
   ▼
risk.evaluate()
   │
   ▼
[decisions table] ◀── INSERT decision row (APPROVED/REJECTED)
   │
   │ (if APPROVED)
   ▼
execute_market_buy/sell()
   │
   ▼
[trades table] ◀── INSERT trade row
   │
   ▼
portfolio.open/close_position()
   │
   ▼
[positions table] ◀── INSERT/UPDATE position row
```

---

## TradingEngine Interaction with Each Table

### Startup Sequence

1. **candles**: Read latest N candles per symbol for indicator warmup. `SELECT * FROM candles WHERE symbol=$1 AND timeframe=$2 ORDER BY ts DESC LIMIT $3`.

2. **positions**: Reconstruct `PortfolioState`. `SELECT * FROM positions WHERE status='open'`. For each open position, query `trades` for the BUY fill price and quantity. Populate `portfolio.positions` dict.

3. **signals/decisions/trades**: No read needed at startup. These are write-only during live operation and read-only during analysis.

### Runtime (Per Tick, Per Symbol)

1. **candles**: `INSERT … ON CONFLICT DO UPDATE` via `upsert_candles()`.

2. **signals**: `INSERT` one row after `generate_signals()`. Always insert — even HOLD. This proves the strategy evaluated the candle.

3. **decisions**: `INSERT` one row after `risk.evaluate()`. Always insert — even REJECTED. This proves risk checked and records why it said no.

4. **trades**: `INSERT` one row after `execute_market_buy/sell()`. Only for APPROVED decisions.

5. **positions**: `INSERT` on BUY fill. `UPDATE SET sell_trade_id, exit_price, realized_pnl, status='closed', closed_at` on SELL fill.

6. **bot_logs**: `INSERT` at every significant event. Not a replacement for Python `logging` — a supplement for structured querying.

### Shutdown / Crash Recovery

- **positions WHERE status='open'**: Restores `PortfolioState`. No other table read needed.
- **candles**: On restart, fetch fresh candles from exchange. Upsert handles duplicates.
- **signals**: On restart, new signals written. Old signals for same `(symbol, timeframe, ts)` would conflict if unique constraint exists — use `ON CONFLICT DO NOTHING` or drop constraint for live.

---

## Query Examples for Analysis

### Win Rate Per Symbol
```sql
SELECT symbol,
       count(*) AS total_trades,
       count(*) FILTER (WHERE realized_pnl > 0) AS winners,
       round(100.0 * count(*) FILTER (WHERE realized_pnl > 0) / count(*), 1) AS win_rate_pct,
       round(avg(realized_pnl), 4) AS avg_pnl
FROM positions
WHERE status = 'closed'
GROUP BY symbol
ORDER BY avg_pnl DESC;
```

### Signal Distribution by Version
```sql
SELECT strategy_version, signal, count(*)
FROM signals
GROUP BY 1, 2
ORDER BY 1, 2;
```

### Rejection Rate by Reason
```sql
SELECT reject_reason, count(*) AS n, round(100.0 * count(*) / (SELECT count(*) FROM decisions), 1) AS pct
FROM decisions
WHERE decision = 'REJECTED'
GROUP BY reject_reason
ORDER BY n DESC;
```

### Slippage Analysis
```sql
SELECT t.symbol, t.side,
       round(avg(t.fill_price - s.close_price), 4) AS avg_slippage,
       round(max(t.fill_price - s.close_price), 4) AS max_slippage
FROM trades t
JOIN decisions d ON d.id = t.decision_id
JOIN signals s ON s.id = d.signal_id
GROUP BY 1, 2;
```

### Full Lifecycle Trace for One Trade
```sql
SELECT s.signal, s.reason, d.decision, d.reject_reason,
       t.side, t.quantity, t.fill_price, t.cost,
       p.realized_pnl, p.status
FROM signals s
JOIN decisions d ON d.signal_id = s.id
LEFT JOIN trades t ON t.decision_id = d.id
LEFT JOIN positions p ON p.buy_trade_id = t.id OR p.sell_trade_id = t.id
WHERE s.symbol = 'BTC/USDT'
ORDER BY s.ts DESC
LIMIT 10;
```

---

## Future Extensibility

### Short-Term (Next Iteration)

| Change                          | Rationale                                              |
|---------------------------------|--------------------------------------------------------|
| Add `exchange` column to candles| Multi-exchange support. Currently implicit as Binance. |
| Add `fee_asset` to trades       | Fees may be in BNB, not quote currency.                |
| Add `config` JSONB to signals   | Freeze full strategy config (RSI period, EMA periods) per signal. Currently only `strategy_version`. |
| Add `latency_ms` to decisions   | Measure risk evaluation time.                          |
| Add `latency_ms` to trades      | Measure order placement round-trip.                    |

### Medium-Term

| Change                              | Rationale                                          |
|-------------------------------------|----------------------------------------------------|
| `market_snapshots` table            | Order book depth at decision time. For slippage modeling. |
| `strategy_configs` table            | Versioned config parameters. JOIN to `signals.strategy_version`. |
| `daily_summary` materialized view   | Pre-computed daily PnL, trade count, win rate. Faster dashboard. |
| Partition `candles` by month        | Performance at scale (millions of rows).           |
| Partition `bot_logs` by week        | Easy pruning. `DROP TABLE bot_logs_2026_w23`.      |

### Long-Term

| Change                                  | Rationale                                      |
|-----------------------------------------|------------------------------------------------|
| `portfolio_snapshots` table             | Hourly balance + position snapshots for equity curve. |
| `signal_backtests` table                | Store backtest results separately from live signals. Different unique constraint. |
| Multi-strategy support                  | Add `strategy_name` to signals. Run N strategies on same candles, compare. |
| Paper trading mode                      | `trades.paper` boolean. Run same pipeline against simulated fills. |
| Event sourcing for positions            | Replace mutable `positions` rows with append-only `position_events`. Full audit trail of position changes. |

---

## Naming Conventions

- Table names: plural, lowercase, snake_case (`candles`, `signals`, `bot_logs`)
- Column names: singular, lowercase, snake_case (`close_price`, `reject_reason`)
- Index names: `{table}_{descriptive_suffix}` (`signals_symbol_ts`, `trades_decision_id`)
- Enum values: UPPERCASE with underscores (`APPROVED`, `NOTIONAL_TOO_LOW`)
- Timestamps: always `TIMESTAMPTZ`, always UTC, always named `ts` (event time) or `created_at`/`updated_at`/`*_at` (wall clock)

---

## Summary Table

| Table      | Purpose                        | Key Columns                                    | Grows With        |
|------------|--------------------------------|------------------------------------------------|-------------------|
| candles    | Raw market data                | symbol, timeframe, ts, OHLCV, volume           | Symbols × candles |
| signals    | Strategy output snapshot       | symbol, ts, signal, RSI, EMA, MACD, BB, reason | Every tick        |
| decisions  | Risk evaluation result         | signal_id, decision, reject_reason, qty        | Every tick        |
| trades     | Executed orders                | decision_id, order_id, side, fill_price        | Every fill        |
| positions  | Portfolio holdings             | symbol, buy_trade_id, sell_trade_id, pnl       | Every round-trip  |
| bot_logs   | Structured operational events  | ts, level, category, event, data (JSONB)       | Every event       |
