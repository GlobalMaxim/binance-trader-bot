# positions

One row per position lifecycle (open → closed). Persistent backing for `PortfolioState`. On startup, the engine reconstructs in-memory state from `WHERE status = 'open'`.

## Fields

| Column        | Type              | Description                                              |
|---------------|-------------------|----------------------------------------------------------|
| id            | BIGSERIAL         | Surrogate PK                                             |
| symbol        | TEXT              | Trading pair                                             |
| buy_trade_id  | BIGINT            | FK → `trades.id` (opening BUY)                           |
| sell_trade_id | BIGINT            | FK → `trades.id` (closing SELL). NULL while open.        |
| quantity      | DOUBLE PRECISION  | Position size in base asset                              |
| entry_price   | DOUBLE PRECISION  | Average entry price from BUY fill                        |
| exit_price    | DOUBLE PRECISION  | Average exit price from SELL fill. NULL while open.      |
| realized_pnl  | DOUBLE PRECISION  | `(exit_price − entry_price) × quantity`. NULL while open.|
| status        | TEXT              | `open` or `closed`                                       |
| opened_at     | TIMESTAMPTZ       | When BUY trade was placed                                |
| closed_at     | TIMESTAMPTZ       | When SELL trade was placed. NULL while open.             |

## Constraints

- **Primary key**: `id` (BIGSERIAL)
- **Invariant**: At most one row per symbol with `status = 'open'`. Enforced by `TradingEngine.has_position()` before any BUY.

## Indexes

| Name                     | Columns              | Purpose                          |
|--------------------------|----------------------|----------------------------------|
| `positions_pk`           | (id)                 | Primary key                      |
| `positions_symbol_status`| (symbol, status)     | Find open positions per symbol   |
| `positions_opened_at`    | (opened_at)          | Time-range PnL queries           |
| `positions_buy_trade`    | (buy_trade_id)       | JOIN to opening trade            |
| `positions_sell_trade`   | (sell_trade_id)      | JOIN to closing trade            |

## Relationships

- ← **trades** (buy): `positions.buy_trade_id` → `trades.id`
- ← **trades** (sell): `positions.sell_trade_id` → `trades.id`

## Startup Recovery

```sql
SELECT p.*, t.fill_price, t.quantity
FROM positions p
JOIN trades t ON t.id = p.buy_trade_id
WHERE p.status = 'open';
```

Populate `PortfolioState.positions` from this result. No other table read needed on startup.

## Examples

**Open position**
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

**Closed position**
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
