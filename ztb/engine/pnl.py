from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PnLSnapshot:
    position: float
    avg_entry_price: float
    realized_pnl: float
    total_commission: float
    total_slippage: float
    initial_cash: float


EPS = 1e-12


class PnLCalculator:
    def __init__(self, initial_cash: float = 100_000.0) -> None:
        self._initial_cash = initial_cash
        self._position = 0.0
        self._avg_entry_price = 0.0
        self._realized_pnl = 0.0
        self._total_commission = 0.0
        self._total_slippage = 0.0

    @property
    def position(self) -> float:
        return self._position

    @property
    def avg_entry_price(self) -> float:
        return self._avg_entry_price

    @property
    def realized_pnl(self) -> float:
        return self._realized_pnl

    @property
    def total_commission(self) -> float:
        return self._total_commission

    @property
    def total_slippage(self) -> float:
        return self._total_slippage

    def unrealized_pnl(self, close_price: float) -> float:
        if self._avg_entry_price == 0.0 or abs(self._position) < EPS:
            return 0.0
        return (close_price - self._avg_entry_price) * self._position

    def equity(self, close_price: float) -> float:
        return self._initial_cash + self._realized_pnl + self.unrealized_pnl(close_price)

    @property
    def snapshot(self) -> PnLSnapshot:
        return PnLSnapshot(
            position=self._position,
            avg_entry_price=self._avg_entry_price,
            realized_pnl=self._realized_pnl,
            total_commission=self._total_commission,
            total_slippage=self._total_slippage,
            initial_cash=self._initial_cash,
        )

    def adopt_state(
        self, position: float, avg_entry_price: float, realized_pnl: float = 0.0
    ) -> None:
        self._position = position
        self._avg_entry_price = avg_entry_price
        self._realized_pnl = realized_pnl

    def set_initial_cash(self, cash: float) -> None:
        self._initial_cash = cash

    def apply_fill(
        self, delta: float, fill_price: float, commission: float = 0.0, slippage: float = 0.0
    ) -> None:
        if abs(delta) < EPS:
            return

        old_pos = self._position
        new_pos = old_pos + delta
        realized = 0.0

        if old_pos > 0 and delta < 0:
            if new_pos >= 0:
                realized = abs(delta) * (fill_price - self._avg_entry_price)
            else:
                realized = old_pos * (fill_price - self._avg_entry_price)
        elif old_pos < 0 and delta > 0:
            if new_pos <= 0:
                realized = abs(delta) * (self._avg_entry_price - fill_price)
            else:
                realized = abs(old_pos) * (self._avg_entry_price - fill_price)

        if abs(new_pos) < EPS:
            self._avg_entry_price = 0.0
        elif old_pos > 0 and delta > 0:
            self._avg_entry_price = (old_pos * self._avg_entry_price + delta * fill_price) / new_pos
        elif old_pos < 0 and delta < 0:
            self._avg_entry_price = (
                abs(old_pos) * self._avg_entry_price + abs(delta) * fill_price
            ) / abs(new_pos)
        elif old_pos > 0 >= new_pos or old_pos < 0 <= new_pos or abs(old_pos) < EPS:
            self._avg_entry_price = fill_price

        self._position = new_pos
        costs = commission + slippage
        self._realized_pnl += realized - costs
        self._total_commission += commission
        self._total_slippage += slippage
