"""SQLite connection handling and schema creation."""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

from . import config

logger = logging.getLogger(__name__)


def connect(db_path: Path | str) -> sqlite3.Connection:
    """Open a connection with foreign keys enforced and dict-like rows."""
    if isinstance(db_path, Path):
        db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(str(db_path))
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def initialize_database(connection: sqlite3.Connection) -> None:
    """Create tables, indexes and analytical views if they do not exist."""
    schema = config.SCHEMA_PATH.read_text(encoding="utf-8")
    connection.executescript(schema)
    connection.commit()
    logger.info("database schema ensured")


def reset_database(db_path: Path) -> None:
    """Delete the database file so the next run starts from nothing."""
    for suffix in ("", "-wal", "-shm"):
        candidate = Path(f"{db_path}{suffix}")
        if candidate.exists():
            candidate.unlink()
            logger.warning("removed existing database file %s", candidate.name)
