import logging
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.database.orm import PositionORM

log = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class OpenPositionRow:
    position_id: int
    symbol: str
    quantity: float
    entry_price: float
    opened_at: datetime


async def open_position(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    symbol: str,
    buy_trade_id: int,
    quantity: float,
    entry_price: float,
    opened_at: datetime,
) -> int:
    """Insert an open position row. Returns the new position id."""
    pos = PositionORM(
        symbol=symbol,
        buy_trade_id=buy_trade_id,
        quantity=quantity,
        entry_price=entry_price,
        status="open",
        opened_at=opened_at,
    )
    async with session_factory() as session:
        session.add(pos)
        await session.commit()
        await session.refresh(pos)

    log.info("position opened  id=%d  %s  qty=%.6f  entry=%.4f", pos.id, symbol, quantity, entry_price)
    return pos.id


async def close_position(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    position_id: int,
    sell_trade_id: int,
    exit_price: float,
    realized_pnl: float,
    closed_at: datetime,
) -> None:
    """Mark an open position as closed."""
    async with session_factory() as session:
        pos = await session.get(PositionORM, position_id)
        if pos is None:
            log.error("close_position: position_id=%d not found", position_id)
            return
        pos.sell_trade_id = sell_trade_id
        pos.exit_price = exit_price
        pos.realized_pnl = realized_pnl
        pos.status = "closed"
        pos.closed_at = closed_at
        await session.commit()

    log.info("position closed  id=%d  exit=%.4f  pnl=%+.4f", position_id, exit_price, realized_pnl)


async def load_open_positions(
    session_factory: async_sessionmaker[AsyncSession],
) -> list[OpenPositionRow]:
    """Load all open positions for startup recovery."""
    async with session_factory() as session:
        result = await session.execute(
            select(PositionORM).where(PositionORM.status == "open")
        )
        rows = result.scalars().all()

    return [
        OpenPositionRow(
            position_id=p.id,
            symbol=p.symbol,
            quantity=p.quantity,
            entry_price=p.entry_price,
            opened_at=p.opened_at,
        )
        for p in rows
    ]
