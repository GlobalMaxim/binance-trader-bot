# Binance Demo Trading Bot

Async algorithmic trading bot for Binance (demo mode). Fetches OHLCV candles, computes technical indicators, generates buy/sell signals, manages risk, executes market orders, and maintains a full audit trail in PostgreSQL.

**No real funds — demo mode only** (`enable_demo_trading(True)`).

## Setup

**1. Install deps**
```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

**2. Configure**
```bash
# .env (required)
BINANCE_API_KEY=<your demo key>
BINANCE_SECRET_KEY=<your demo secret>

# Postgres — optional, defaults match docker-compose
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_DB=trader
POSTGRES_USER=trader
POSTGRES_PASSWORD=trader
```

**3. Start Postgres**
```bash
docker-compose up -d
```

**4. Apply migrations**
```bash
alembic upgrade head
```

**5. Run**
```bash
python main.py
```

## Configuration (`.env`)

| Variable | Default | Description |
|---|---|---|
| `BINANCE_API_KEY` | — | Binance demo API key (required) |
| `BINANCE_SECRET_KEY` | — | Binance demo secret (required) |
| `SYMBOLS` | `BTC/USDT,ETH/USDT` | Comma-separated trading pairs |
| `TIMEFRAME` | `1m` | ccxt timeframe string |
| `FETCH_LIMIT` | `100` | Candles per fetch |
| `POLL_INTERVAL` | `60` | Seconds between ticks |

## Pipeline

Each tick, per symbol:

```
fetch_candles → upsert DB → compute indicators → generate signal
  → persist signal → risk decision → persist decision
  → (if approved) execute order → persist trade → update position
  → log all events to bot_logs
```

Signals: `RSI` + `EMA 20/50 crossover` + `MACD histogram`.  
Risk: 2% of balance per trade, Binance minimum notional enforced, max 1 open position per symbol.

## Database

6 tables, all managed by Alembic:

| Table | Contents |
|---|---|
| `candles` | Raw OHLCV data (asyncpg bulk upsert) |
| `signals` | Strategy output per tick per symbol |
| `decisions` | Risk manager output — approved and rejected |
| `trades` | Exchange order fill audit trail |
| `positions` | Position lifecycle (open → closed, with PnL) |
| `bot_logs` | Structured event log with JSONB payload |

```bash
# Check all tables
psql postgresql://trader:trader@localhost:5432/trader -c "\dt"

# Candles flowing
psql postgresql://trader:trader@localhost:5432/trader \
  -c "SELECT symbol, timeframe, count(*), max(ts) FROM candles GROUP BY 1,2;"

# Recent events
psql postgresql://trader:trader@localhost:5432/trader \
  -c "SELECT ts, level, event, symbol, message FROM bot_logs ORDER BY ts DESC LIMIT 20;"
```

## Project structure

```
main.py                   — bootstrap and entry point
src/
  config.py               — Config dataclass from .env
  models/                 — Candle, SignalRecord dataclasses
  collector/ohlcv.py      — ccxt async fetch_candles (3× retry)
  features/indicators.py  — RSI, EMA, MACD, Bollinger Bands
  strategy/signals.py     — BUY / SELL / HOLD signal generation
  risk/risk.py            — position sizing, notional/balance checks
  execution/executor.py   — market order execution (only ccxt touch)
  engine/
    portfolio.py          — in-memory position and balance state
    trading_engine.py     — main loop, wires all stages together
  database/
    connection.py         — asyncpg pool
    session.py            — SQLAlchemy async session factory
    orm.py                — all ORM models
  storage/
    candle_repo.py        — bulk upsert via unnest
    signal_repo.py        — insert_signal (upsert + RETURNING id)
    decision_repo.py      — save_decision
    trade_repo.py         — save_trade
    position_repo.py      — open / close / load positions
    log_repo.py           — write_log / safe_write_log + event constants
alembic/
  versions/               — 0001 candles → 0006 bot_logs
```
