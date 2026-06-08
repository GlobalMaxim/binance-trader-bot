import logging

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.database.orm import BotLogORM

log = logging.getLogger(__name__)

# ── Category constants ────────────────────────────────────────────────────────
CAT_COLLECTOR = "collector"
CAT_STRATEGY  = "strategy"
CAT_RISK      = "risk"
CAT_EXECUTION = "execution"
CAT_ENGINE    = "engine"
CAT_SYSTEM    = "system"

# ── Event constants ───────────────────────────────────────────────────────────
EVT_ENGINE_STARTED        = "engine_started"
EVT_TICK_START            = "tick_start"
EVT_SIGNAL_GENERATED      = "signal_generated"
EVT_DECISION_APPROVED     = "decision_approved"
EVT_RISK_REJECTED         = "risk_rejected"
EVT_ORDER_FILLED          = "order_filled"
EVT_POSITION_OPENED       = "position_opened"
EVT_POSITION_CLOSED       = "position_closed"
EVT_EXCHANGE_ERROR        = "exchange_error"
EVT_UNEXPECTED_EXCEPTION  = "unexpected_exception"
EVT_DB_ERROR              = "db_error"
EVT_SL_HIT                = "sl_hit"
EVT_TP_HIT                = "tp_hit"
EVT_STRATEGY_EXIT         = "strategy_exit"


async def write_log(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    level: str,
    category: str,
    event: str,
    symbol: str | None = None,
    message: str,
    data: dict | None = None,
    trade_id: int | None = None,
    decision_id: int | None = None,
) -> None:
    """Insert a structured log row into bot_logs."""
    row = BotLogORM(
        level=level,
        category=category,
        event=event,
        symbol=symbol,
        message=message,
        data=data,
        trade_id=trade_id,
        decision_id=decision_id,
    )
    async with session_factory() as session:
        session.add(row)
        await session.commit()


async def safe_write_log(
    session_factory: async_sessionmaker[AsyncSession],
    **kwargs,
) -> None:
    """write_log wrapped so DB failures never propagate to callers."""
    try:
        await write_log(session_factory, **kwargs)
    except Exception as exc:
        log.warning("bot_log write failed [%s/%s]: %s", kwargs.get("category"), kwargs.get("event"), exc)
