import hashlib
import hmac
import secrets
import time
from dataclasses import dataclass

from rimex.domain.trading import START_CASH, START_SOL
from rimex.services.exchange import Exchange


TOKEN_LENGTH = 43
SESSION_AGE = 7 * 24 * 60 * 60
DUMMY_HASH = f"{'00' * 16}:{'00' * 32}"

SCHEMA = """
CREATE TABLE IF NOT EXISTS web_users (
    username TEXT PRIMARY KEY,
    account TEXT NOT NULL UNIQUE REFERENCES accounts(id),
    password_hash TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS web_sessions (
    token_hash TEXT PRIMARY KEY,
    username TEXT NOT NULL REFERENCES web_users(username),
    expires_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS web_sessions_expiry ON web_sessions(expires_at);
"""


@dataclass(frozen=True)
class WebUser:
    username: str
    account: str


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def derive_key(password: str, salt: bytes) -> bytes:
    return hashlib.scrypt(
        password.encode(), salt=salt, n=2**15, r=8, p=1, dklen=32, maxmem=64 * 1024 * 1024
    )


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    return f"{salt.hex()}:{derive_key(password, salt).hex()}"


def verify_password(password: str, password_hash: str) -> bool:
    salt, expected = password_hash.split(":")
    return hmac.compare_digest(derive_key(password, bytes.fromhex(salt)), bytes.fromhex(expected))


class Accounts:
    def __init__(self, exchange: Exchange) -> None:
        self.exchange = exchange
        with exchange.transaction() as db:
            db.executescript(SCHEMA)

    def register(
        self, username: str, password_hash: str, guest_token: str, previous_token: str
    ) -> tuple[WebUser, str] | None:
        with self.exchange.transaction() as db:
            if db.execute("SELECT 1 FROM web_users WHERE username = ?", (username,)).fetchone():
                return None
            guest = token_hash(guest_token) if len(guest_token) == TOKEN_LENGTH else ""
            claimable = db.execute(
                "SELECT 1 FROM accounts WHERE id = ? "
                "AND NOT EXISTS (SELECT 1 FROM web_users WHERE account = ?)",
                (guest, guest),
            ).fetchone()
            if claimable:
                account = guest
            else:
                account = secrets.token_hex(32)
                db.execute("INSERT INTO accounts VALUES (?, ?, ?)", (account, START_CASH, START_SOL))
            db.execute("INSERT INTO web_users VALUES (?, ?, ?)", (username, account, password_hash))
            return WebUser(username, account), self._issue_session(db, username, previous_token)

    def get_password_hash(self, username: str) -> str | None:
        with self.exchange.transaction(write=False) as db:
            item = db.execute("SELECT password_hash FROM web_users WHERE username = ?", (username,)).fetchone()
            return item["password_hash"] if item else None

    @staticmethod
    def _issue_session(db, username: str, previous_token: str) -> str:
        now = int(time.time())
        token = secrets.token_urlsafe(32)
        db.execute("DELETE FROM web_sessions WHERE expires_at <= ?", (now,))
        if len(previous_token) == TOKEN_LENGTH:
            db.execute("DELETE FROM web_sessions WHERE token_hash = ?", (token_hash(previous_token),))
        db.execute(
            "INSERT INTO web_sessions VALUES (?, ?, ?)",
            (token_hash(token), username, now + SESSION_AGE),
        )
        return token

    def create_session(self, username: str, previous_token: str) -> str:
        with self.exchange.transaction() as db:
            return self._issue_session(db, username, previous_token)

    def get_user(self, token: str) -> WebUser | None:
        with self.exchange.transaction(write=False) as db:
            user = db.execute(
                "SELECT u.username, u.account FROM web_sessions s "
                "JOIN web_users u ON u.username = s.username "
                "WHERE s.token_hash = ? AND s.expires_at > ?",
                (token_hash(token), int(time.time())),
            ).fetchone()
            return WebUser(user["username"], user["account"]) if user else None

    def logout(self, token: str) -> None:
        if len(token) != TOKEN_LENGTH:
            return
        with self.exchange.transaction() as db:
            db.execute("DELETE FROM web_sessions WHERE token_hash = ?", (token_hash(token),))
