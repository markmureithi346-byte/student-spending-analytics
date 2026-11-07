"""Local demo accounts for the money planner and upload workspace.

Passwords are hashed with scrypt before they touch disk and sessions are
opaque random tokens; the database stores only a SHA-256 digest of each token.
Recovery codes are also stored only as digests and are shown once. This is a
learning feature on a loopback server, not a production identity system: there
is no email delivery, remote provider or email verification.
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

from .legal import POLICY_VERSION

SESSION_COOKIE = "ssa_session"
SESSION_SECONDS = 8 * 60 * 60
MIN_PASSWORD_LENGTH = 10
MAX_PASSWORD_LENGTH = 128
MAX_DISPLAY_NAME_LENGTH = 40
MAX_EMAIL_LENGTH = 120
RECOVERY_CODE_LENGTH = 16

_SCRYPT_N = 2 ** 14
_SCRYPT_R = 8
_SCRYPT_P = 1
_SCRYPT_DKLEN = 32
_EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_RECOVERY_ALPHABET = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS accounts (
    account_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    display_name TEXT NOT NULL,
    email        TEXT NOT NULL UNIQUE COLLATE NOCASE,
    password_hash TEXT NOT NULL,
    created_at   TEXT NOT NULL,
    consent_at   TEXT,
    policy_version TEXT,
    recovery_hash TEXT
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

_ACCOUNT_COLUMNS = (
    "account_id, display_name, email, created_at, consent_at, policy_version, "
    "recovery_hash"
)


class AccountError(ValueError):
    """A sign-up or sign-in request that cannot be accepted."""


@dataclass(frozen=True)
class Account:
    account_id: int
    display_name: str
    email: str
    created_at: str
    consent_at: str | None = None
    policy_version: str | None = None
    recovery_configured: bool = False


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


def new_recovery_code() -> str:
    """Return a 16-character code in four groups, e.g. ``7K2M-9QXA-...``."""
    raw = "".join(
        secrets.choice(_RECOVERY_ALPHABET) for _ in range(RECOVERY_CODE_LENGTH)
    )
    return "-".join(raw[index:index + 4] for index in range(0, len(raw), 4))


def _recovery_digest(code: str) -> str:
    normalised = re.sub(r"[^A-Z0-9]", "", code.upper())
    return hashlib.sha256(
        ("plan-it-recovery:" + normalised).encode("utf-8")
    ).hexdigest()


def _row_to_account(row: sqlite3.Row) -> Account:
    return Account(
        account_id=int(row["account_id"]),
        display_name=str(row["display_name"]),
        email=str(row["email"]),
        created_at=str(row["created_at"]),
        consent_at=(
            str(row["consent_at"]) if row["consent_at"] is not None else None
        ),
        policy_version=(
            str(row["policy_version"])
            if row["policy_version"] is not None
            else None
        ),
        recovery_configured=row["recovery_hash"] is not None,
    )


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
            columns = {
                str(row[1])
                for row in connection.execute("PRAGMA table_info(accounts)")
            }
            additions = {
                "consent_at": "consent_at TEXT",
                "policy_version": "policy_version TEXT",
                "recovery_hash": "recovery_hash TEXT",
            }
            for name, definition in additions.items():
                if name not in columns:
                    connection.execute(
                        f"ALTER TABLE accounts ADD COLUMN {definition}"
                    )
            connection.commit()
        finally:
            connection.close()

    def create_account(
        self,
        display_name: str,
        email: str,
        password: str,
        *,
        consented: bool = False,
    ) -> Account:
        name = validate_display_name(display_name)
        address = validate_email(email)
        validate_password(password)
        created_at = _stamp(_now())
        consent_at = created_at if consented else None
        policy_version = POLICY_VERSION if consented else None
        connection = self._connect()
        try:
            with connection:
                cursor = connection.execute(
                    "INSERT INTO accounts (display_name, email, password_hash, "
                    "created_at, consent_at, policy_version) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        name,
                        address,
                        hash_password(password),
                        created_at,
                        consent_at,
                        policy_version,
                    ),
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
            consent_at=consent_at,
            policy_version=policy_version,
            recovery_configured=False,
        )

    def authenticate(self, email: str, password: str) -> Account | None:
        address = normalise_email(email)
        connection = self._connect()
        try:
            row = connection.execute(
                f"SELECT {_ACCOUNT_COLUMNS}, password_hash FROM accounts "
                "WHERE email = ?",
                (address,),
            ).fetchone()
        finally:
            connection.close()
        if row is None:
            verify_password(password, _dummy_hash())
            return None
        if not verify_password(password, str(row["password_hash"])):
            return None
        return _row_to_account(row)

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
                f"SELECT {', '.join('a.' + name for name in _ACCOUNT_COLUMNS.split(', '))} "
                "FROM sessions AS s JOIN accounts AS a "
                "ON a.account_id = s.account_id "
                "WHERE s.token_hash = ? AND s.expires_at > ?",
                (_token_digest(token), now),
            ).fetchone()
        finally:
            connection.close()
        if row is None:
            return None
        return _row_to_account(row)

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

    def delete_sessions(self, account_id: int) -> None:
        connection = self._connect()
        try:
            with connection:
                connection.execute(
                    "DELETE FROM sessions WHERE account_id = ?", (account_id,)
                )
        finally:
            connection.close()

    def verify_account_password(self, account_id: int, password: str) -> bool:
        connection = self._connect()
        try:
            row = connection.execute(
                "SELECT password_hash FROM accounts WHERE account_id = ?",
                (account_id,),
            ).fetchone()
        finally:
            connection.close()
        if row is None:
            verify_password(password, _dummy_hash())
            return False
        return verify_password(password, str(row["password_hash"]))

    def set_consent(self, account_id: int) -> bool:
        connection = self._connect()
        try:
            with connection:
                cursor = connection.execute(
                    "UPDATE accounts SET consent_at = ?, policy_version = ? "
                    "WHERE account_id = ?",
                    (_stamp(_now()), POLICY_VERSION, account_id),
                )
        finally:
            connection.close()
        return cursor.rowcount > 0

    def generate_recovery_code(
        self, account_id: int, password: str
    ) -> str | None:
        if not self.verify_account_password(account_id, password):
            return None
        code = new_recovery_code()
        connection = self._connect()
        try:
            with connection:
                connection.execute(
                    "UPDATE accounts SET recovery_hash = ? WHERE account_id = ?",
                    (_recovery_digest(code), account_id),
                )
        finally:
            connection.close()
        return code

    def reset_password(
        self, email: str, recovery_code: str, new_password: str
    ) -> bool:
        """Consume a recovery code and set a new password.

        The code is single-use: a successful reset clears it and ends every
        existing session. Unknown emails and bad codes take the same generic
        path and return the same result.
        """
        validate_password(new_password)
        address = normalise_email(email)
        digest = _recovery_digest(recovery_code)
        connection = self._connect()
        try:
            row = connection.execute(
                "SELECT account_id, recovery_hash FROM accounts WHERE email = ?",
                (address,),
            ).fetchone()
            if row is None or not row["recovery_hash"]:
                hmac.compare_digest(digest, _recovery_digest("0000-0000-0000-0000"))
                return False
            if not hmac.compare_digest(digest, str(row["recovery_hash"])):
                return False
            account_id = int(row["account_id"])
            with connection:
                connection.execute(
                    "UPDATE accounts SET password_hash = ?, recovery_hash = NULL "
                    "WHERE account_id = ?",
                    (hash_password(new_password), account_id),
                )
                connection.execute(
                    "DELETE FROM sessions WHERE account_id = ?", (account_id,)
                )
        finally:
            connection.close()
        return True

    def change_password(
        self, account_id: int, current_password: str, new_password: str
    ) -> bool:
        validate_password(new_password)
        if not self.verify_account_password(account_id, current_password):
            return False
        connection = self._connect()
        try:
            with connection:
                connection.execute(
                    "UPDATE accounts SET password_hash = ? WHERE account_id = ?",
                    (hash_password(new_password), account_id),
                )
                connection.execute(
                    "DELETE FROM sessions WHERE account_id = ?", (account_id,)
                )
        finally:
            connection.close()
        return True

    def delete_account(self, account_id: int) -> bool:
        connection = self._connect()
        try:
            with connection:
                connection.execute(
                    "DELETE FROM sessions WHERE account_id = ?", (account_id,)
                )
                cursor = connection.execute(
                    "DELETE FROM accounts WHERE account_id = ?", (account_id,)
                )
        finally:
            connection.close()
        return cursor.rowcount > 0
