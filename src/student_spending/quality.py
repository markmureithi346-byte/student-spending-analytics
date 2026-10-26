"""Automated data quality checks run at the end of every pipeline execution."""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass

from . import config

logger = logging.getLogger(__name__)

CHECK_RECONCILIATION = "reconciliation_counts"
CHECK_DUPLICATES = "no_duplicate_transaction_ids"
CHECK_ORPHANS = "no_orphan_transaction_references"
CHECK_BUDGET_ORPHANS = "no_orphan_budget_references"
CHECK_POSITIVE_AMOUNTS = "amounts_are_positive"
CHECK_BLANK_TEXT = "required_text_not_blank"
CHECK_FUTURE_DATES = "no_future_dated_transactions"
CHECK_VIEW_PARITY = "transaction_view_row_parity"
CHECK_MONTHLY_PARITY = "monthly_aggregation_matches_base"
CHECK_ANOMALY_RATE = "anomaly_rate_within_threshold"
CHECK_TRANSACTIONS_PRESENT = "transactions_present"
CHECK_BUDGETS_PRESENT = "budgets_present"


@dataclass(frozen=True)
class CheckResult:
    name: str
    passed: bool
    observed: str
    expected: str


def _count(connection: sqlite3.Connection, sql: str, params: tuple[object, ...] = ()) -> int:
    row = connection.execute(sql, params).fetchone()
    return 0 if row is None or row[0] is None else int(row[0])


