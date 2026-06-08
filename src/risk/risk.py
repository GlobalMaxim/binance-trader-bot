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
    HOLD_SIGNAL = "HOLD_SIGNAL"
    SL_HIT = "SL_HIT"
    TP_HIT = "TP_HIT"


class SLTPTrigger(StrEnum):
    SL_HIT = "SL_HIT"
    TP_HIT = "TP_HIT"


@dataclass(frozen=True, slots=True)
class RiskConfig:
    capital_pct: float = 0.02
    min_notional: float = 10.0
    max_positions_per_symbol: int = 1
    sl_pct: float | None = 0.02   # stop-loss fraction of entry price; None = disabled
    tp_pct: float | None = 0.04   # take-profit fraction of entry price; None = disabled


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


def check_sl_tp(
    entry_price: float,
    current_price: float,
    config: RiskConfig,
) -> SLTPTrigger | None:
    """Evaluate stop-loss / take-profit thresholds for an open position.

    Returns SL_HIT, TP_HIT, or None.
    SL checked first so a gap-down that crosses both fires SL.
    """
    if entry_price <= 0:
        return None
    change_pct = (current_price - entry_price) / entry_price
    if config.sl_pct is not None and change_pct <= -config.sl_pct:
        return SLTPTrigger.SL_HIT
    if config.tp_pct is not None and change_pct >= config.tp_pct:
        return SLTPTrigger.TP_HIT
    return None
