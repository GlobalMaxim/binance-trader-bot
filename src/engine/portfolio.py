from dataclasses import dataclass, field

from src.risk.risk import Position


@dataclass
class PortfolioState:
    balance: float
    positions: dict[str, Position] = field(default_factory=dict)
    position_db_ids: dict[str, int] = field(default_factory=dict, repr=False)
    position_extreme: dict[str, float] = field(default_factory=dict, repr=False)
    position_bars: dict[str, int] = field(default_factory=dict, repr=False)

    def has_position(self, symbol: str) -> bool:
        return symbol in self.positions

    def open_position(
        self, symbol: str, quantity: float, entry_price: float, db_id: int
    ) -> None:
        self.balance -= quantity * entry_price
        self.positions[symbol] = Position(
            symbol=symbol, quantity=quantity, entry_price=entry_price
        )
        self.position_db_ids[symbol] = db_id
        self.position_extreme[symbol] = entry_price
        self.position_bars[symbol] = 0

    def close_position(self, symbol: str, fill_price: float) -> tuple[float, int]:
        """Returns (realized_pnl, position_db_id)."""
        pos = self.positions.pop(symbol)
        db_id = self.position_db_ids.pop(symbol)
        self.position_extreme.pop(symbol, None)
        self.position_bars.pop(symbol, None)
        self.balance += pos.quantity * fill_price
        pnl = (fill_price - pos.entry_price) * pos.quantity
        return pnl, db_id

    def restore_position(
        self, symbol: str, quantity: float, entry_price: float, db_id: int
    ) -> None:
        """Reconstruct in-memory state from DB row (startup recovery, no balance change).
        extreme resets to entry_price — trailing stop is conservative after a restart.
        """
        self.positions[symbol] = Position(
            symbol=symbol, quantity=quantity, entry_price=entry_price
        )
        self.position_db_ids[symbol] = db_id
        self.position_extreme[symbol] = entry_price
        self.position_bars[symbol] = 0

    def tick_position(self, symbol: str, high: float, low: float) -> None:
        """Update extreme and bar count after a bar where no exit fired.
        Only long positions supported — extreme tracks highest high.
        """
        if symbol in self.position_extreme:
            self.position_extreme[symbol] = max(self.position_extreme[symbol], high)
        if symbol in self.position_bars:
            self.position_bars[symbol] += 1

    def unrealized_pnl(self, symbol: str, current_price: float) -> float:
        if symbol not in self.positions:
            return 0.0
        pos = self.positions[symbol]
        return (current_price - pos.entry_price) * pos.quantity
