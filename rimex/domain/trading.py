from decimal import Decimal

PRICE_SCALE = 100
SIZE_SCALE = 1000
CASH_SCALE = PRICE_SCALE * SIZE_SCALE
START_CASH = 10_000 * CASH_SCALE
START_SOL = 5 * SIZE_SCALE
MAKER_SIZE = 5 * SIZE_SCALE
QUOTE_TTL = 15


class TradeRejected(ValueError):
    pass


def units(value: Decimal, scale: int, maximum: int) -> int:
    if not value.is_finite() or not 0 < value <= maximum:
        raise TradeRejected(f"Enter a value between zero and {maximum}.")
    amount = value * scale
    if amount != amount.to_integral_value():
        raise TradeRejected("Too many decimal places.")
    return int(amount)


def displayed(value: int, scale: int) -> str:
    return format(Decimal(value) / scale, "f")


def crosses(side: str, limit: int, other_price: int) -> bool:
    return limit >= other_price if side == "buy" else limit <= other_price
