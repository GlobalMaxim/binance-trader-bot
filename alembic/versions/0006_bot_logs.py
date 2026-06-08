"""add bot_logs table

Revision ID: f1c5a7e2b384
Revises: e8b4f1d6a923
Create Date: 2026-06-08
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "f1c5a7e2b384"
down_revision: str | None = "e8b4f1d6a923"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


def upgrade() -> None:
    op.create_table(
        "bot_logs",
        sa.Column("id",          sa.BigInteger,              nullable=False),
        sa.Column("ts",          sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("level",       sa.Text,                    nullable=False),
        sa.Column("category",    sa.Text,                    nullable=False),
        sa.Column("event",       sa.Text,                    nullable=False),
        sa.Column("symbol",      sa.Text,                    nullable=True),
        sa.Column("message",     sa.Text,                    nullable=False),
        sa.Column("data",        JSONB,                      nullable=True),
        sa.Column("trade_id",    sa.BigInteger,              nullable=True),
        sa.Column("decision_id", sa.BigInteger,              nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("bot_logs_ts",          "bot_logs", [sa.text("ts DESC")])
    op.create_index("bot_logs_level_ts",    "bot_logs", ["level",    "ts"])
    op.create_index("bot_logs_category_ts", "bot_logs", ["category", "ts"])
    op.create_index("bot_logs_event_ts",    "bot_logs", ["event",    "ts"])
    op.create_index("bot_logs_symbol_ts",   "bot_logs", ["symbol",   "ts"])


def downgrade() -> None:
    op.drop_index("bot_logs_symbol_ts",   table_name="bot_logs")
    op.drop_index("bot_logs_event_ts",    table_name="bot_logs")
    op.drop_index("bot_logs_category_ts", table_name="bot_logs")
    op.drop_index("bot_logs_level_ts",    table_name="bot_logs")
    op.drop_index("bot_logs_ts",          table_name="bot_logs")
    op.drop_table("bot_logs")
