"""Write dimensions, facts and rejection audit trails into SQLite."""

from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
from dataclasses import dataclass

from . import config
from .validate import CleanTransaction, RejectedRecord

logger = logging.getLogger(__name__)

_UPSERT_TRANSACTION = """
INSERT INTO transactions (
    transaction_id, student_id, transaction_date, amount_cents, category,
    description, payment_method, merchant, is_recurring, record_hash,
    is_anomaly, anomaly_reason, first_loaded_at, last_updated_at
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, NULL, ?, ?)
ON CONFLICT (transaction_id) DO UPDATE SET
    student_id       = excluded.student_id,
    transaction_date = excluded.transaction_date,
    amount_cents     = excluded.amount_cents,
    category         = excluded.category,
    description      = excluded.description,
    payment_method   = excluded.payment_method,
    merchant         = excluded.merchant,
    is_recurring     = excluded.is_recurring,
    record_hash      = excluded.record_hash,
    is_anomaly       = 0,
    anomaly_reason   = NULL,
    last_updated_at  = excluded.last_updated_at
WHERE transactions.record_hash <> excluded.record_hash
"""


@dataclass(frozen=True)
class LoadStats:
    inserted: int
    updated: int
    unchanged: int

    @property
    def total(self) -> int:
        return self.inserted + self.updated + self.unchanged


def record_hash(transaction: CleanTransaction) -> str:
    """Stable fingerprint of the business fields used for change detection."""
    payload = "|".join(str(value) for value in transaction.content_signature())
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def ensure_categories(connection: sqlite3.Connection) -> int:
    rows = [
        (category, 1 if discretionary else 0)
        for category, discretionary in config.CATEGORY_DISCRETIONARY.items()
    ]
    with connection:
        connection.executemany(
            "INSERT INTO categories (category, is_discretionary) VALUES (?, ?) "
            "ON CONFLICT (category) DO UPDATE SET is_discretionary = excluded.is_discretionary",
            rows,
        )
    logger.info("ensured %d categories", len(rows))
    return len(rows)


def load_students(connection: sqlite3.Connection, profiles: list[dict[str, object]]) -> int:
    rows = [
        (
            profile["student_id"],
            profile["profile_label"],
            profile["campus"],
            profile["study_year"],
            profile["monthly_income_cents"],
        )
        for profile in profiles
    ]
    with connection:
        connection.executemany(
            """
            INSERT INTO students (
                student_id, profile_label, campus, study_year, monthly_income_cents
            ) VALUES (?, ?, ?, ?, ?)
            ON CONFLICT (student_id) DO UPDATE SET
                profile_label        = excluded.profile_label,
                campus               = excluded.campus,
                study_year           = excluded.study_year,
                monthly_income_cents = excluded.monthly_income_cents
            """,
            rows,
        )
    logger.info("loaded %d student profiles", len(rows))
    return len(rows)


def load_budgets(connection: sqlite3.Connection, budgets: list[dict[str, object]]) -> int:
    rows = [
        (
            budget["student_id"],
            budget["budget_month"],
            budget["category"],
            budget["budget_cents"],
        )
        for budget in budgets
    ]
    with connection:
        connection.executemany(
            """
            INSERT INTO budgets (student_id, budget_month, category, budget_cents)
            VALUES (?, ?, ?, ?)
            ON CONFLICT (student_id, budget_month, category) DO UPDATE SET
                budget_cents = excluded.budget_cents
            """,
            rows,
        )
    logger.info("loaded %d budget rows", len(rows))
    return len(rows)


