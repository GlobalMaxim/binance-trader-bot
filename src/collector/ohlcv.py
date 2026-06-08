import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timezone

import ccxt.async_support as ccxt

from src.config import Config


@dataclass(frozen=True, slots=True)
class Candle:
    symbol: str
    timeframe: str
    ts: datetime  # UTC-aware
    open: float
    high: float
    low: float
    close: float
    volume: float

log = logging.getLogger(__name__)

_MAX_ATTEMPTS = 3
_RETRY_DELAY = 2.0  # seconds; doubles each attempt


def create_exchange(cfg: Config) -> ccxt.binance:
    exchange = ccxt.binance(
        {
            "apiKey": cfg.binance_api_key,
            "secret": cfg.binance_secret,
            "enableRateLimit": True,
            "options": {"defaultType": "spot"},
        }
    )
    exchange.enable_demo_trading(True)
    return exchange


def _normalize_symbol(symbol: str) -> str:
    """Coerce bare formats (BTCUSDT → BTC/USDT). Passthrough if already slash-separated."""
    s = symbol.strip().upper()
    if "/" in s:
        return s
    for quote in ("USDT", "BUSD", "BTC", "ETH", "BNB"):
        if s.endswith(quote) and len(s) > len(quote):
            return f"{s[: -len(quote)]}/{quote}"
    return s


async def fetch_candles(
    exchange: ccxt.binance,
    symbol: str,
    timeframe: str,
    limit: int,
) -> list[Candle]:
    symbol = _normalize_symbol(symbol)

    last_exc: Exception = RuntimeError("unreachable")
    wait = _RETRY_DELAY

    for attempt in range(1, _MAX_ATTEMPTS + 1):
        try:
            raw: list = await exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
            candles = [
                Candle(
                    symbol=symbol,
                    timeframe=timeframe,
                    ts=datetime.fromtimestamp(row[0] / 1000, tz=timezone.utc),
                    open=float(row[1]),
                    high=float(row[2]),
                    low=float(row[3]),
                    close=float(row[4]),
                    volume=float(row[5]),
                )
                for row in raw
            ]
            log.debug("fetched %d candles  %s %s", len(candles), symbol, timeframe)
            return candles
        except Exception as exc:
            last_exc = exc
            if attempt >= _MAX_ATTEMPTS:
                log.error(
                    "fetch_ohlcv failed after %d attempts  %s: %s",
                    _MAX_ATTEMPTS,
                    symbol,
                    exc,
                )
                raise
            log.warning(
                "fetch_ohlcv retry %d/%d  %s: %s  (%.1fs)",
                attempt,
                _MAX_ATTEMPTS,
                symbol,
                exc,
                wait,
            )
            await asyncio.sleep(wait)
            wait *= 2.0

    raise last_exc  # unreachable, satisfies type checker
