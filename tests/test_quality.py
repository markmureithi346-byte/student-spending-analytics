from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from student_spending import database, load, quality
from student_spending.validate import CleanTransaction

NOW = "2026-10-26T12:00:00+00:00"

PROFILES = [
    {
        "student_id": "STU-001",
        "profile_label": "Profile A",
        "campus": "Main Campus",
        "study_year": 2,
        "monthly_income_cents": 3_200_000,
    }
]


def transaction(transaction_id: str, when: str = "2026-08-10") -> CleanTransaction:
    return CleanTransaction(
        transaction_id=transaction_id,
        student_id="STU-001",
        transaction_date=when,
        amount_cents=45_000,
        category="Food",
        description="Lunch",
        payment_method="M-Pesa",
        merchant="Cafeteria",
        is_recurring=False,
        source_line=2,
    )


class QualityCheckTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.connection = database.connect(Path(self._tmp.name) / "test.db")
        self.addCleanup(self.connection.close)
        database.initialize_database(self.connection)
        load.ensure_categories(self.connection)
        load.load_students(self.connection, PROFILES)
        load.load_budgets(
            self.connection,
            [
                {
                    "student_id": "STU-001",
                    "budget_month": "2026-08",
                    "category": "Food",
                    "budget_cents": 500_000,
                }
            ],
        )
        load.load_transactions(
            self.connection, [transaction("TXN-0001"), transaction("TXN-0002")], NOW
        )
        load.start_run(self.connection, "run-1", "input.csv", NOW)
        load.finish_run(
            self.connection,
            "run-1",
            status="success",
            finished_at=NOW,
            counts={
                "rows_read": 2,
                "rows_accepted": 2,
                "rows_rejected": 0,
                "rows_quarantined": 0,
                "rows_inserted": 2,
                "rows_updated": 0,
                "rows_unchanged": 0,
            },
        )

    def results(self, run_id: str = "run-1") -> dict[str, bool]:
        return {result.name: result.passed for result in quality.run_checks(self.connection, run_id)}

    def test_all_checks_pass_on_healthy_data(self) -> None:
        results = self.results()
        failed = [name for name, passed in results.items() if not passed]
        self.assertEqual(failed, [])
        self.assertEqual(len(results), 12)

    def test_reconciliation_detects_count_mismatch(self) -> None:
        self.connection.execute(
            "UPDATE pipeline_runs SET rows_read = 3 WHERE run_id = 'run-1'"
        )
        results = self.results()
        self.assertFalse(results[quality.CHECK_RECONCILIATION])
        self.assertTrue(results[quality.CHECK_VIEW_PARITY])

    def test_future_dated_transaction_is_detected(self) -> None:
        self.connection.execute(
            """
            INSERT INTO transactions (
                transaction_id, student_id, transaction_date, amount_cents, category,
                description, payment_method, merchant, is_recurring, record_hash,
                first_loaded_at, last_updated_at
            ) VALUES ('TXN-0003', 'STU-001', '2099-01-01', 1000, 'Food',
                      'Future', 'M-Pesa', 'Cafeteria', 0, 'hash', ?, ?)
            """,
            (NOW, NOW),
        )
        self.connection.commit()
        self.assertFalse(self.results()[quality.CHECK_FUTURE_DATES])

    def test_blank_text_is_detected(self) -> None:
        self.connection.execute(
            """
            INSERT INTO transactions (
                transaction_id, student_id, transaction_date, amount_cents, category,
                description, payment_method, merchant, is_recurring, record_hash,
                first_loaded_at, last_updated_at
            ) VALUES ('TXN-0004', 'STU-001', '2026-08-11', 1000, 'Food',
                      '', 'M-Pesa', 'Cafeteria', 0, 'hash-2', ?, ?)
            """,
            (NOW, NOW),
        )
        self.connection.commit()
        self.assertFalse(self.results()[quality.CHECK_BLANK_TEXT])

    def test_results_are_persisted(self) -> None:
        results = quality.run_checks(self.connection, "run-1")
        quality.save_results(self.connection, "run-1", results, NOW)
        quality.save_results(self.connection, "run-1", results, NOW)
        stored = self.connection.execute(
            "SELECT COUNT(*) FROM data_quality_results WHERE run_id = 'run-1'"
        ).fetchone()[0]
        self.assertEqual(stored, len(results))

    def test_unknown_run_raises(self) -> None:
        with self.assertRaises(ValueError):
            quality.run_checks(self.connection, "missing-run")


if __name__ == "__main__":
    unittest.main()
