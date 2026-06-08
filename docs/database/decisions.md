# decisions

Risk manager output for every signal. Records whether the signal was APPROVED or REJECTED, position size calculated, and the portfolio state at evaluation time.

## Fields

| Column            | Type              | Description                                                          |
|-------------------|-------------------|----------------------------------------------------------------------|
| id                | BIGSERIAL         | Surrogate PK                                                         |
| signal_id         | BIGINT            | FK → `signals.id`                                                    |
| created_at        | TIMESTAMPTZ       | Wall clock when risk evaluation completed. Default `now()`.          |
| decision          | TEXT              | `APPROVED` or `REJECTED`                                             |
| reject_reason     | TEXT              | `NOTIONAL_TOO_LOW` \| `INSUFFICIENT_BALANCE` \| `MAX_POSITIONS` \| NULL |
| proposed_qty      | DOUBLE PRECISION  | Position size computed by risk before checks                         |
| capital_pct       | DOUBLE PRECISION  | `RiskConfig.capital_pct` used (e.g. `0.02` = 2%)                   |
| min_notional      | DOUBLE PRECISION  | `RiskConfig.min_notional` threshold at evaluation time               |
| available_balance | DOUBLE PRECISION  | Portfolio balance at evaluation time                                 |
| open_positions    | INT               | Count of open positions at evaluation time                           |

## Constraints

- **Primary key**: `id` (BIGSERIAL)

## Indexes

| Name                     | Columns                | Purpose                          |
|--------------------------|------------------------|----------------------------------|
| `decisions_pk`           | (id)                   | Primary key                      |
| `decisions_signal_id`    | (signal_id)            | JOIN to signals                  |
| `decisions_decision_ts`  | (decision, created_at) | Rejection rate over time         |
| `decisions_reject_reason`| (reject_reason)        | Group rejections by reason       |

## Relationships

- ← **signals**: `decisions.signal_id` → `signals.id` (1:1)
- → **trades**: `decisions.id` → `trades.decision_id` (1:1, APPROVED only)

## Implementation Notes

- **Always insert, including REJECTED.** Without this, you cannot distinguish "strategy emitted few signals" from "risk blocked everything."
- **Freeze config values.** `capital_pct` and `min_notional` are stored per row. When risk config changes, historical decisions remain attributable to the parameters that produced them.

## Examples

**Rejected**
```
id                | 982
signal_id         | 1423
decision          | REJECTED
reject_reason     | INSUFFICIENT_BALANCE
proposed_qty      | 0.0023
capital_pct       | 0.02
min_notional      | 10.00
available_balance | 8.50
open_positions    | 1
```

**Approved**
```
id                | 983
signal_id         | 1500
decision          | APPROVED
reject_reason     | NULL
proposed_qty      | 0.0023
capital_pct       | 0.02
min_notional      | 10.00
available_balance | 9876.50
open_positions    | 0
```
