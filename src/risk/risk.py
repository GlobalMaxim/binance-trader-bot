from dataclasses import dataclass
from enum import StrEnum


class RiskDecision(StrEnum):
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    NO_ACTION = "NO_ACTION"


class RejectReason(StrEnum):
    NOTIONAL_TOO_LOW = "NOTIONAL_TOO_LOW"
    INSUFFICIENT_BALANCE = "INSUFFICIENT_BALANCE"
    MAX_POSITIONS = "MAX_POSITIONS"
    NO_OPEN_POSITION = "NO_OPEN_POSITION"
    HOLD_SIGNAL = "HOLD_SIGNAL"
    # Legacy values kept for DB query compatibility — no longer written by new code
    SL_HIT = "SL_HIT"
    TP_HIT = "TP_HIT"


@dataclass(frozen=True, slots=True)
class RiskConfig:
    capital_pct: float = 0.02
    min_notional: float = 10.0
    max_positions_per_symbol: int = 1


@dataclass(frozen=True, slots=True)
class Position:
    symbol: str
    quantity: float
    entry_price: float


def _notional(qty: float, price: float) -> float:
    return qty * price


def check_min_notional(qty: float, price: float, min_notional: float) -> bool:
    return _notional(qty, price) >= min_notional


def check_balance(qty: float, price: float, available_balance: float) -> bool:
    return _notional(qty, price) <= available_balance


def check_max_positions(
    symbol: str, positions: dict[str, list[Position]], max_positions: int
) -> bool:
    return len(positions.get(symbol, [])) < max_positions


def position_size(price: float, capital: float, capital_pct: float) -> float:
    allocation = capital * capital_pct
    return allocation / price


def evaluate(
    symbol: str,
    price: float,
    capital: float,
    available_balance: float,
    positions: dict[str, list[Position]],
    config: RiskConfig | None = None,
) -> tuple[RiskDecision, float, RejectReason | None]:
    if config is None:
        config = RiskConfig()

    qty = position_size(price, capital, config.capital_pct)

    if not check_min_notional(qty, price, config.min_notional):
        return RiskDecision.REJECTED, 0.0, RejectReason.NOTIONAL_TOO_LOW
    if not check_balance(qty, price, available_balance):
        return RiskDecision.REJECTED, 0.0, RejectReason.INSUFFICIENT_BALANCE
    if not check_max_positions(symbol, positions, config.max_positions_per_symbol):
        return RiskDecision.REJECTED, 0.0, RejectReason.MAX_POSITIONS

    return RiskDecision.APPROVED, qty, None


def evaluate_sell(
    has_open_position: bool,
) -> tuple[RiskDecision, RejectReason | None]:
    """Risk evaluation for a SELL signal.
    Only meaningful rejection: no position to close.
    """
    if not has_open_position:
        return RiskDecision.REJECTED, RejectReason.NO_OPEN_POSITION
    return RiskDecision.APPROVED, None
