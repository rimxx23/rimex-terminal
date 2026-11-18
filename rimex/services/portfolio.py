from decimal import Decimal
from sqlite3 import Row

from rimex.domain.portfolio import Position
from rimex.domain.trading import CASH_SCALE, PRICE_SCALE, SIZE_SCALE, displayed
from rimex.services.exchange import Exchange


SCHEMA = """
CREATE TABLE IF NOT EXISTS portfolio_basis (
    account TEXT PRIMARY KEY REFERENCES accounts(id),
    initial_price TEXT NOT NULL,
    source TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS fills_buy_order ON fills(buy);
CREATE INDEX IF NOT EXISTS fills_sell_order ON fills(sell);
"""

OPERATIONS = """
SELECT 'trade' AS source, f.id AS sort_id, f.created_at AS happened_at,
       'buy' AS side, f.size AS sol, f.size * f.price AS cash, NULL AS trigger
FROM orders o JOIN fills f ON f.buy = o.id
WHERE o.account = :account
UNION ALL
SELECT 'trade', f.id, f.created_at, 'sell', f.size, f.size * f.price,
       CASE WHEN o.kind IN ('stop_loss', 'take_profit') THEN o.kind END
FROM orders o JOIN fills f ON f.sell = o.id
WHERE o.account = :account
UNION ALL
SELECT 'swap', rowid, executed_at,
       CASE WHEN input_asset = 'USDT' THEN 'buy' ELSE 'sell' END,
       CASE WHEN input_asset = 'USDT' THEN output_amount ELSE input_amount END,
       CASE WHEN input_asset = 'USDT' THEN input_amount ELSE output_amount END, NULL
FROM demo_swaps
WHERE account = :account AND executed_at IS NOT NULL
ORDER BY happened_at, source, sort_id
"""


def formatted(value: Decimal | int | None, scale: int) -> str | None:
    if value is None:
        return None
    rounded = (Decimal(value) / scale).quantize(Decimal("0.00001"))
    return "0" if not rounded else format(rounded.normalize(), "f")


class Portfolio:
    def __init__(self, exchange: Exchange) -> None:
        self.exchange = exchange
        with exchange.transaction() as db:
            db.executescript(SCHEMA)

    def _save_basis(self, account: str, price: Decimal, source: str) -> Row:
        with self.exchange.transaction() as db:
            db.execute(
                "INSERT INTO portfolio_basis VALUES (?, ?, ?) ON CONFLICT(account) DO NOTHING",
                (account, str(price), source),
            )
            return db.execute("SELECT * FROM portfolio_basis WHERE account = ?", (account,)).fetchone()

    def snapshot(self, account: str, limit: int, offset: int) -> dict:
        with self.exchange.transaction(write=False) as db:
            wallet = db.execute("SELECT cash, sol FROM accounts WHERE id = ?", (account,)).fetchone()
            locked = db.execute(
                "SELECT side, SUM(CASE WHEN side = 'buy' THEN price * remaining ELSE remaining END) AS amount "
                "FROM orders WHERE account = ? AND status = 'open' GROUP BY side",
                (account,),
            ).fetchall()
            operations = db.execute(OPERATIONS, {"account": account}).fetchall()
            basis = db.execute("SELECT * FROM portfolio_basis WHERE account = ?", (account,)).fetchone()
            quote = self.exchange.current_quote(db)
            exit_reserve = self.exchange.reserved_exit_sol(db, account)

        amounts = {item["side"]: item["amount"] for item in locked}
        cash = wallet["cash"] + amounts.get("buy", 0)
        sol = wallet["sol"] + amounts.get("sell", 0) + exit_reserve
        mark = Decimal(quote["bid"] + quote["ask"]) / 2 if quote else None

        if basis is None:
            if operations:
                first = operations[0]
                basis = self._save_basis(account, Decimal(first["cash"]) / first["sol"], "first_operation")
            elif mark is not None:
                basis = self._save_basis(account, mark, "first_portfolio_quote")

        realized_by_operation = []
        position = Position.opening(Decimal(basis["initial_price"])) if basis else None
        if position is not None:
            try:
                for operation in operations:
                    if operation["side"] == "buy":
                        position.buy(operation["sol"], operation["cash"])
                        realized_by_operation.append(None)
                    else:
                        realized_by_operation.append(position.sell(operation["sol"], operation["cash"]))
                if position.quantity != sol:
                    position = None
            except ValueError:
                position = None

        journal = []
        end = max(0, len(operations) - offset)
        start = max(0, end - limit)
        for index in range(end - 1, start - 1, -1):
            operation = operations[index]
            realized = realized_by_operation[index] if position is not None else None
            journal.append({
                "source": operation["source"], "side": operation["side"], "happened_at": operation["happened_at"],
                "sol": displayed(operation["sol"], SIZE_SCALE), "usdt": displayed(operation["cash"], CASH_SCALE),
                "price": formatted(Decimal(operation["cash"]) / operation["sol"], PRICE_SCALE),
                "realized_pnl": formatted(realized, CASH_SCALE), "trigger": operation["trigger"],
            })

        market_value = mark * sol if mark is not None else (Decimal(0) if sol == 0 else None)
        unrealized = market_value - position.cost if market_value is not None and position else None
        return {
            "balances": {"SOL": displayed(sol, SIZE_SCALE), "USDT": displayed(cash, CASH_SCALE)},
            "mark_price": formatted(mark, PRICE_SCALE),
            "equity": formatted(cash + market_value if market_value is not None else None, CASH_SCALE),
            "average_price": formatted(position.average_price if position else None, PRICE_SCALE),
            "realized_pnl": formatted(position.realized if position else None, CASH_SCALE),
            "unrealized_pnl": formatted(unrealized, CASH_SCALE),
            "starting_sol_price": formatted(Decimal(basis["initial_price"]), PRICE_SCALE) if basis else None,
            "starting_price_source": basis["source"] if basis else None,
            "accounting_ready": position is not None,
            "journal": journal, "total_operations": len(operations),
        }
