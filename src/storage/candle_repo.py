import asyncio
import logging

import asyncpg

from src.collector.ohlcv import Candle

log = logging.getLogger(__name__)

_UPSERT = """
    INSERT INTO candles (symbol, timeframe, ts, open, high, low, close, volume)
    SELECT * FROM unnest(
        $1::text[], $2::text[], $3::timestamptz[],
        $4::float8[], $5::float8[], $6::float8[], $7::float8[], $8::float8[]
    )
    ON CONFLICT (symbol, timeframe, ts) DO UPDATE SET
        open   = EXCLUDED.open,
        high   = EXCLUDED.high,
        low    = EXCLUDED.low,
        close  = EXCLUDED.close,
        volume = EXCLUDED.volume
"""

_MAX_ATTEMPTS = 3
_RETRY_DELAY = 1.0  # seconds; doubles each attempt


async def upsert_candles(pool: asyncpg.Pool, candles: list[Candle]) -> int:
    if not candles:
        return 0

    symbol = candles[0].symbol
    timeframe = candles[0].timeframe
    last_exc: Exception = RuntimeError("unreachable")
    wait = _RETRY_DELAY

    for attempt in range(1, _MAX_ATTEMPTS + 1):
        try:
            async with pool.acquire() as conn:
                # asyncpg returns command tag string e.g. "INSERT 0 42"
                tag: str = await conn.execute(
                    _UPSERT,
                    [c.symbol for c in candles],
                    [c.timeframe for c in candles],
                    [c.ts for c in candles],
                    [c.open for c in candles],
                    [c.high for c in candles],
                    [c.low for c in candles],
                    [c.close for c in candles],
                    [c.volume for c in candles],
                )
            # Tag format: "INSERT 0 <n>" where n = rows inserted/updated
            n = int(tag.split()[-1])
            log.info("upserted %d candles  %s %s", n, symbol, timeframe)
            return n
        except Exception as exc:
            last_exc = exc
            if attempt >= _MAX_ATTEMPTS:
                log.error(
                    "upsert failed after %d attempts  %s %s: %s",
                    _MAX_ATTEMPTS,
                    symbol,
                    timeframe,
                    exc,
                )
                raise
            log.warning(
                "upsert retry %d/%d  %s %s: %s  (%.1fs)",
                attempt,
                _MAX_ATTEMPTS,
                symbol,
                timeframe,
                exc,
                wait,
            )
            await asyncio.sleep(wait)
            wait *= 2.0

    raise last_exc  # unreachable
