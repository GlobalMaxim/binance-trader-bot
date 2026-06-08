"""add positions table

Revision ID: d7e3f9a2c841
Revises: c5f2a8e3b017
Create Date: 2026-06-08
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "d7e3f9a2c841"
down_revision: str | None = "c5f2a8e3b017"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


def upgrade() -> None:
    op.create_table(
        "positions",
        sa.Column("id",            sa.BigInteger,              nullable=False),
        sa.Column("symbol",        sa.Text,                    nullable=False),
        sa.Column("buy_trade_id",  sa.BigInteger,              nullable=False),
        sa.Column("sell_trade_id", sa.BigInteger,              nullable=True),
        sa.Column("quantity",      sa.Double,                  nullable=False),
        sa.Column("entry_price",   sa.Double,                  nullable=False),
        sa.Column("exit_price",    sa.Double,                  nullable=True),
        sa.Column("realized_pnl",  sa.Double,                  nullable=True),
        sa.Column("status",        sa.Text,                    nullable=False),
        sa.Column("opened_at",     sa.DateTime(timezone=True), nullable=False),
        sa.Column("closed_at",     sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("positions_symbol_status", "positions", ["symbol", "status"])
    op.create_index("positions_opened_at",     "positions", ["opened_at"])
    op.create_index("positions_buy_trade",     "positions", ["buy_trade_id"])
    op.create_index("positions_sell_trade",    "positions", ["sell_trade_id"])


def downgrade() -> None:
    op.drop_index("positions_sell_trade",   table_name="positions")
    op.drop_index("positions_buy_trade",    table_name="positions")
    op.drop_index("positions_opened_at",    table_name="positions")
    op.drop_index("positions_symbol_status", table_name="positions")
    op.drop_table("positions")
