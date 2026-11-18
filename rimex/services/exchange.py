import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path

from rimex.domain.trading import (
    CASH_SCALE, MAKER_SIZE, PRICE_SCALE, QUOTE_TTL, SIZE_SCALE, START_CASH,
    START_SOL, TradeRejected, crosses, displayed,
)


SCHEMA = """
CREATE TABLE IF NOT EXISTS accounts (
    id TEXT PRIMARY KEY, cash INTEGER NOT NULL CHECK(cash >= 0),
    sol INTEGER NOT NULL CHECK(sol >= 0)
);
CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY, account TEXT NOT NULL REFERENCES accounts(id),
    side TEXT NOT NULL, price INTEGER NOT NULL, size INTEGER NOT NULL,
    remaining INTEGER NOT NULL, status TEXT NOT NULL DEFAULT 'open',
    kind TEXT NOT NULL DEFAULT 'limit'
);
CREATE INDEX IF NOT EXISTS book ON orders(status, side, price, id);
CREATE INDEX IF NOT EXISTS account_orders ON orders(account, id);
CREATE TABLE IF NOT EXISTS fills (
    id INTEGER PRIMARY KEY, buy INTEGER REFERENCES orders(id),
    sell INTEGER REFERENCES orders(id), price INTEGER NOT NULL,
    size INTEGER NOT NULL, created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS exit_plans (
    id INTEGER PRIMARY KEY,
    account TEXT NOT NULL REFERENCES accounts(id),
    size INTEGER NOT NULL CHECK(size > 0),
    remaining INTEGER NOT NULL CHECK(remaining >= 0),
    stop INTEGER NOT NULL,
    target INTEGER NOT NULL CHECK(target > stop),
    status TEXT NOT NULL DEFAULT 'armed',
    trigger TEXT,
    triggered_at REAL
);
CREATE INDEX IF NOT EXISTS exit_status ON exit_plans(status, id);
CREATE INDEX IF NOT EXISTS account_exits ON exit_plans(account, id);
CREATE TABLE IF NOT EXISTS quote (
    id INTEGER PRIMARY KEY CHECK(id = 1), bid INTEGER, ask INTEGER,
    bid_size INTEGER, ask_size INTEGER, source TEXT, received_at REAL
);
"""


