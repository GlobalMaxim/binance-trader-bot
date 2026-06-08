"""add decisions table

Revision ID: e8b4f1d6a923
Revises: d7e3f9a2c841
Create Date: 2026-06-08
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "e8b4f1d6a923"
down_revision: str | None = "d7e3f9a2c841"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


def upgrade() -> None:
    op.create_table(
        "decisions",
        sa.Column("id",                sa.BigInteger,              nullable=False),
        sa.Column("signal_id",         sa.BigInteger,              nullable=False),
        sa.Column("created_at",        sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("decision",          sa.Text,                    nullable=False),
        sa.Column("reject_reason",     sa.Text,                    nullable=True),
        sa.Column("proposed_qty",      sa.Double,                  nullable=False),
        sa.Column("capital_pct",       sa.Double,                  nullable=False),
        sa.Column("min_notional",      sa.Double,                  nullable=False),
        sa.Column("available_balance", sa.Double,                  nullable=False),
        sa.Column("open_positions",    sa.Integer,                 nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("decisions_signal_id",     "decisions", ["signal_id"])
    op.create_index("decisions_decision_ts",   "decisions", ["decision", "created_at"])
    op.create_index("decisions_reject_reason", "decisions", ["reject_reason"])


def downgrade() -> None:
    op.drop_index("decisions_reject_reason", table_name="decisions")
    op.drop_index("decisions_decision_ts",   table_name="decisions")
    op.drop_index("decisions_signal_id",     table_name="decisions")
    op.drop_table("decisions")
