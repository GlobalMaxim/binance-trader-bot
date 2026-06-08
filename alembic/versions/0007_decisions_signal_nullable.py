"""make decisions.signal_id nullable for forced SL/TP exits

Revision ID: a2b4c6d8e0f2
Revises: f1c5a7e2b384
Create Date: 2026-06-08
"""
from __future__ import annotations

from alembic import op

revision: str = "a2b4c6d8e0f2"
down_revision: str | None = "f1c5a7e2b384"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


def upgrade() -> None:
    op.alter_column("decisions", "signal_id", nullable=True)


def downgrade() -> None:
    op.alter_column("decisions", "signal_id", nullable=False)
