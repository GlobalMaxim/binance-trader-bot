import logging
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.database.orm import DecisionORM

log = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class DecisionRecord:
    signal_id: int | None   # None for forced SL/TP exits (no strategy signal)
    decision: str           # "APPROVED" / "REJECTED" / "NO_ACTION"
    reject_reason: str | None
    proposed_qty: float
    capital_pct: float
    min_notional: float
    available_balance: float
    open_positions: int


async def save_decision(
    session_factory: async_sessionmaker[AsyncSession],
    rec: DecisionRecord,
) -> int:
    """Insert a decision row. Returns the new decision id."""
    row = DecisionORM(
        signal_id=rec.signal_id,
        decision=rec.decision,
        reject_reason=rec.reject_reason,
        proposed_qty=rec.proposed_qty,
        capital_pct=rec.capital_pct,
        min_notional=rec.min_notional,
        available_balance=rec.available_balance,
        open_positions=rec.open_positions,
    )
    async with session_factory() as session:
        session.add(row)
        await session.commit()
        await session.refresh(row)

    log.info(
        "decision saved  id=%d  signal_id=%d  %s  reason=%s  qty=%.6f",
        row.id, rec.signal_id, rec.decision, rec.reject_reason, rec.proposed_qty,
    )
    return row.id
