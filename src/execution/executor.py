from dataclasses import dataclass
from datetime import datetime, timezone

import ccxt.async_support as ccxt


@dataclass
class OrderResult:
    order_id: str
    symbol: str
    side: str           # "buy" / "sell"
    quantity: float
    fill_price: float
    cost: float
    fee: float
    status: str         # "open" / "closed" / "canceled" / "expired"
    exchange: str       # exchange id, e.g. "binance"
    filled_at: datetime | None


def _parse_order(
    order: dict,
    symbol: str,
    side: str,
    fallback_qty: float,
    exchange_id: str,
) -> OrderResult:
    fill_price = float(order.get("average") or order.get("price") or 0.0)
    quantity = float(order.get("filled") or fallback_qty)
    cost = float(order.get("cost") or quantity * fill_price)
    fee_info = order.get("fee") or {}
    fee = float(fee_info.get("cost") or 0.0)

    filled_ms = order.get("lastTradeTimestamp") or order.get("timestamp")
    filled_at = (
        datetime.fromtimestamp(filled_ms / 1000, tz=timezone.utc) if filled_ms else None
    )

    return OrderResult(
        order_id=str(order["id"]),
        symbol=symbol,
        side=side,
        quantity=quantity,
        fill_price=fill_price,
        cost=cost,
        fee=fee,
        status=str(order.get("status", "unknown")),
        exchange=exchange_id,
        filled_at=filled_at,
    )


async def execute_market_buy(
    exchange: ccxt.binance, symbol: str, quantity: float
) -> OrderResult:
    order = await exchange.create_market_buy_order(symbol, quantity)
    return _parse_order(order, symbol, "buy", quantity, exchange.id)


async def execute_market_sell(
    exchange: ccxt.binance, symbol: str, quantity: float
) -> OrderResult:
    order = await exchange.create_market_sell_order(symbol, quantity)
    return _parse_order(order, symbol, "sell", quantity, exchange.id)