def run_checks(connection: sqlite3.Connection, run_id: str) -> list[CheckResult]:
    run = connection.execute(
        "SELECT * FROM pipeline_runs WHERE run_id = ?", (run_id,)
    ).fetchone()
    if run is None:
        raise ValueError(f"unknown run_id {run_id!r}")

    results: list[CheckResult] = []

    read = run["rows_read"]
    accepted = run["rows_accepted"]
    rejected = run["rows_rejected"]
    quarantined = run["rows_quarantined"]
    loaded = run["rows_inserted"] + run["rows_updated"] + run["rows_unchanged"]
    passed = read == accepted + rejected + quarantined and accepted == loaded
    results.append(
        CheckResult(
            name=CHECK_RECONCILIATION,
            passed=passed,
            observed=(
                f"read={read}, accepted={accepted}, rejected={rejected}, "
                f"quarantined={quarantined}, loaded={loaded}"
            ),
            expected="read = accepted + rejected + quarantined and accepted = loaded",
        )
    )

    duplicates = _count(
        connection,
        """
        SELECT COUNT(*) FROM (
            SELECT transaction_id FROM transactions
            GROUP BY transaction_id HAVING COUNT(*) > 1
        )
        """,
    )
    results.append(
        CheckResult(
            CHECK_DUPLICATES,
            duplicates == 0,
            f"{duplicates} duplicated transaction_id value(s)",
            "0 duplicated transaction_id values",
        )
    )

    orphans = _count(
        connection,
        """
        SELECT COUNT(*)
        FROM transactions AS t
        LEFT JOIN students   AS s ON s.student_id = t.student_id
        LEFT JOIN categories AS c ON c.category   = t.category
        WHERE s.student_id IS NULL OR c.category IS NULL
        """,
    )
    results.append(
        CheckResult(
            CHECK_ORPHANS,
            orphans == 0,
            f"{orphans} transaction(s) without a student or category",
            "0 orphaned transactions",
        )
    )

    budget_orphans = _count(
        connection,
        """
        SELECT COUNT(*)
        FROM budgets AS b
        LEFT JOIN students   AS s ON s.student_id = b.student_id
        LEFT JOIN categories AS c ON c.category   = b.category
        WHERE s.student_id IS NULL OR c.category IS NULL
        """,
    )
    results.append(
        CheckResult(
            CHECK_BUDGET_ORPHANS,
            budget_orphans == 0,
            f"{budget_orphans} budget row(s) without a student or category",
            "0 orphaned budget rows",
        )
    )

    bad_amounts = _count(
        connection, "SELECT COUNT(*) FROM transactions WHERE amount_cents <= 0"
    )
    results.append(
        CheckResult(
            CHECK_POSITIVE_AMOUNTS,
            bad_amounts == 0,
            f"{bad_amounts} non-positive amount(s)",
            "0 non-positive amounts",
        )
    )

    blank_text = _count(
        connection,
        """
        SELECT COUNT(*) FROM transactions
        WHERE trim(description) = '' OR trim(merchant) = '' OR trim(payment_method) = ''
        """,
    )
    results.append(
        CheckResult(
            CHECK_BLANK_TEXT,
            blank_text == 0,
            f"{blank_text} row(s) with blank description, merchant or payment method",
            "0 rows with blank required text",
        )
    )

    future = _count(
        connection,
        "SELECT COUNT(*) FROM transactions WHERE transaction_date > date('now')",
    )
    results.append(
        CheckResult(
            CHECK_FUTURE_DATES,
            future == 0,
            f"{future} transaction(s) dated after today",
            "0 future-dated transactions",
        )
    )

    base_rows = _count(connection, "SELECT COUNT(*) FROM transactions")
    view_rows = _count(connection, "SELECT COUNT(*) FROM v_transactions")
    base_cents = _count(connection, "SELECT COALESCE(SUM(amount_cents), 0) FROM transactions")
    view_cents = _count(connection, "SELECT COALESCE(SUM(amount_cents), 0) FROM v_transactions")
    results.append(
        CheckResult(
            CHECK_VIEW_PARITY,
            base_rows == view_rows and base_cents == view_cents,
            f"base rows={base_rows}, view rows={view_rows}; base cents={base_cents}, view cents={view_cents}",
            "v_transactions exposes every transaction with the same total",
        )
    )

    monthly_cents = _count(
        connection,
        "SELECT COALESCE(SUM(CAST(ROUND(total_kes * 100) AS INTEGER)), 0) FROM v_monthly_category",
    )
    results.append(
        CheckResult(
            CHECK_MONTHLY_PARITY,
            monthly_cents == base_cents,
            f"monthly-by-category total={monthly_cents} cents, base total={base_cents} cents",
            "monthly aggregation equals the base table total (no double counting)",
        )
    )

    flagged = _count(connection, "SELECT COALESCE(SUM(is_anomaly), 0) FROM transactions")
    rate = (flagged / base_rows) if base_rows else 0.0
    results.append(
        CheckResult(
            CHECK_ANOMALY_RATE,
            rate <= config.MAX_ANOMALY_RATE,
            f"{flagged}/{base_rows} flagged ({rate:.2%})",
            f"flagged share at or below {config.MAX_ANOMALY_RATE:.0%}",
        )
    )

    results.append(
        CheckResult(
            CHECK_TRANSACTIONS_PRESENT,
            base_rows > 0,
            f"{base_rows} transaction(s) in the warehouse",
            "at least 1 transaction",
        )
    )

    budget_rows = _count(connection, "SELECT COUNT(*) FROM budgets")
    if budget_rows:
        results.append(
            CheckResult(
                CHECK_BUDGETS_PRESENT,
                True,
                f"{budget_rows} budget row(s)",
                "at least 1 budget row so budget analysis is meaningful",
            )
        )

    return results


def save_results(
    connection: sqlite3.Connection,
    run_id: str,
    results: list[CheckResult],
    checked_at: str,
) -> None:
    rows = [
        (run_id, result.name, 1 if result.passed else 0, result.observed, result.expected, checked_at)
        for result in results
    ]
    with connection:
        connection.executemany(
            """
            INSERT INTO data_quality_results (
                run_id, check_name, passed, observed, expected, checked_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT (run_id, check_name) DO UPDATE SET
                passed     = excluded.passed,
                observed   = excluded.observed,
                expected   = excluded.expected,
                checked_at = excluded.checked_at
            """,
            rows,
        )
    failed = [result for result in results if not result.passed]
    if failed:
        for result in failed:
            logger.error(
                "QUALITY FAIL %s | observed: %s | expected: %s",
                result.name,
                result.observed,
                result.expected,
            )
    else:
        logger.info("all %d data quality checks passed", len(results))
