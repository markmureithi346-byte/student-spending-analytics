"""Analytical queries and the anomaly flagging step.

The views live in sql/schema.sql; this module is the only place that reads
them, so the report and the tests agree on what a number means.
"""

from __future__ import annotations

import logging
import sqlite3
from datetime import date

from . import config

logger = logging.getLogger(__name__)


def _rows(connection: sqlite3.Connection, sql: str, params: tuple[object, ...] = ()) -> list[dict]:
    return [dict(row) for row in connection.execute(sql, params)]


def _scalar(connection: sqlite3.Connection, sql: str, params: tuple[object, ...] = ()) -> object:
    row = connection.execute(sql, params).fetchone()
    return None if row is None else row[0]


def flag_anomalies(connection: sqlite3.Connection) -> int:
    """Flag transactions far above the student's own category average.

    Rule: at least 3 historical transactions for that student/category, the
    amount is more than ANOMALY_MULTIPLIER times that average, and it is
    above ANOMALY_FLOOR_CENTS. Flags are recomputed on every run so they can
    never go stale.
    """
    with connection:
        connection.execute("UPDATE transactions SET is_anomaly = 0, anomaly_reason = NULL")

    candidates = _rows(
        connection,
        """
        WITH category_stats AS (
            SELECT student_id,
                   category,
                   AVG(amount_cents) AS avg_cents,
                   COUNT(*)          AS transaction_count
            FROM transactions
            GROUP BY student_id, category
        )
        SELECT t.transaction_id,
               t.amount_cents,
               t.category,
               s.avg_cents,
               s.transaction_count
        FROM transactions AS t
        JOIN category_stats AS s
          ON s.student_id = t.student_id
         AND s.category   = t.category
        WHERE s.transaction_count >= 3
          AND t.amount_cents > s.avg_cents * ?
          AND t.amount_cents > ?
        """,
        (config.ANOMALY_MULTIPLIER, config.ANOMALY_FLOOR_CENTS),
    )

    updates = []
    for candidate in candidates:
        ratio = candidate["amount_cents"] / candidate["avg_cents"]
        reason = (
            f"{ratio:.1f}x the student's average {candidate['category']} spend "
            f"(average KES {candidate['avg_cents'] / 100:,.2f})"
        )
        updates.append((reason, candidate["transaction_id"]))

    with connection:
        connection.executemany(
            "UPDATE transactions SET is_anomaly = 1, anomaly_reason = ? WHERE transaction_id = ?",
            updates,
        )

    logger.info("flagged %d transaction(s) as anomalous", len(updates))
    return len(updates)


def kpis(connection: sqlite3.Connection) -> dict[str, object]:
    row = connection.execute(
        """
        SELECT COUNT(*)                          AS transaction_count,
               COUNT(DISTINCT student_id)        AS student_count,
               COALESCE(SUM(amount_cents), 0)    AS total_cents,
               ROUND(COALESCE(AVG(amount_cents), 0) / 100.0, 2) AS avg_transaction_kes,
               MIN(transaction_date)             AS first_date,
               MAX(transaction_date)             AS last_date,
               COALESCE(SUM(is_anomaly), 0)      AS flagged_count
        FROM transactions
        """
    ).fetchone()

    total_kes = row["total_cents"] / 100.0
    first_date, last_date = row["first_date"], row["last_date"]
    days = 0
    if first_date and last_date:
        days = (date.fromisoformat(last_date) - date.fromisoformat(first_date)).days + 1
    return {
        "transaction_count": row["transaction_count"],
        "student_count": row["student_count"],
        "total_kes": total_kes,
        "avg_transaction_kes": row["avg_transaction_kes"],
        "avg_daily_kes": round(total_kes / days, 2) if days else 0.0,
        "first_date": first_date,
        "last_date": last_date,
        "days_covered": days,
        "flagged_count": row["flagged_count"],
    }


