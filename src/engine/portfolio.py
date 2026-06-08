from dataclasses import dataclass, field

from src.risk.risk import Position


@dataclass
class PortfolioState:
    balance: float
    positions: dict[str, Position] = field(default_factory=dict)
    position_db_ids: dict[str, int] = field(default_factory=dict, repr=False)

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

    def close_position(self, symbol: str, fill_price: float) -> tuple[float, int]:
        """Returns (realized_pnl, position_db_id)."""
        pos = self.positions.pop(symbol)
        db_id = self.position_db_ids.pop(symbol)
        self.balance += pos.quantity * fill_price
        pnl = (fill_price - pos.entry_price) * pos.quantity
        return pnl, db_id

    def restore_position(
        self, symbol: str, quantity: float, entry_price: float, db_id: int
    ) -> None:
        """Reconstruct in-memory state from DB row (startup recovery, no balance change)."""
        self.positions[symbol] = Position(
            symbol=symbol, quantity=quantity, entry_price=entry_price
        )
        self.position_db_ids[symbol] = db_id

    def unrealized_pnl(self, symbol: str, current_price: float) -> float:
        if symbol not in self.positions:
            return 0.0
        pos = self.positions[symbol]
        return (current_price - pos.entry_price) * pos.quantity
