import logging
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.database.orm import SignalORM


@dataclass(frozen=True, slots=True)
class SignalRecord:
    symbol: str
    timeframe: str
    ts: datetime
    signal: str
    rsi: float | None
    ema_fast: float | None
    ema_slow: float | None
    macd: float | None
    macd_signal: float | None
    macd_hist: float | None
    bb_upper: float | None
    bb_middle: float | None
    bb_lower: float | None
    close_price: float | None
    strategy_version: str | None
    reason: str | None
    confidence: float | None = None

log = logging.getLogger(__name__)


async def insert_signal(
    session_factory: async_sessionmaker[AsyncSession],
    rec: SignalRecord,
) -> int:
    """Upsert a signal row. Returns the signal id (existing or new)."""
    insert_stmt = pg_insert(SignalORM).values(
        symbol=rec.symbol,
        timeframe=rec.timeframe,
        ts=rec.ts,
        signal=rec.signal,
        rsi=rec.rsi,
        ema_fast=rec.ema_fast,
        ema_slow=rec.ema_slow,
        macd=rec.macd,
        macd_signal=rec.macd_signal,
        macd_hist=rec.macd_hist,
        bb_upper=rec.bb_upper,
        bb_middle=rec.bb_middle,
        bb_lower=rec.bb_lower,
        close_price=rec.close_price,
        strategy_version=rec.strategy_version,
        reason=rec.reason,
        confidence=rec.confidence,
    )
    # On conflict: no-op update (set symbol to its own excluded value) so RETURNING
    # always fires and we get the id whether the row is new or already exists.
    stmt = (
        insert_stmt
        .on_conflict_do_update(
            index_elements=["symbol", "timeframe", "ts"],
            set_={"symbol": insert_stmt.excluded.symbol},
        )
        .returning(SignalORM.id)
    )

    async with session_factory() as session:
        result = await session.execute(stmt)
        signal_id: int = result.scalar_one()
        await session.commit()

    log.debug(
        "signal upserted  id=%d  %s %s %s  signal=%s",
        signal_id, rec.symbol, rec.timeframe, rec.ts, rec.signal,
    )
    return signal_id
