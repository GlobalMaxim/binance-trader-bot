"""initial schema: candles and signals

Revision ID: f3a8c2e1d940
Revises:
Create Date: 2026-06-07

Uses CREATE TABLE IF NOT EXISTS so this migration is safe to run against
an existing database that already has the candles table (created by the
legacy asyncpg migration runner). For a brand-new database, run:

    alembic upgrade head

For a database that already has candles (legacy setup), run:

    alembic stamp head   # mark as applied without running SQL
    # OR just run upgrade head — IF NOT EXISTS makes it idempotent
"""
from __future__ import annotations

from alembic import op

revision: str = "f3a8c2e1d940"
down_revision: str | None = None
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


def upgrade() -> None:
    # ------------------------------------------------------------------ candles
    op.execute("""
        CREATE TABLE IF NOT EXISTS candles (
            symbol    TEXT             NOT NULL,
            timeframe TEXT             NOT NULL,
            ts        TIMESTAMPTZ      NOT NULL,
            open      DOUBLE PRECISION NOT NULL,
            high      DOUBLE PRECISION NOT NULL,
            low       DOUBLE PRECISION NOT NULL,
            close     DOUBLE PRECISION NOT NULL,
            volume    DOUBLE PRECISION NOT NULL,
            PRIMARY KEY (symbol, timeframe, ts)
        )
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS candles_sym_tf_ts
            ON candles (symbol, timeframe, ts DESC)
    """)

    # ------------------------------------------------------------------ signals
    op.execute("""
        CREATE TABLE IF NOT EXISTS signals (
            id               BIGSERIAL        PRIMARY KEY,
            symbol           TEXT             NOT NULL,
            timeframe        TEXT             NOT NULL,
            ts               TIMESTAMPTZ      NOT NULL,
            created_at       TIMESTAMPTZ      NOT NULL DEFAULT now(),
            signal           TEXT             NOT NULL,
            rsi              DOUBLE PRECISION,
            ema_fast         DOUBLE PRECISION,
            ema_slow         DOUBLE PRECISION,
            macd             DOUBLE PRECISION,
            macd_signal      DOUBLE PRECISION,
            macd_hist        DOUBLE PRECISION,
            bb_upper         DOUBLE PRECISION,
            bb_middle        DOUBLE PRECISION,
            bb_lower         DOUBLE PRECISION,
            close_price      DOUBLE PRECISION,
            strategy_version TEXT,
            reason           TEXT,
            confidence       DOUBLE PRECISION,
            CONSTRAINT signals_symbol_timeframe_ts_key UNIQUE (symbol, timeframe, ts)
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS signals_symbol_ts  ON signals (symbol, timeframe, ts)")
    op.execute("CREATE INDEX IF NOT EXISTS signals_signal_ts  ON signals (signal, ts)")
    op.execute("CREATE INDEX IF NOT EXISTS signals_version_ts ON signals (strategy_version, ts)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS signals")
    op.execute("DROP TABLE IF EXISTS candles")
