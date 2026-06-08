from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Double, Index, Integer, String, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column



class Base(DeclarativeBase):
    pass


class CandleORM(Base):
    """Schema mirror of the candles table. Used by Alembic only — raw OHLCV
    data is stored via asyncpg bulk upsert (candle_repo.py) for performance."""

    __tablename__ = "candles"

    symbol: Mapped[str] = mapped_column(String, primary_key=True)
    timeframe: Mapped[str] = mapped_column(String, primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    open: Mapped[float] = mapped_column(Double, nullable=False)
    high: Mapped[float] = mapped_column(Double, nullable=False)
    low: Mapped[float] = mapped_column(Double, nullable=False)
    close: Mapped[float] = mapped_column(Double, nullable=False)
    volume: Mapped[float] = mapped_column(Double, nullable=False)

    __table_args__ = (
        Index("candles_sym_tf_ts", "symbol", "timeframe", "ts"),
    )


class SignalORM(Base):
    """Persistent store for strategy output. Written via SQLAlchemy async session."""

    __tablename__ = "signals"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String, nullable=False)
    timeframe: Mapped[str] = mapped_column(String, nullable=False)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )
    signal: Mapped[str] = mapped_column(String, nullable=False)
    rsi: Mapped[float | None] = mapped_column(Double, nullable=True)
    ema_fast: Mapped[float | None] = mapped_column(Double, nullable=True)
    ema_slow: Mapped[float | None] = mapped_column(Double, nullable=True)
    macd: Mapped[float | None] = mapped_column(Double, nullable=True)
    macd_signal: Mapped[float | None] = mapped_column(Double, nullable=True)
    macd_hist: Mapped[float | None] = mapped_column(Double, nullable=True)
    bb_upper: Mapped[float | None] = mapped_column(Double, nullable=True)
    bb_middle: Mapped[float | None] = mapped_column(Double, nullable=True)
    bb_lower: Mapped[float | None] = mapped_column(Double, nullable=True)
    close_price: Mapped[float | None] = mapped_column(Double, nullable=True)
    strategy_version: Mapped[str | None] = mapped_column(String, nullable=True)
    reason: Mapped[str | None] = mapped_column(String, nullable=True)
    confidence: Mapped[float | None] = mapped_column(Double, nullable=True)

    __table_args__ = (
        UniqueConstraint("symbol", "timeframe", "ts", name="signals_symbol_timeframe_ts_key"),
        Index("signals_symbol_ts", "symbol", "timeframe", "ts"),
        Index("signals_signal_ts", "signal", "ts"),
        Index("signals_version_ts", "strategy_version", "ts"),
    )


class BotLogORM(Base):
    """Queryable structured event log. Supplements Python logging with DB-queryable records."""

    __tablename__ = "bot_logs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    ts: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )
    level: Mapped[str] = mapped_column(String, nullable=False)       # "INFO" / "WARNING" / "ERROR"
    category: Mapped[str] = mapped_column(String, nullable=False)    # pipeline stage
    event: Mapped[str] = mapped_column(String, nullable=False)       # event name
    symbol: Mapped[str | None] = mapped_column(String, nullable=True)
    message: Mapped[str] = mapped_column(String, nullable=False)
    data: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    trade_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    decision_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    __table_args__ = (
        Index("bot_logs_ts",          text("ts DESC")),
        Index("bot_logs_level_ts",    "level",    "ts"),
        Index("bot_logs_category_ts", "category", "ts"),
        Index("bot_logs_event_ts",    "event",    "ts"),
        Index("bot_logs_symbol_ts",   "symbol",   "ts"),
    )


class DecisionORM(Base):
    """Risk manager output for every actionable signal (BUY/SELL)."""

    __tablename__ = "decisions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    signal_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )
    decision: Mapped[str] = mapped_column(String, nullable=False)        # "APPROVED" / "REJECTED"
    reject_reason: Mapped[str | None] = mapped_column(String, nullable=True)
    proposed_qty: Mapped[float] = mapped_column(Double, nullable=False)
    capital_pct: Mapped[float] = mapped_column(Double, nullable=False)
    min_notional: Mapped[float] = mapped_column(Double, nullable=False)
    available_balance: Mapped[float] = mapped_column(Double, nullable=False)
    open_positions: Mapped[int] = mapped_column(Integer, nullable=False)

    __table_args__ = (
        Index("decisions_signal_id",     "signal_id"),
        Index("decisions_decision_ts",   "decision", "created_at"),
        Index("decisions_reject_reason", "reject_reason"),
    )


class PositionORM(Base):
    """One row per position lifecycle (open → closed). Persistent backing for PortfolioState."""

    __tablename__ = "positions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String, nullable=False)
    buy_trade_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sell_trade_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    quantity: Mapped[float] = mapped_column(Double, nullable=False)
    entry_price: Mapped[float] = mapped_column(Double, nullable=False)
    exit_price: Mapped[float | None] = mapped_column(Double, nullable=True)
    realized_pnl: Mapped[float | None] = mapped_column(Double, nullable=True)
    status: Mapped[str] = mapped_column(String, nullable=False)  # "open" / "closed"
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("positions_symbol_status", "symbol", "status"),
        Index("positions_opened_at",     "opened_at"),
        Index("positions_buy_trade",     "buy_trade_id"),
        Index("positions_sell_trade",    "sell_trade_id"),
    )


class TradeORM(Base):
    """Execution audit trail. One row per order that reached the exchange."""

    __tablename__ = "trades"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    decision_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)   # FK → decisions.id (future)
    exchange: Mapped[str | None] = mapped_column(String, nullable=True)           # e.g. "binance"
    order_id: Mapped[str | None] = mapped_column(String, nullable=True)
    symbol: Mapped[str] = mapped_column(String, nullable=False)
    side: Mapped[str] = mapped_column(String, nullable=False)                     # "buy" / "sell"
    quantity: Mapped[float] = mapped_column(Double, nullable=False)
    fill_price: Mapped[float] = mapped_column(Double, nullable=False)
    cost: Mapped[float | None] = mapped_column(Double, nullable=True)
    fee: Mapped[float | None] = mapped_column(Double, nullable=True)
    status: Mapped[str] = mapped_column(String, nullable=False)                   # "open" / "closed" / "canceled" / "expired"
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )
    filled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("trades_symbol_ts",   "symbol", "created_at"),
        Index("trades_decision_id", "decision_id"),
        Index("trades_order_id",    "order_id"),
    )
