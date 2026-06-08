# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Setup & Run

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
docker-compose up -d          # starts Postgres
alembic upgrade head          # apply all migrations (run once, or after pulling new migrations)
python main.py
```

## Architecture

Async demo trading system. Polls Binance spot demo via `ccxt.async_support`, persists OHLCV candles to PostgreSQL, runs a full signal → risk → execution pipeline with complete audit trail.

```
main.py                       bootstrap: pool, session_factory, exchange, portfolio → TradingEngine.run()
src/config.py                 Config dataclass loaded from .env
src/models/
  candle.py                   Candle frozen dataclass
  signal_record.py            SignalRecord dataclass (input to insert_signal)
src/database/
  connection.py               asyncpg pool (candle upsert only)
  session.py                  create_session_factory() — SQLAlchemy async_sessionmaker
  orm.py                      All ORM models: CandleORM, SignalORM, DecisionORM, TradeORM, PositionORM, BotLogORM
  migrations/                 (empty — Alembic owns schema)
src/collector/
  ohlcv.py                    create_exchange() + fetch_candles() — retry on failure; normalizes symbol format
src/storage/
  candle_repo.py              upsert_candles() — bulk unnest upsert via asyncpg; parses command tag for row count
  signal_repo.py              insert_signal() → int signal_id (upsert + RETURNING)
  decision_repo.py            save_decision(DecisionRecord) → int decision_id
  trade_repo.py               save_trade(...) → int trade_id
  position_repo.py            open_position / close_position / load_open_positions
  log_repo.py                 write_log / safe_write_log + category/event constants
src/features/
  indicators.py               candles_to_dataframe(), compute_all_indicators() (RSI, EMA-20/50, MACD, BB)
src/strategy/
  signals.py                  generate_signals() → Signal.BUY / SELL / HOLD
src/risk/
  risk.py                     evaluate() — position sizing + balance/notional/max-position checks; RiskConfig, RiskDecision
src/execution/
  executor.py                 execute_market_buy/sell() → OrderResult — ONLY place that calls ccxt order methods
src/engine/
  portfolio.py                PortfolioState — balance, open positions, realized PnL; open/close/restore_position
  trading_engine.py           TradingEngine — central loop wiring all modules together
alembic/
  versions/
    0001_initial.py           candles table
    0002_trades.py            trades table (initial)
    0003_fix_trades_schema.py trades schema fix (fill_price, fee, exchange, decision_id, filled_at)
    0004_positions.py         positions table
    0005_decisions.py         decisions table
    0006_bot_logs.py          bot_logs table (JSONB data col, DESC index)
```

## Pipeline flow per symbol per tick

```
fetch_candles()         → list[Candle]          (collector, retries 3×)
upsert_candles()        → persisted to DB        (storage, asyncpg)
compute_all_indicators  → pd.DataFrame           (features)
generate_signals()      → Signal                 (strategy)
insert_signal()         → int signal_id          (storage, upsert+RETURNING)
risk.evaluate()         → APPROVED / REJECTED    (risk)
save_decision()         → int decision_id        (storage, persists both outcomes)
execute_market_*()      → OrderResult            (execution — only ccxt touch)
save_trade()            → int trade_id           (storage)
db_open/close_position()→ int position_id        (storage)
portfolio.*_position()  → in-memory state update (engine)
safe_write_log()        → bot_logs row           (storage, every stage)
```

## Dual DB clients

Two separate DB clients run in parallel — do not mix them:

| Client | Used for | Why |
|---|---|---|
| `asyncpg.Pool` | `candle_repo.upsert_candles()` only | bulk unnest upsert, one round-trip |
| `SQLAlchemy async_sessionmaker` | signals, decisions, trades, positions, bot_logs | ORM models, RETURNING, JSONB |

DSN for asyncpg: `postgresql://…`  
DSN for SQLAlchemy: `postgresql+asyncpg://…` (auto-converted in `session.py`)

## Key design notes

- `ccxt.async_support` (not sync ccxt) — required for async
- `exchange.enable_demo_trading(True)` — no real orders ever sent
- `options.defaultType = "spot"` — must be explicit; ccxt defaults to futures on Binance
- Bulk candle upsert: `INSERT … SELECT * FROM unnest(…) ON CONFLICT DO UPDATE` — one round-trip per batch
- `asyncpg.Connection.execute()` returns command tag string (`"INSERT 0 N"`); parse `tag.split()[-1]` for row count
- Signal upsert returns id via `on_conflict_do_update(set_={"symbol": excluded.symbol}).returning(id)` — no-op update forces RETURNING on both insert and conflict
- `safe_write_log()` swallows all exceptions — logging failures never interrupt trading
- `portfolio.restore_position()` used on startup recovery — does NOT modify balance (exchange already excludes locked capital from free balance)
- Alembic owns the full schema. `connection.py` is asyncpg pool only — no SQL migration files.

## Alembic

```bash
alembic upgrade head          # apply pending migrations
alembic revision --autogenerate -m "description"  # generate new migration
alembic current               # show current head
alembic history               # show all revisions
```

`alembic/env.py` reads DSN from `.env` via `load_config()`. Current head: `f1c5a7e2b384` (0006_bot_logs).

## Postgres connection

Default DSN: `postgresql://trader:trader@localhost:5432/trader` (matches docker-compose defaults).  
Override via `.env`: `POSTGRES_HOST`, `POSTGRES_PORT`, `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`.

## Verification queries

```bash
# Candles flowing
psql postgresql://trader:trader@localhost:5432/trader \
  -c "SELECT symbol, timeframe, count(*), max(ts) FROM candles GROUP BY 1,2 ORDER BY 1,2;"

# Full pipeline check
psql postgresql://trader:trader@localhost:5432/trader -c "
  SELECT 'signals' AS tbl, count(*) FROM signals
  UNION ALL SELECT 'decisions', count(*) FROM decisions
  UNION ALL SELECT 'trades',    count(*) FROM trades
  UNION ALL SELECT 'positions', count(*) FROM positions
  UNION ALL SELECT 'bot_logs',  count(*) FROM bot_logs;"

# Decision/trade integrity (every trade must point to an APPROVED decision)
psql postgresql://trader:trader@localhost:5432/trader -c "
  SELECT t.id, t.side, d.decision FROM trades t
  JOIN decisions d ON d.id = t.decision_id ORDER BY t.id DESC LIMIT 10;"
```
