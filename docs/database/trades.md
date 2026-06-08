# trades

Execution audit trail. One row per filled order. Only APPROVED decisions produce a trade row.

## Fields

| Column      | Type              | Description                                                      |
|-------------|-------------------|------------------------------------------------------------------|
| id          | BIGSERIAL         | Surrogate PK                                                     |
| decision_id | BIGINT            | FK → `decisions.id`                                              |
| exchange    | TEXT              | Exchange name: `binance`                                         |
| order_id    | TEXT              | Exchange-assigned order ID                                       |
| symbol      | TEXT              | Trading pair                                                     |
| side        | TEXT              | `buy` or `sell`                                                  |
| quantity    | DOUBLE PRECISION  | Base asset quantity filled                                       |
| fill_price  | DOUBLE PRECISION  | Average fill price from exchange (`order['average']`)            |
| cost        | DOUBLE PRECISION  | Quote asset cost (`quantity × fill_price`)                       |
| fee         | DOUBLE PRECISION  | Fee in quote currency (0 for demo; real value for live trading)  |
| status      | TEXT              | `open`, `closed`, `canceled`, `expired`                          |
| created_at  | TIMESTAMPTZ       | When order was placed. Default `now()`.                          |
| filled_at   | TIMESTAMPTZ       | When order filled (from exchange `datetime` field)               |

## Constraints

- **Primary key**: `id` (BIGSERIAL)

## Indexes

| Name                 | Columns              | Purpose                          |
|----------------------|----------------------|----------------------------------|
| `trades_pk`          | (id)                 | Primary key                      |
| `trades_decision_id` | (decision_id)        | JOIN to decisions                |
| `trades_symbol_ts`   | (symbol, created_at) | Trade history per symbol         |
| `trades_order_id`    | (order_id)           | Lookup by exchange order ID      |

## Relationships

- ← **decisions**: `trades.decision_id` → `decisions.id` (1:1)
- → **positions**: `trades.id` → `positions.buy_trade_id` or `positions.sell_trade_id`

## Implementation Notes

- `fill_price` source: `order['average']` from ccxt (average fill for market orders). Falls back to `order['price']` if `average` is None.
- `filled_at - created_at` = fill latency. Track over time to detect exchange degradation.
- Slippage = `fill_price - signals.close_price`. JOIN path: `trades → decisions → signals`.

## Example

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
