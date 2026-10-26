from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from student_spending import analytics, database, load
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


def transaction(
    transaction_id: str,
    when: str,
    amount_cents: int,
    category: str = "Food",
) -> CleanTransaction:
    return CleanTransaction(
        transaction_id=transaction_id,
        student_id="STU-001",
        transaction_date=when,
        amount_cents=amount_cents,
        category=category,
        description="Test row",
        payment_method="M-Pesa",
        merchant="Cafeteria",
        is_recurring=False,
        source_line=2,
    )


class AnalyticsTests(unittest.TestCase):
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
                    "budget_cents": 1_500_000,
                }
            ],
        )
        load.load_transactions(
            self.connection,
            [
                transaction("TXN-0001", "2026-08-03", 100_000),
                transaction("TXN-0002", "2026-08-10", 100_000),
                transaction("TXN-0003", "2026-08-17", 100_000),
                transaction("TXN-0004", "2026-08-20", 2_000_000),
                transaction("TXN-0005", "2026-08-04", 50_000, category="Transport"),
            ],
            NOW,
        )

    def test_monthly_totals_are_exact(self) -> None:
        months = analytics.monthly_totals(self.connection)
        self.assertEqual(len(months), 1)
        self.assertEqual(months[0]["transaction_month"], "2026-08")
        self.assertEqual(months[0]["transaction_count"], 5)
        self.assertAlmostEqual(months[0]["total_kes"], 23_500.00, places=2)

    def test_category_totals_and_share(self) -> None:
        categories = {row["category"]: row for row in analytics.category_totals(self.connection)}
        self.assertEqual(categories["Food"]["transaction_count"], 4)
        self.assertAlmostEqual(categories["Food"]["total_kes"], 23_000.00, places=2)
        self.assertAlmostEqual(categories["Food"]["share_pct"], 97.87, places=2)
        shares = sum(row["share_pct"] for row in categories.values())
        self.assertAlmostEqual(shares, 100.0, places=1)

    def test_weekday_mapping_uses_transaction_date(self) -> None:
        weekdays = {row["weekday_name"]: row for row in analytics.weekday_spending(self.connection)}
        self.assertAlmostEqual(weekdays["Monday"]["total_kes"], 3_000.00, places=2)
        self.assertAlmostEqual(weekdays["Thursday"]["total_kes"], 20_000.00, places=2)
        self.assertAlmostEqual(weekdays["Tuesday"]["total_kes"], 500.00, places=2)

    def test_budget_variance_matches_actual_spend(self) -> None:
        overruns = analytics.budget_overruns(self.connection)
        self.assertEqual(len(overruns), 1)
        self.assertEqual(overruns[0]["category"], "Food")
        self.assertAlmostEqual(overruns[0]["actual_kes"], 23_000.00, places=2)
        self.assertAlmostEqual(overruns[0]["variance_kes"], 8_000.00, places=2)

    def test_anomaly_flagging_marks_the_outlier(self) -> None:
        flagged = analytics.flag_anomalies(self.connection)
        self.assertEqual(flagged, 1)
        rows = analytics.flagged_transactions(self.connection)
        self.assertEqual([row["transaction_id"] for row in rows], ["TXN-0004"])
        self.assertIn("x the student's average", rows[0]["anomaly_reason"])

    def test_anomaly_flags_are_recomputed_not_accumulated(self) -> None:
        analytics.flag_anomalies(self.connection)
        analytics.flag_anomalies(self.connection)
        total = self.connection.execute(
            "SELECT COUNT(*) FROM transactions WHERE is_anomaly = 1"
        ).fetchone()[0]
        self.assertEqual(total, 1)

    def test_kpis_are_derived_from_the_fact_table(self) -> None:
        kpis = analytics.kpis(self.connection)
        self.assertEqual(kpis["transaction_count"], 5)
        self.assertEqual(kpis["student_count"], 1)
        self.assertAlmostEqual(kpis["total_kes"], 23_500.00, places=2)
        self.assertEqual(kpis["days_covered"], 18)
        self.assertAlmostEqual(kpis["avg_daily_kes"], 1_305.56, places=2)

    def test_week_over_week_view_is_available(self) -> None:
        rows = analytics.weekly_change(self.connection)
        self.assertGreaterEqual(len(rows), 2)
        self.assertIsNone(rows[0]["change_pct"] or None)


if __name__ == "__main__":
    unittest.main()
