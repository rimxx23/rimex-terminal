import time
from uuid import uuid4

from rimex.domain.trading import Asset, CASH_SCALE, SIZE_SCALE, TradeRejected, displayed, other_asset
from rimex.services.exchange import Exchange


SCALES = {"SOL": SIZE_SCALE, "USDT": CASH_SCALE}
MAX_AMOUNTS = {"SOL": 1_000, "USDT": 100_000}
BALANCE_FIELDS = {"SOL": "sol", "USDT": "cash"}
SWAP_TTL = 25
SLIPPAGE_BPS = 50

SCHEMA = """
CREATE TABLE IF NOT EXISTS demo_swaps (
    id TEXT PRIMARY KEY,
    account TEXT NOT NULL REFERENCES accounts(id),
    input_asset TEXT NOT NULL CHECK(input_asset IN ('SOL', 'USDT')),
    input_amount INTEGER NOT NULL CHECK(input_amount > 0),
    expected_output INTEGER NOT NULL CHECK(expected_output > 0),
    min_output INTEGER NOT NULL CHECK(min_output > 0),
    expires_at INTEGER NOT NULL,
    executed_at REAL,
    output_amount INTEGER
);
CREATE INDEX IF NOT EXISTS swap_history ON demo_swaps(account, executed_at DESC);
CREATE INDEX IF NOT EXISTS swap_expiry ON demo_swaps(expires_at) WHERE executed_at IS NULL;
"""


class SwapNotFound(LookupError):
    pass


class SwapLedger:
    def __init__(self, exchange: Exchange) -> None:
        self.exchange = exchange
        with exchange.transaction() as db:
            db.executescript(SCHEMA)

    def create(self, account: str, asset: Asset, amount: int, output: int) -> dict:
        now = int(time.time())
        quote_id = uuid4().hex
        minimum = (output * (10_000 - SLIPPAGE_BPS) + 9_999) // 10_000
        with self.exchange.transaction() as db:
            db.execute("DELETE FROM demo_swaps WHERE executed_at IS NULL AND expires_at <= ?", (now,))
            db.execute(
                "INSERT INTO demo_swaps(id, account, input_asset, input_amount, expected_output, min_output, expires_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (quote_id, account, asset, amount, output, minimum, now + SWAP_TTL),
            )
            return self._view(self._find(db, account, quote_id))

    @staticmethod
    def _find(db, account: str, quote_id: str):
        row = db.execute(
            "SELECT * FROM demo_swaps WHERE account = ? AND id = ?", (account, quote_id)
        ).fetchone()
        if row is None:
            raise SwapNotFound("Quote not found. Get a new quote.")
        return row

    @staticmethod
    def _verify_time(row, now: float) -> None:
        if row["expires_at"] <= now:
            raise TradeRejected("Quote expired. Get a new quote.")

    def prepare(self, account: str, quote_id: str) -> tuple[Asset, int] | dict:
        with self.exchange.transaction(write=False) as db:
            row = self._find(db, account, quote_id)
            if row["executed_at"] is not None:
                return self._view(row)
            self._verify_time(row, int(time.time()))
            return row["input_asset"], row["input_amount"]

    def settle(self, account: str, quote_id: str, output: int) -> dict:
        with self.exchange.transaction() as db:
            row = self._find(db, account, quote_id)
            if row["executed_at"] is not None:
                return self._view(row)
            now = time.time()
            self._verify_time(row, now)
            if output < row["min_output"]:
                raise TradeRejected("Price moved below the minimum. Get a new quote.")
            source = row["input_asset"]
            debit, credit = BALANCE_FIELDS[source], BALANCE_FIELDS[other_asset(source)]
            amount = row["input_amount"]
            balance = db.execute(
                f"UPDATE accounts SET {debit} = {debit} - ?, {credit} = {credit} + ? "
                f"WHERE id = ? AND {debit} >= ?",
                (amount, output, account, amount),
            )
            if not balance.rowcount:
                raise TradeRejected("Insufficient available balance.")
            db.execute(
                "UPDATE demo_swaps SET executed_at = ?, output_amount = ? WHERE id = ?",
                (now, output, quote_id),
            )
            return self._view(self._find(db, account, quote_id))

    def snapshot(self, account: str) -> dict:
        with self.exchange.transaction(write=False) as db:
            wallet = db.execute("SELECT sol, cash FROM accounts WHERE id = ?", (account,)).fetchone()
            history = db.execute(
                "SELECT * FROM demo_swaps WHERE account = ? AND executed_at IS NOT NULL "
                "ORDER BY executed_at DESC, rowid DESC LIMIT 30",
                (account,),
            ).fetchall()
            return {
                "balances": {"SOL": displayed(wallet["sol"], SIZE_SCALE), "USDT": displayed(wallet["cash"], CASH_SCALE)},
                "history": [self._view(row) for row in history],
            }

    @staticmethod
    def _view(row) -> dict:
        asset = row["input_asset"]
        target = other_asset(asset)
        return {
            "id": row["id"], "input_asset": asset, "output_asset": target,
            "input_amount": displayed(row["input_amount"], SCALES[asset]),
            "expected_output": displayed(row["expected_output"], SCALES[target]),
            "min_output": displayed(row["min_output"], SCALES[target]),
            "output_amount": (
                displayed(row["output_amount"], SCALES[target]) if row["output_amount"] is not None else None
            ),
            "slippage_bps": SLIPPAGE_BPS, "expires_at": row["expires_at"], "executed_at": row["executed_at"],
        }
