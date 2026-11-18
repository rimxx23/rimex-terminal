from dataclasses import dataclass
from decimal import Decimal

from rimex.domain.trading import START_SOL


@dataclass
class Position:
    quantity: int
    cost: Decimal
    realized: Decimal = Decimal(0)

    @classmethod
    def opening(cls, starting_price: Decimal) -> "Position":
        return cls(START_SOL, starting_price * START_SOL)

    @property
    def average_price(self) -> Decimal | None:
        return self.cost / self.quantity if self.quantity else None

    def buy(self, quantity: int, paid: int) -> None:
        self.quantity += quantity
        self.cost += paid

    def sell(self, quantity: int, received: int) -> Decimal:
        if quantity > self.quantity:
            raise ValueError("Sale exceeds costed position")
        allocated = self.cost if quantity == self.quantity else self.cost * quantity / self.quantity
        self.cost -= allocated
        self.quantity -= quantity
        profit = Decimal(received) - allocated
        self.realized += profit
        return profit
