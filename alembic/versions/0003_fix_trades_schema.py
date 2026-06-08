"""fix trades schema to match spec

Revision ID: c5f2a8e3b017
Revises: b9e4d1c73a82
Create Date: 2026-06-08

Brings trades table into alignment with docs/database/trades.md:
  - rename price → fill_price
  - rename timestamp → created_at
  - add decision_id, exchange, fee, filled_at
  - drop execution_type, strategy_version
  - rebuild indexes per spec
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision: str = "c5f2a8e3b017"
down_revision: str | None = "b9e4d1c73a82"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


def upgrade() -> None:
    # 1. Rename columns
    op.alter_column("trades", "price",     new_column_name="fill_price")
    op.alter_column("trades", "timestamp", new_column_name="created_at")

    # 2. Add missing columns
    op.add_column("trades", sa.Column("decision_id", sa.BigInteger, nullable=True))
    op.add_column("trades", sa.Column("exchange",    sa.Text,       nullable=True))
    op.add_column("trades", sa.Column("fee",         sa.Double,     nullable=True))
    op.add_column("trades", sa.Column("filled_at",   sa.DateTime(timezone=True), nullable=True))

    # 3. Drop obsolete columns
    op.drop_column("trades", "execution_type")
    op.drop_column("trades", "strategy_version")

    # 4. Rebuild indexes
    op.drop_index("trades_status",    table_name="trades")
    op.drop_index("trades_symbol_ts", table_name="trades")
    op.create_index("trades_symbol_ts",    "trades", ["symbol", "created_at"])
    op.create_index("trades_decision_id",  "trades", ["decision_id"])
    op.create_index("trades_order_id",     "trades", ["order_id"])


def downgrade() -> None:
    op.drop_index("trades_order_id",    table_name="trades")
    op.drop_index("trades_decision_id", table_name="trades")
    op.drop_index("trades_symbol_ts",   table_name="trades")

    op.add_column("trades", sa.Column("execution_type",  sa.Text, server_default="market", nullable=False))
    op.add_column("trades", sa.Column("strategy_version", sa.Text, nullable=True))
    op.drop_column("trades", "filled_at")
    op.drop_column("trades", "fee")
    op.drop_column("trades", "exchange")
    op.drop_column("trades", "decision_id")

    op.alter_column("trades", "created_at", new_column_name="timestamp")
    op.alter_column("trades", "fill_price", new_column_name="price")

    op.create_index("trades_symbol_ts", "trades", ["symbol", "timestamp"])
    op.create_index("trades_status",    "trades", ["status"])