class Exchange:
    def __init__(self, path: Path) -> None:
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.transaction() as db:
            db.executescript(SCHEMA)
        with self.transaction() as db:
            columns = {column["name"] for column in db.execute("PRAGMA table_info(orders)")}
            if "kind" not in columns:
                db.execute("ALTER TABLE orders ADD COLUMN kind TEXT NOT NULL DEFAULT 'limit'")

    @contextmanager
    def transaction(self, *, write: bool = True):
        db = sqlite3.connect(self.path, isolation_level=None, timeout=5)
        db.row_factory = sqlite3.Row
        try:
            db.execute("PRAGMA foreign_keys = ON")
            db.execute("BEGIN IMMEDIATE" if write else "BEGIN")
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def has_account(self, account: str) -> bool:
        with self.transaction() as db:
            return db.execute("SELECT 1 FROM accounts WHERE id = ?", (account,)).fetchone() is not None

    def create_account(self, account: str) -> None:
        with self.transaction() as db:
            db.execute("INSERT INTO accounts VALUES (?, ?, ?)", (account, START_CASH, START_SOL))

    def current_quote(self, db):
        quote = db.execute("SELECT * FROM quote WHERE id = 1").fetchone()
        return quote if quote and time.time() - quote["received_at"] <= QUOTE_TTL else None

    def update_quote(self, bid: int, ask: int, source: str) -> None:
        if not 0 < bid < ask:
            return
        with self.transaction() as db:
            db.execute(
                "INSERT OR REPLACE INTO quote VALUES (1, ?, ?, ?, ?, ?, ?)",
                (bid, ask, MAKER_SIZE, MAKER_SIZE, source, time.time()),
            )
            for side, price, comparison, ordering in (
                ("buy", ask, ">=", "DESC"), ("sell", bid, "<=", "ASC"),
            ):
                available = MAKER_SIZE
                orders = db.execute(
                    f"SELECT * FROM orders WHERE status = 'open' AND side = ? AND price {comparison} ? "
                    f"ORDER BY price {ordering}, id",
                    (side, price),
                ).fetchall()
                for order in orders:
                    size = min(available, order["remaining"])
                    self._fill(db, order, None, price, size)
                    available -= size
                    if not available:
                        break
                field = "ask_size" if side == "buy" else "bid_size"
                db.execute(f"UPDATE quote SET {field} = ? WHERE id = 1", (available,))
            self._run_exits(db, bid)

    def _fill(self, db, order, resting, price: int, size: int) -> None:
        buy, sell = (order, resting) if order["side"] == "buy" else (resting, order)
        if buy is not None:
            db.execute(
                "UPDATE accounts SET cash = cash + ?, sol = sol + ? WHERE id = ?",
                ((buy["price"] - price) * size, size, buy["account"]),
            )
        if sell is not None:
            db.execute(
                "UPDATE accounts SET cash = cash + ? WHERE id = ?",
                (price * size, sell["account"]),
            )
        for item in (buy, sell):
            if item is not None:
                db.execute(
                    "UPDATE orders SET remaining = remaining - ?, "
                    "status = CASE WHEN remaining = ? THEN 'filled' ELSE 'open' END WHERE id = ?",
                    (size, size, item["id"]),
                )
        db.execute(
            "INSERT INTO fills(buy, sell, price, size, created_at) VALUES (?, ?, ?, ?, ?)",
            (buy["id"] if buy else None, sell["id"] if sell else None, price, size, time.time()),
        )

    def place(self, account: str, side: str, price: int | None, size: int) -> dict:
        with self.transaction() as db:
            return self._order(self._place(db, account, side, price, size))

    def _place(self, db, account: str, side: str, price: int | None, size: int, *, trigger: str | None = None):
        market = self.current_quote(db)
        if market is None:
            raise TradeRejected("Market quotes are unavailable. Try again when the feed is live.")
        market_order = price is None
        kind = trigger or ("market" if market_order else "limit")
        if market_order:
            if side == "buy":
                price = market["ask"] * 101 // 100
            else:
                price = (market["bid"] * 99 + 99) // 100
        if kind == "limit" and db.execute(
            "SELECT count(*) FROM orders WHERE account = ? AND status = 'open'", (account,)
        ).fetchone()[0] >= 25:
            raise TradeRejected("Cancel an existing order before placing another.")
        if trigger is None:
            self._reserve(db, account, "cash" if side == "buy" else "sol", price * size if side == "buy" else size)
        order_id = db.execute(
            "INSERT INTO orders(account, side, price, size, remaining, kind) VALUES (?, ?, ?, ?, ?, ?)",
            (account, side, price, size, size, kind),
        ).lastrowid
        maker_price, maker_size = ("ask", "ask_size") if side == "buy" else ("bid", "bid_size")
        other_side, ordering = ("sell", "ASC") if side == "buy" else ("buy", "DESC")
        excluded = account if trigger else None
        while True:
            order = db.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
            if not order["remaining"]:
                break
            resting = db.execute(
                f"SELECT * FROM orders WHERE status = 'open' AND side = ? "
                f"AND (? IS NULL OR account != ?) ORDER BY price {ordering}, id LIMIT 1",
                (other_side, excluded, excluded),
            ).fetchone()
            if resting and not crosses(side, price, resting["price"]):
                resting = None
            quote = self.current_quote(db)
            use_maker = (
                quote and quote[maker_size] and crosses(side, price, quote[maker_price])
                and (resting is None or (
                    resting["price"] != quote[maker_price]
                    and crosses(side, resting["price"], quote[maker_price])
                ))
            )
            if use_maker:
                amount = min(order["remaining"], quote[maker_size])
                self._fill(db, order, None, quote[maker_price], amount)
                db.execute(f"UPDATE quote SET {maker_size} = {maker_size} - ? WHERE id = 1", (amount,))
            elif resting is None:
                break
            elif resting["account"] == account:
                raise TradeRejected("This order would match one of your own orders.")
            else:
                self._fill(db, order, resting, resting["price"], min(order["remaining"], resting["remaining"]))
        if market_order and order["remaining"]:
            if order["remaining"] == order["size"]:
                raise TradeRejected("No liquidity available within 1% of the quoted price.")
            if trigger is None:
                self._release_order(db, order)
            else:
                db.execute("UPDATE orders SET status = 'cancelled' WHERE id = ?", (order_id,))
            order = db.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
        return order

    @staticmethod
    def _reserve(db, account: str, field: str, amount: int) -> None:
        result = db.execute(
            f"UPDATE accounts SET {field} = {field} - ? WHERE id = ? AND {field} >= ?",
            (amount, account, amount),
        )
        if not result.rowcount:
            raise TradeRejected("Insufficient available balance.")

    @staticmethod
    def reserved_exit_sol(db, account: str) -> int:
        return db.execute(
            "SELECT COALESCE(SUM(remaining), 0) FROM exit_plans "
            "WHERE account = ? AND status IN ('armed', 'triggered')",
            (account,),
        ).fetchone()[0]

    def has_active_exits(self) -> bool:
        with self.transaction(write=False) as db:
            return db.execute(
                "SELECT 1 FROM exit_plans WHERE status IN ('armed', 'triggered') LIMIT 1"
            ).fetchone() is not None

    def protect(self, account: str, size: int, stop: int, target: int) -> dict:
        with self.transaction() as db:
            market = self.current_quote(db)
            if market is None:
                raise TradeRejected("Market quotes are unavailable. Try again when the feed is live.")
            if not stop < market["bid"] < target:
                raise TradeRejected("Stop loss must be below the current bid and take profit above it.")
            count = db.execute(
                "SELECT count(*) FROM exit_plans WHERE account = ? AND status IN ('armed', 'triggered')",
                (account,),
            ).fetchone()[0]
            if count >= 10:
                raise TradeRejected("Cancel an existing exit plan before adding another.")
            self._reserve(db, account, "sol", size)
            plan = db.execute(
                "INSERT INTO exit_plans(account, size, remaining, stop, target) "
                "VALUES (?, ?, ?, ?, ?) RETURNING *",
                (account, size, size, stop, target),
            ).fetchone()
            return self._exit(plan)

    def cancel_exit(self, account: str, plan_id: int) -> bool:
        with self.transaction() as db:
            plan = db.execute(
                "UPDATE exit_plans SET status = 'cancelled' WHERE account = ? AND id = ? "
                "AND status IN ('armed', 'triggered') RETURNING remaining",
                (account, plan_id),
            ).fetchone()
            if plan is None:
                return False
            db.execute("UPDATE accounts SET sol = sol + ? WHERE id = ?", (plan["remaining"], account))
            return True

    def _run_exits(self, db, bid: int) -> None:
        plans = db.execute(
            "SELECT * FROM exit_plans WHERE status = 'triggered' "
            "OR (status = 'armed' AND (stop >= ? OR target <= ?)) "
            "ORDER BY (status = 'triggered') DESC, triggered_at, id",
            (bid, bid),
        ).fetchall()
        for plan in plans:
            trigger = plan["trigger"]
            if trigger is None:
                trigger = "stop_loss" if bid <= plan["stop"] else "take_profit"
                db.execute(
                    "UPDATE exit_plans SET status = 'triggered', trigger = ?, triggered_at = ? WHERE id = ?",
                    (trigger, time.time(), plan["id"]),
                )
            db.execute("SAVEPOINT exit_fill")
            try:
                order = self._place(db, plan["account"], "sell", None, plan["remaining"], trigger=trigger)
            except TradeRejected:
                db.execute("ROLLBACK TO exit_fill")
            else:
                remaining = order["remaining"]
                db.execute(
                    "UPDATE exit_plans SET remaining = ?, status = ? WHERE id = ?",
                    (remaining, "triggered" if remaining else "filled", plan["id"]),
                )
            finally:
                db.execute("RELEASE exit_fill")

    @staticmethod
    def _exit(row) -> dict:
        return {
            "id": row["id"], "status": row["status"], "trigger": row["trigger"],
            "triggered_at": row["triggered_at"], "size": displayed(row["size"], SIZE_SCALE),
            "remaining": displayed(row["remaining"], SIZE_SCALE),
            "stop": displayed(row["stop"], PRICE_SCALE), "target": displayed(row["target"], PRICE_SCALE),
        }

    @staticmethod
    def _release_order(db, order) -> None:
        field, amount = (
            ("cash", order["price"] * order["remaining"])
            if order["side"] == "buy" else ("sol", order["remaining"])
        )
        db.execute(f"UPDATE accounts SET {field} = {field} + ? WHERE id = ?", (amount, order["account"]))
        db.execute("UPDATE orders SET status = 'cancelled' WHERE id = ?", (order["id"],))

    def cancel(self, account: str, order_id: int) -> bool:
        with self.transaction() as db:
            order = db.execute(
                "SELECT * FROM orders WHERE account = ? AND id = ? AND status = 'open'", (account, order_id)
            ).fetchone()
            if order is None:
                return False
            self._release_order(db, order)
            return True

    @staticmethod
    def _order(row) -> dict:
        return {
            "id": row["id"], "side": row["side"], "status": row["status"], "kind": row["kind"],
            "price": displayed(row["price"], PRICE_SCALE),
            "size": displayed(row["size"], SIZE_SCALE),
            "remaining": displayed(row["remaining"], SIZE_SCALE),
        }

    def snapshot(self, account: str) -> dict:
        with self.transaction(write=False) as db:
            wallet = db.execute("SELECT * FROM accounts WHERE id = ?", (account,)).fetchone()
            orders = db.execute(
                "SELECT * FROM orders WHERE account = ? "
                "ORDER BY (status = 'open') DESC, id DESC LIMIT 50",
                (account,),
            ).fetchall()
            fills = db.execute(
                "SELECT fills.*, b.account AS buyer FROM fills "
                "LEFT JOIN orders b ON b.id = fills.buy LEFT JOIN orders s ON s.id = fills.sell "
                "WHERE b.account = ? OR s.account = ? ORDER BY fills.id DESC LIMIT 50",
                (account, account),
            ).fetchall()
            exits = db.execute(
                "SELECT * FROM exit_plans WHERE account = ? "
                "ORDER BY (status IN ('armed', 'triggered')) DESC, id DESC LIMIT 25",
                (account,),
            ).fetchall()
            quote = self.current_quote(db)
            book = {}
            for side, order_by in (("buy", "DESC"), ("sell", "ASC")):
                rows = db.execute(
                    f"SELECT price, sum(remaining) AS size FROM orders WHERE status = 'open' AND side = ? "
                    f"GROUP BY price ORDER BY price {order_by} LIMIT 12",
                    (side,),
                )
                levels = {row["price"]: row["size"] for row in rows}
                if quote:
                    price, available = ("bid", "bid_size") if side == "buy" else ("ask", "ask_size")
                    if quote[available]:
                        levels[quote[price]] = levels.get(quote[price], 0) + quote[available]
                book[side] = [
                    {"price": displayed(price, PRICE_SCALE), "size": displayed(levels[price], SIZE_SCALE)}
                    for price in sorted(levels, reverse=side == "buy")[:10]
                ]
            locked = {"buy": 0, "sell": self.reserved_exit_sol(db, account)}
            for order in orders:
                if order["status"] == "open":
                    size = order["remaining"]
                    locked[order["side"]] += size * order["price"] if order["side"] == "buy" else size
            return {
                "symbol": "SOL/USDT",
                "market": None if quote is None else {
                    "source": quote["source"], "bid": displayed(quote["bid"], PRICE_SCALE),
                    "ask": displayed(quote["ask"], PRICE_SCALE), "updated_at": quote["received_at"],
                },
                "book": book,
                "wallet": {
                    "usdt": displayed(wallet["cash"], CASH_SCALE), "sol": displayed(wallet["sol"], SIZE_SCALE),
                    "locked_usdt": displayed(locked["buy"], CASH_SCALE),
                    "locked_sol": displayed(locked["sell"], SIZE_SCALE),
                },
                "orders": [self._order(order) for order in orders],
                "exits": [self._exit(plan) for plan in exits],
                "trades": [
                    {"id": row["id"], "side": "buy" if row["buyer"] == account else "sell",
                     "price": displayed(row["price"], PRICE_SCALE),
                     "size": displayed(row["size"], SIZE_SCALE), "created_at": row["created_at"]}
                    for row in fills
                ],
            }