def load_transactions(
    connection: sqlite3.Connection,
    transactions: list[CleanTransaction],
    loaded_at: str,
) -> LoadStats:
    """Insert new transactions and update changed ones; unchanged rows are skipped."""
    if not transactions:
        return LoadStats(0, 0, 0)

    existing: dict[str, str] = {}
    identifiers = [transaction.transaction_id for transaction in transactions]
    for start in range(0, len(identifiers), 500):
        chunk = identifiers[start : start + 500]
        placeholders = ",".join("?" for _ in chunk)
        query = f"SELECT transaction_id, record_hash FROM transactions WHERE transaction_id IN ({placeholders})"
        for row in connection.execute(query, chunk):
            existing[row["transaction_id"]] = row["record_hash"]

    inserted = updated = unchanged = 0
    rows: list[tuple[object, ...]] = []
    for transaction in transactions:
        fingerprint = record_hash(transaction)
        previous = existing.get(transaction.transaction_id)
        if previous is None:
            inserted += 1
        elif previous != fingerprint:
            updated += 1
        else:
            unchanged += 1
            continue
        rows.append(
            (
                transaction.transaction_id,
                transaction.student_id,
                transaction.transaction_date,
                transaction.amount_cents,
                transaction.category,
                transaction.description,
                transaction.payment_method,
                transaction.merchant,
                1 if transaction.is_recurring else 0,
                fingerprint,
                loaded_at,
                loaded_at,
            )
        )

    with connection:
        connection.executemany(_UPSERT_TRANSACTION, rows)

    stats = LoadStats(inserted=inserted, updated=updated, unchanged=unchanged)
    logger.info(
        "loaded transactions: inserted=%d updated=%d unchanged=%d",
        stats.inserted,
        stats.updated,
        stats.unchanged,
    )
    return stats


def save_rejections(
    connection: sqlite3.Connection,
    run_id: str,
    rejections: list[RejectedRecord],
    recorded_at: str,
) -> None:
    quarantined = []
    rejected = []
    for record in rejections:
        payload = json.dumps(record.raw_payload, sort_keys=True) if record.raw_payload else "{}"
        if record.outcome == "quarantined":
            quarantined.append(
                (
                    run_id,
                    record.transaction_id,
                    record.student_id,
                    record.reason_code,
                    record.reason_detail,
                    payload,
                    recorded_at,
                )
            )
        else:
            rejected.append(
                (
                    run_id,
                    record.transaction_id,
                    record.reason_code,
                    record.reason_detail,
                    payload,
                    recorded_at,
                )
            )

    with connection:
        connection.executemany(
            """
            INSERT INTO transactions_quarantine (
                run_id, transaction_id, student_id, reason_code,
                reason_detail, raw_payload, quarantined_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            quarantined,
        )
        connection.executemany(
            """
            INSERT INTO rejected_transactions (
                run_id, transaction_id, reason_code, reason_detail, raw_payload, rejected_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            rejected,
        )
    logger.info(
        "recorded %d quarantined and %d rejected row(s)", len(quarantined), len(rejected)
    )


def start_run(
    connection: sqlite3.Connection, run_id: str, input_file: str, started_at: str
) -> None:
    with connection:
        connection.execute(
            """
            INSERT INTO pipeline_runs (run_id, started_at, status, input_file)
            VALUES (?, ?, 'running', ?)
            """,
            (run_id, started_at, input_file),
        )


def finish_run(
    connection: sqlite3.Connection,
    run_id: str,
    *,
    status: str,
    finished_at: str,
    counts: dict[str, int],
    message: str | None = None,
) -> None:
    with connection:
        connection.execute(
            """
            UPDATE pipeline_runs SET
                finished_at      = ?,
                status           = ?,
                rows_read        = ?,
                rows_accepted    = ?,
                rows_rejected    = ?,
                rows_quarantined = ?,
                rows_inserted    = ?,
                rows_updated     = ?,
                rows_unchanged   = ?,
                message          = ?
            WHERE run_id = ?
            """,
            (
                finished_at,
                status,
                counts.get("rows_read", 0),
                counts.get("rows_accepted", 0),
                counts.get("rows_rejected", 0),
                counts.get("rows_quarantined", 0),
                counts.get("rows_inserted", 0),
                counts.get("rows_updated", 0),
                counts.get("rows_unchanged", 0),
                message,
                run_id,
            ),
        )
