import logging
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.database.orm import TradeORM

log = logging.getLogger(__name__)


async def save_trade(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    symbol: str,
    side: str,
    fill_price: float,
    quantity: float,
    status: str,
    exchange: str | None = None,
    order_id: str | None = None,
    cost: float | None = None,
    fee: float | None = None,
    filled_at: datetime | None = None,
    decision_id: int | None = None,
) -> int:
    """Insert one trade row. Returns the new trade id."""
    trade = TradeORM(
        symbol=symbol,
        side=side,
        fill_price=fill_price,
        quantity=quantity,
        status=status,
        exchange=exchange,
        order_id=order_id,
        cost=cost,
        fee=fee,
        filled_at=filled_at,
        decision_id=decision_id,
    )
    async with session_factory() as session:
        session.add(trade)
        await session.commit()
        await session.refresh(trade)

    log.info(
        "trade saved  id=%d  %s  %s  qty=%.6f  fill=%.4f  status=%s",
        trade.id, symbol, side, quantity, fill_price, status,
    )
    return trade.id
