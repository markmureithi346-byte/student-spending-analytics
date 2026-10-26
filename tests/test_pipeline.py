from __future__ import annotations

import contextlib
import dataclasses
import io
import sqlite3
import tempfile
import unittest
from pathlib import Path

from student_spending import database
from student_spending.cli import PipelineOptions, run_pipeline
from student_spending.synthetic import generate_dataset


class PipelineIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.raw = self.root / "raw"
        self.summary = generate_dataset(self.raw)
        self.options = PipelineOptions(
            transactions_csv=self.raw / "student_expenses.csv",
            profiles_csv=self.raw / "student_profiles.csv",
            budgets_csv=self.raw / "student_budgets.csv",
            db_path=self.root / "warehouse" / "test.db",
            reports_dir=self.root / "reports",
            quarantine_dir=self.root / "quarantine",
            full_refresh=True,
        )

    def run_pipeline_quietly(self, options: PipelineOptions) -> int:
        with contextlib.redirect_stdout(io.StringIO()):
            return run_pipeline(options)

    def connect(self) -> sqlite3.Connection:
        return database.connect(self.options.db_path)

    def last_run(self, connection: sqlite3.Connection) -> sqlite3.Row:
        return connection.execute(
            "SELECT * FROM pipeline_runs ORDER BY rowid DESC LIMIT 1"
        ).fetchone()

    def test_full_pipeline_reconciles_and_passes_quality(self) -> None:
        self.assertEqual(self.run_pipeline_quietly(self.options), 0)

        connection = self.connect()
        self.addCleanup(connection.close)
        run = self.last_run(connection)

        self.assertEqual(run["status"], "success")
        self.assertEqual(run["rows_read"], self.summary["transactions"])
        self.assertEqual(run["rows_rejected"], 4)
        self.assertGreaterEqual(run["rows_quarantined"], 20)
        self.assertEqual(
            run["rows_read"],
            run["rows_accepted"] + run["rows_rejected"] + run["rows_quarantined"],
        )
        self.assertEqual(
            run["rows_accepted"],
            run["rows_inserted"] + run["rows_updated"] + run["rows_unchanged"],
        )

        failed = connection.execute(
            "SELECT check_name, observed FROM data_quality_results WHERE passed = 0"
        ).fetchall()
        self.assertEqual([tuple(row) for row in failed], [])

        reasons = {
            row[0]
            for row in connection.execute(
                "SELECT reason_code FROM transactions_quarantine "
                "UNION SELECT reason_code FROM rejected_transactions"
            )
        }
        for expected in (
            "MALFORMED_ROW",
            "INVALID_DATE",
            "NON_POSITIVE_AMOUNT",
            "UNEXPECTED_CATEGORY",
            "UNKNOWN_STUDENT",
            "MISSING_REQUIRED_FIELD",
            "DATE_IN_FUTURE",
            "DUPLICATE_CONFLICT",
            "DUPLICATE_IDENTICAL",
        ):
            self.assertIn(expected, reasons)

        categories = {
            row[0] for row in connection.execute("SELECT DISTINCT category FROM transactions")
        }
        self.assertTrue(categories.issubset({"Food", "Transport", "Rent", "Utilities", "Education",
                                             "Airtime and Internet", "Entertainment",
                                             "Personal Care", "Other"}))
        self.assertGreater(
            connection.execute("SELECT COUNT(*) FROM transactions WHERE is_anomaly = 1").fetchone()[0],
            0,
        )

        report_path = self.options.reports_dir / "spending_report.html"
        self.assertTrue(report_path.exists())
        report_text = report_path.read_text(encoding="utf-8")
        self.assertIn("Student Spending Analytics", report_text)
        self.assertIn("synthetic", report_text.lower())
        self.assertTrue((self.options.quarantine_dir / f"rejections_{run['run_id']}.csv").exists())

    def test_second_run_does_not_duplicate_transactions(self) -> None:
        self.assertEqual(self.run_pipeline_quietly(self.options), 0)
        connection = self.connect()
        self.addCleanup(connection.close)
        first_count = connection.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]
        first_total = connection.execute("SELECT SUM(amount_cents) FROM transactions").fetchone()[0]

        code = self.run_pipeline_quietly(dataclasses.replace(self.options, full_refresh=False))
        self.assertEqual(code, 0)

        self.assertEqual(
            connection.execute("SELECT COUNT(*) FROM transactions").fetchone()[0], first_count
        )
        self.assertEqual(
            connection.execute("SELECT SUM(amount_cents) FROM transactions").fetchone()[0],
            first_total,
        )
        run = self.last_run(connection)
        self.assertEqual(run["rows_inserted"], 0)
        self.assertEqual(run["rows_updated"], 0)
        self.assertEqual(run["rows_unchanged"], run["rows_accepted"])

    def test_full_refresh_rebuilds_the_warehouse(self) -> None:
        self.assertEqual(self.run_pipeline_quietly(self.options), 0)
        connection = self.connect()
        self.addCleanup(connection.close)
        count = connection.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]
        connection.close()

        self.assertEqual(self.run_pipeline_quietly(self.options), 0)
        connection = self.connect()
        self.addCleanup(connection.close)
        self.assertEqual(
            connection.execute("SELECT COUNT(*) FROM transactions").fetchone()[0], count
        )
        self.assertEqual(
            connection.execute("SELECT COUNT(*) FROM pipeline_runs").fetchone()[0], 1
        )

    def test_single_file_mode_derives_students_and_skips_budgets(self) -> None:
        options = dataclasses.replace(
            self.options, profiles_csv=None, budgets_csv=None
        )
        self.assertEqual(self.run_pipeline_quietly(options), 0)

        connection = self.connect()
        self.addCleanup(connection.close)
        self.assertEqual(
            connection.execute("SELECT COUNT(*) FROM budgets").fetchone()[0], 0
        )
        self.assertGreater(
            connection.execute("SELECT COUNT(*) FROM students").fetchone()[0], 0
        )
        years = {
            row[0] for row in connection.execute("SELECT DISTINCT study_year FROM students")
        }
        self.assertEqual(years, {0})
        self.assertGreater(
            self.last_run(connection)["rows_accepted"], 0
        )
        self.assertEqual(
            connection.execute("SELECT COUNT(*) FROM data_quality_results").fetchone()[0],
            11,
        )

        report_text = (
            self.options.reports_dir / "spending_report.html"
        ).read_text(encoding="utf-8")
        self.assertIn("No budget plan was provided", report_text)

    def test_missing_input_file_fails_the_run_record(self) -> None:
        broken = dataclasses.replace(
            self.options, transactions_csv=self.root / "missing.csv"
        )
        self.assertEqual(self.run_pipeline_quietly(broken), 2)
        connection = self.connect()
        self.addCleanup(connection.close)
        run = self.last_run(connection)
        self.assertEqual(run["status"], "failed")
        self.assertIn("not found", run["message"] or "")


if __name__ == "__main__":
    unittest.main()