def monthly_totals(connection: sqlite3.Connection) -> list[dict]:
    return _rows(connection, "SELECT * FROM v_monthly_totals ORDER BY transaction_month")


def category_totals(connection: sqlite3.Connection) -> list[dict]:
    return _rows(
        connection,
        "SELECT * FROM v_category_totals ORDER BY total_cents DESC, category",
    )


def student_totals(connection: sqlite3.Connection) -> list[dict]:
    return _rows(
        connection,
        "SELECT * FROM v_student_totals ORDER BY total_cents DESC, student_id",
    )


def weekday_spending(connection: sqlite3.Connection) -> list[dict]:
    order = """
        CASE weekday_name
            WHEN 'Monday' THEN 1 WHEN 'Tuesday' THEN 2 WHEN 'Wednesday' THEN 3
            WHEN 'Thursday' THEN 4 WHEN 'Friday' THEN 5 WHEN 'Saturday' THEN 6
            ELSE 7
        END
    """
    return _rows(
        connection,
        f"SELECT *, {order} AS sort_order FROM v_weekday_spending ORDER BY sort_order",
    )


def budget_overruns(connection: sqlite3.Connection, limit: int = 10) -> list[dict]:
    return _rows(
        connection,
        """
        SELECT profile_label, budget_month, category, budget_kes, actual_kes, variance_kes
        FROM v_budget_vs_actual
        WHERE is_over_budget = 1
        ORDER BY variance_kes DESC
        LIMIT ?
        """,
        (limit,),
    )


def budget_summary(connection: sqlite3.Connection) -> dict[str, float | int]:
    row = connection.execute(
        """
        SELECT COUNT(*)                                            AS budget_lines,
               COALESCE(SUM(is_over_budget), 0)                    AS over_budget_lines,
               ROUND(COALESCE(SUM(budget_kes), 0), 2)              AS total_budget_kes,
               ROUND(COALESCE(SUM(actual_kes), 0), 2)              AS total_actual_kes
        FROM v_budget_vs_actual
        """
    ).fetchone()
    return dict(row)


def flagged_transactions(connection: sqlite3.Connection, limit: int = 15) -> list[dict]:
    return _rows(
        connection,
        "SELECT * FROM v_flagged_transactions ORDER BY amount_kes DESC LIMIT ?",
        (limit,),
    )


def top_merchants(connection: sqlite3.Connection, limit: int = 5) -> list[dict]:
    return _rows(
        connection,
        """
        SELECT merchant, COUNT(*) AS transaction_count, SUM(amount_cents) / 100.0 AS total_kes
        FROM v_transactions
        GROUP BY merchant
        ORDER BY SUM(amount_cents) DESC, merchant
        LIMIT ?
        """,
        (limit,),
    )


def payment_mix(connection: sqlite3.Connection) -> list[dict]:
    return _rows(
        connection,
        """
        SELECT payment_method, COUNT(*) AS transaction_count, SUM(amount_cents) / 100.0 AS total_kes
        FROM v_transactions
        GROUP BY payment_method
        ORDER BY SUM(amount_cents) DESC, payment_method
        """,
    )


def weekly_change(connection: sqlite3.Connection) -> list[dict]:
    return _rows(
        connection,
        "SELECT * FROM v_week_over_week ORDER BY year_week, profile_label",
    )


def run_row(connection: sqlite3.Connection, run_id: str) -> dict:
    row = connection.execute("SELECT * FROM pipeline_runs WHERE run_id = ?", (run_id,)).fetchone()
    if row is None:
        raise ValueError(f"unknown run_id {run_id!r}")
    return dict(row)


def quality_results(connection: sqlite3.Connection, run_id: str) -> list[dict]:
    return _rows(
        connection,
        """
        SELECT check_name, passed, observed, expected
        FROM data_quality_results
        WHERE run_id = ?
        ORDER BY check_name
        """,
        (run_id,),
    )
