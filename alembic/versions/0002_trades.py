"""add trades table

Revision ID: b9e4d1c73a82
Revises: f3a8c2e1d940
Create Date: 2026-06-08
"""
from __future__ import annotations

from alembic import op

revision: str = "b9e4d1c73a82"
down_revision: str | None = "f3a8c2e1d940"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS trades (
            id               BIGSERIAL        PRIMARY KEY,
            symbol           TEXT             NOT NULL,
            side             TEXT             NOT NULL,
            price            DOUBLE PRECISION NOT NULL,
            quantity         DOUBLE PRECISION NOT NULL,
            order_id         TEXT,
            status           TEXT             NOT NULL,
            execution_type   TEXT             NOT NULL DEFAULT 'market',
            cost             DOUBLE PRECISION,
            timestamp        TIMESTAMPTZ      NOT NULL DEFAULT now(),
            strategy_version TEXT
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS trades_symbol_ts ON trades (symbol, timestamp)")
    op.execute("CREATE INDEX IF NOT EXISTS trades_status    ON trades (status)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS trades")
