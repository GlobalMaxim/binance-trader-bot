# bot_logs

Queryable structured event log. Supplements Python `logging` (stdout) with DB-queryable records. Use for operational monitoring, alerting, and post-mortem correlation.

## Fields

| Column      | Type        | Description                                                                               |
|-------------|-------------|-------------------------------------------------------------------------------------------|
| id          | BIGSERIAL   | Surrogate PK                                                                              |
| ts          | TIMESTAMPTZ | Event timestamp. Default `now()`.                                                         |
| level       | TEXT        | `INFO`, `WARNING`, `ERROR`                                                                |
| category    | TEXT        | Pipeline stage: `collector`, `strategy`, `risk`, `execution`, `engine`, `system`         |
| event       | TEXT        | Event name (see JSONB Payloads below)                                                     |
| symbol      | TEXT        | Trading pair. NULL for system-wide events.                                                |
| message     | TEXT        | Human-readable detail                                                                     |
| data        | JSONB       | Structured payload. Schema by event (see below).                                          |
| trade_id    | BIGINT      | FK → `trades.id`. NULL if not trade-related.                                              |
| decision_id | BIGINT      | FK → `decisions.id`. NULL if not decision-related.                                        |

## Constraints

- **Primary key**: `id` (BIGSERIAL)

## Indexes

| Name                   | Columns           | Purpose                        |
|------------------------|-------------------|--------------------------------|
| `bot_logs_pk`          | (id)              | Primary key                    |
| `bot_logs_ts`          | (ts DESC)         | Recent events first            |
| `bot_logs_level_ts`    | (level, ts)       | Filter errors/warnings         |
| `bot_logs_category_ts` | (category, ts)    | Filter by pipeline stage       |
| `bot_logs_event_ts`    | (event, ts)       | Find specific event types      |
| `bot_logs_symbol_ts`   | (symbol, ts)      | Per-symbol event history       |

## JSONB Payloads

| Event              | `data` shape                                                                         |
|--------------------|--------------------------------------------------------------------------------------|
| `tick_start`       | `{"balance": 9876.50, "open_positions": ["BTC/USDT"], "symbols": ["BTC/USDT", ...]}`|
| `signal_generated` | `{"signal": "BUY", "rsi": 32.5, "close_price": 87295.75, "reason": "..."}`          |
| `risk_rejected`    | `{"reason": "INSUFFICIENT_BALANCE", "available": 8.50, "required": 200.78}`         |
| `order_placed`     | `{"side": "buy", "quantity": 0.0023, "order_id": "123456789", "status": "open"}`    |
| `order_filled`     | `{"side": "buy", "quantity": 0.0023, "fill_price": 87295.75, "cost": 200.78, "order_id": "123456789"}` |
| `position_opened`  | `{"symbol": "BTC/USDT", "quantity": 0.0023, "entry_price": 87295.75}`               |
| `position_closed`  | `{"symbol": "BTC/USDT", "realized_pnl": 45.20, "entry_price": 87295.75, "exit_price": 87491.50}` |
| `exchange_error`   | `{"error": "RequestTimeout", "endpoint": "createMarketBuyOrder", "symbol": "BTC/USDT", "retry": 2}` |
| `db_error`         | `{"error": "ConnectionRefusedError", "operation": "upsert_candles", "retry": 3}`    |

Shapes are conventions, not enforced by schema.

## Implementation Notes

- **Retention**: Unlike other tables (keep forever), `bot_logs` can be pruned: `DELETE FROM bot_logs WHERE ts < now() - interval '30 days'`
- **Correlation**: `trade_id` + `decision_id` link log events to the full lifecycle chain (signal → decision → trade)
- **Alerting**: External monitors can poll `WHERE level = 'ERROR' AND ts > now() - interval '1 hour'` without parsing log files

## Example

```
id          | 10452
ts          | 2026-06-07 15:00:02+00
level       | INFO
category    | execution
event       | order_filled
symbol      | BTC/USDT
message     | BUY filled: 0.0023 BTC/USDT @ 87295.75
data        | {"side":"buy","quantity":0.0023,"fill_price":87295.75,"cost":200.78,"order_id":"123456789"}
trade_id    | 501
decision_id | 983
```
