import asyncio
import logging

from src.collector.ohlcv import create_exchange
from src.config import load_config
from src.database.connection import create_pool
from src.database.session import create_session_factory
from src.engine.portfolio import PortfolioState
from src.engine.trading_engine import TradingEngine
from src.risk.risk import RiskConfig

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
log = logging.getLogger(__name__)

_DEMO_FALLBACK_BALANCE = 10_000.0  # used if exchange returns 0


async def main() -> None:
    cfg = load_config()
    pool = await create_pool(cfg.postgres_dsn)
    session_factory = create_session_factory(cfg.postgres_dsn)
    exchange = create_exchange(cfg)

    # Fetch real demo balance so position sizing is accurate
    raw_balance = await exchange.fetch_balance()
    usdt_free = float((raw_balance.get("USDT") or {}).get("free") or 0.0)
    if usdt_free == 0.0:
        log.warning("USDT balance is 0 or unavailable, using %.0f USDT demo fallback", _DEMO_FALLBACK_BALANCE)
        usdt_free = _DEMO_FALLBACK_BALANCE

    portfolio = PortfolioState(balance=usdt_free)
    risk_config = RiskConfig(
        capital_pct=0.02,    # 2 % of balance per trade
        min_notional=10.0,   # Binance minimum
        max_positions_per_symbol=1,
    )

    engine = TradingEngine(
        cfg=cfg,
        exchange=exchange,
        portfolio=portfolio,
        pool=pool,
        session_factory=session_factory,
        risk_config=risk_config,
    )

    try:
        await engine.run()
    finally:
        await exchange.close()
        await pool.close()


if __name__ == "__main__":
    asyncio.run(main())
