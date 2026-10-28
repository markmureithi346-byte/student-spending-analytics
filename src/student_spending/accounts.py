"""Local demo accounts for the money planner and upload workspace.

Passwords are hashed with scrypt before they touch disk and sessions are
opaque random tokens; the database stores only a SHA-256 digest of each token.
This is a learning feature on a loopback server, not a production identity
system: there is no email verification, password reset or remote provider, and
the UI asks for made-up details only.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import re
import secrets
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path

SESSION_COOKIE = "ssa_session"
SESSION_SECONDS = 8 * 60 * 60
MIN_PASSWORD_LENGTH = 8
MAX_PASSWORD_LENGTH = 128
MAX_DISPLAY_NAME_LENGTH = 40
MAX_EMAIL_LENGTH = 120

_SCRYPT_N = 2 ** 14
_SCRYPT_R = 8
_SCRYPT_P = 1
_SCRYPT_DKLEN = 32
_EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS accounts (
    account_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    display_name TEXT NOT NULL,
    email        TEXT NOT NULL UNIQUE COLLATE NOCASE,
    password_hash TEXT NOT NULL,
    created_at   TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions (
    token_hash TEXT PRIMARY KEY,
    account_id INTEGER NOT NULL REFERENCES accounts(account_id) ON DELETE CASCADE,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS sessions_account
    ON sessions(account_id);
CREATE INDEX IF NOT EXISTS sessions_expiry
    ON sessions(expires_at);
"""


class AccountError(ValueError):
    """A sign-up or sign-in request that cannot be accepted."""


@dataclass(frozen=True)
class Account:
    account_id: int
    display_name: str
    email: str
    created_at: str


def normalise_email(value: str) -> str:
    return value.strip().lower()


def validate_display_name(value: str) -> str:
    name = " ".join(value.split())
    if len(name) < 2:
        raise AccountError("Use a display name of at least 2 characters.")
    if len(name) > MAX_DISPLAY_NAME_LENGTH:
        raise AccountError(
            f"Keep the display name to {MAX_DISPLAY_NAME_LENGTH} characters or fewer."
        )
    return name


def validate_email(value: str) -> str:
    email = normalise_email(value)
    if not email:
        raise AccountError("Enter an email address for this demo account.")
    if len(email) > MAX_EMAIL_LENGTH or not _EMAIL_PATTERN.match(email):
        raise AccountError("That email address does not look valid.")
    return email


def validate_password(value: str) -> str:
    if len(value) < MIN_PASSWORD_LENGTH:
        raise AccountError(
            f"Use at least {MIN_PASSWORD_LENGTH} characters for the password."
        )
    if len(value) > MAX_PASSWORD_LENGTH:
        raise AccountError(
            f"Keep the password to {MAX_PASSWORD_LENGTH} characters or fewer."
        )
    if not any(character.isalpha() for character in value):
        raise AccountError("Include at least one letter in the password.")
    if not any(character.isdigit() for character in value):
        raise AccountError("Include at least one number in the password.")
    return value


def _b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=_SCRYPT_N,
        r=_SCRYPT_R,
        p=_SCRYPT_P,
        dklen=_SCRYPT_DKLEN,
    )
    return (
        f"scrypt${_SCRYPT_N}${_SCRYPT_R}${_SCRYPT_P}"
        f"${_b64(salt)}${_b64(digest)}"
    )


def verify_password(password: str, encoded: str) -> bool:
    try:
        scheme, n, r, p, salt_text, digest_text = encoded.split("$")
        if scheme != "scrypt":
            return False
        salt = base64.b64decode(salt_text, validate=True)
        expected = base64.b64decode(digest_text, validate=True)
        actual = hashlib.scrypt(
            password.encode("utf-8"),
            salt=salt,
            n=int(n),
            r=int(r),
            p=int(p),
            dklen=len(expected),
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(actual, expected)


@lru_cache(maxsize=1)
def _dummy_hash() -> str:
    """A real hash used to spend the same time on unknown accounts."""
    return hash_password("demo-placeholder-password-1")


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def _stamp(moment: datetime) -> str:
    return moment.isoformat()


def _token_digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class AccountStore:
    """A tiny SQLite store; each call uses its own connection."""

    def __init__(self, path: Path | str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_schema()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def _ensure_schema(self) -> None:
        connection = self._connect()
        try:
            connection.executescript(_SCHEMA)
            connection.commit()
        finally:
            connection.close()

    def create_account(
        self, display_name: str, email: str, password: str
    ) -> Account:
        name = validate_display_name(display_name)
        address = validate_email(email)
        validate_password(password)
        created_at = _stamp(_now())
        connection = self._connect()
        try:
            with connection:
                cursor = connection.execute(
                    "INSERT INTO accounts (display_name, email, password_hash, created_at) "
                    "VALUES (?, ?, ?, ?)",
                    (name, address, hash_password(password), created_at),
                )
            account_id = int(cursor.lastrowid)
        except sqlite3.IntegrityError:
            raise AccountError(
                "An account with that email already exists. Sign in instead."
            ) from None
        finally:
            connection.close()
        return Account(
            account_id=account_id,
            display_name=name,
            email=address,
            created_at=created_at,
        )

    def authenticate(self, email: str, password: str) -> Account | None:
        address = normalise_email(email)
        connection = self._connect()
        try:
            row = connection.execute(
                "SELECT account_id, display_name, email, password_hash, created_at "
                "FROM accounts WHERE email = ?",
                (address,),
            ).fetchone()
        finally:
            connection.close()
        if row is None:
            verify_password(password, _dummy_hash())
            return None
        if not verify_password(password, str(row["password_hash"])):
            return None
        return Account(
            account_id=int(row["account_id"]),
            display_name=str(row["display_name"]),
            email=str(row["email"]),
            created_at=str(row["created_at"]),
        )

    def create_session(self, account_id: int) -> str:
        token = secrets.token_urlsafe(32)
        created = _now()
        expires = created + timedelta(seconds=SESSION_SECONDS)
        connection = self._connect()
        try:
            with connection:
                connection.execute(
                    "DELETE FROM sessions WHERE expires_at <= ?", (_stamp(created),)
                )
                connection.execute(
                    "INSERT INTO sessions (token_hash, account_id, created_at, expires_at) "
                    "VALUES (?, ?, ?, ?)",
                    (
                        _token_digest(token),
                        account_id,
                        _stamp(created),
                        _stamp(expires),
                    ),
                )
        finally:
            connection.close()
        return token

    def account_for_token(self, token: str) -> Account | None:
        if not 20 <= len(token) <= 200:
            return None
        now = _stamp(_now())
        connection = self._connect()
        try:
            row = connection.execute(
                "SELECT a.account_id, a.display_name, a.email, a.created_at "
                "FROM sessions AS s JOIN accounts AS a "
                "ON a.account_id = s.account_id "
                "WHERE s.token_hash = ? AND s.expires_at > ?",
                (_token_digest(token), now),
            ).fetchone()
        finally:
            connection.close()
        if row is None:
            return None
        return Account(
            account_id=int(row["account_id"]),
            display_name=str(row["display_name"]),
            email=str(row["email"]),
            created_at=str(row["created_at"]),
        )

    def delete_session(self, token: str) -> None:
        if not token:
            return
        connection = self._connect()
        try:
            with connection:
                connection.execute(
                    "DELETE FROM sessions WHERE token_hash = ?",
                    (_token_digest(token),),
                )
        finally:
            connection.close()
