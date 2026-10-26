from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from student_spending import database, load
from student_spending.validate import CleanTransaction, RejectedRecord

NOW = "2026-10-26T12:00:00+00:00"
LATER = "2026-10-26T13:00:00+00:00"

PROFILES = [
    {
        "student_id": "STU-001",
        "profile_label": "Profile A",
        "campus": "Main Campus",
        "study_year": 2,
        "monthly_income_cents": 3_200_000,
    },
    {
        "student_id": "STU-002",
        "profile_label": "Profile B",
        "campus": "Main Campus",
        "study_year": 1,
        "monthly_income_cents": 2_100_000,
    },
]


def transaction(
    transaction_id: str = "TXN-0001",
    *,
    amount_cents: int = 45_000,
    student_id: str = "STU-001",
    transaction_date: str = "2026-08-10",
    category: str = "Food",
) -> CleanTransaction:
    return CleanTransaction(
        transaction_id=transaction_id,
        student_id=student_id,
        transaction_date=transaction_date,
        amount_cents=amount_cents,
        category=category,
        description="Lunch",
        payment_method="M-Pesa",
        merchant="Cafeteria",
        is_recurring=False,
        source_line=2,
    )


class LoadTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.connection = database.connect(Path(self._tmp.name) / "test.db")
        self.addCleanup(self.connection.close)
        database.initialize_database(self.connection)
        load.ensure_categories(self.connection)
        load.load_students(self.connection, PROFILES)

    def count(self, table: str) -> int:
        return self.connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


class TransactionLoadTests(LoadTestCase):
    def test_new_transactions_are_inserted(self) -> None:
        stats = load.load_transactions(
            self.connection,
            [transaction("TXN-0001"), transaction("TXN-0002", student_id="STU-002")],
            NOW,
        )
        self.assertEqual((stats.inserted, stats.updated, stats.unchanged), (2, 0, 0))
        self.assertEqual(self.count("transactions"), 2)

    def test_rerun_is_idempotent(self) -> None:
        rows = [transaction("TXN-0001"), transaction("TXN-0002")]
        load.load_transactions(self.connection, rows, NOW)
        stats = load.load_transactions(self.connection, rows, LATER)
        self.assertEqual((stats.inserted, stats.updated, stats.unchanged), (0, 0, 2))
        self.assertEqual(self.count("transactions"), 2)

    def test_changed_record_is_updated_not_duplicated(self) -> None:
        load.load_transactions(self.connection, [transaction("TXN-0001")], NOW)
        stats = load.load_transactions(
            self.connection, [transaction("TXN-0001", amount_cents=99_900)], LATER
        )
        self.assertEqual((stats.inserted, stats.updated, stats.unchanged), (0, 1, 0))
        self.assertEqual(self.count("transactions"), 1)
        row = self.connection.execute(
            "SELECT amount_cents, first_loaded_at, last_updated_at FROM transactions"
        ).fetchone()
        self.assertEqual(row["amount_cents"], 99_900)
        self.assertEqual(row["first_loaded_at"], NOW)
        self.assertEqual(row["last_updated_at"], LATER)

    def test_unknown_student_violates_foreign_key(self) -> None:
        with self.assertRaises(sqlite3.IntegrityError):
            load.load_transactions(
                self.connection, [transaction("TXN-0009", student_id="STU-999")], NOW
            )
        self.assertEqual(self.count("transactions"), 0)

    def test_non_positive_amount_violates_check_constraint(self) -> None:
        with self.assertRaises(sqlite3.IntegrityError):
            load.load_transactions(self.connection, [transaction(amount_cents=0)], NOW)

    def test_record_hash_is_stable_for_identical_content(self) -> None:
        first = load.record_hash(transaction("TXN-0001"))
        second = load.record_hash(transaction("TXN-0001"))
        changed = load.record_hash(transaction("TXN-0001", amount_cents=1))
        self.assertEqual(first, second)
        self.assertNotEqual(first, changed)


class DimensionLoadTests(LoadTestCase):
    def test_categories_are_seeded_once(self) -> None:
        first = load.ensure_categories(self.connection)
        second = load.ensure_categories(self.connection)
        self.assertEqual(first, second)
        self.assertEqual(self.count("categories"), first)

    def test_budget_upsert_is_idempotent(self) -> None:
        budget = {
            "student_id": "STU-001",
            "budget_month": "2026-08",
            "category": "Food",
            "budget_cents": 500_000,
        }
        load.load_budgets(self.connection, [budget])
        load.load_budgets(self.connection, [{**budget, "budget_cents": 650_000}])
        self.assertEqual(self.count("budgets"), 1)
        value = self.connection.execute("SELECT budget_cents FROM budgets").fetchone()[0]
        self.assertEqual(value, 650_000)


class RejectionStorageTests(LoadTestCase):
    def test_rejections_are_split_by_outcome(self) -> None:
        rejections = [
            RejectedRecord(3, "TXN-1", "STU-001", "quarantined", "INVALID_DATE", "bad date", {"a": "b"}),
            RejectedRecord(4, "TXN-2", "STU-001", "rejected", "DUPLICATE_IDENTICAL", "copy", None),
        ]
        load.save_rejections(self.connection, "run-1", rejections, NOW)
        self.assertEqual(self.count("transactions_quarantine"), 1)
        self.assertEqual(self.count("rejected_transactions"), 1)


class RunAccountingTests(LoadTestCase):
    def test_run_lifecycle_records_counts(self) -> None:
        load.start_run(self.connection, "run-1", "input.csv", NOW)
        load.finish_run(
            self.connection,
            "run-1",
            status="success",
            finished_at=LATER,
            counts={
                "rows_read": 10,
                "rows_accepted": 7,
                "rows_rejected": 1,
                "rows_quarantined": 2,
                "rows_inserted": 7,
                "rows_updated": 0,
                "rows_unchanged": 0,
            },
        )
        row = self.connection.execute("SELECT * FROM pipeline_runs").fetchone()
        self.assertEqual(row["status"], "success")
        self.assertEqual(row["rows_read"], 10)
        self.assertEqual(row["finished_at"], LATER)


if __name__ == "__main__":
    unittest.main()
