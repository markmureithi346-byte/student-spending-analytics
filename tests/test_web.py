from __future__ import annotations

import contextlib
import csv
import io
import re
import sqlite3
import tempfile
import threading
import unittest
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from unittest import mock

from student_spending import cli, config, database, web

REPORT_SENTINEL = "<!DOCTYPE html><html><body>REPORT SENTINEL</body></html>"
LOADED_AT = "2026-09-30T12:00:00+00:00"


def _seed(db_path: Path) -> None:
    connection = database.connect(db_path)
    database.initialize_database(connection)
    connection.executemany(
        "INSERT INTO students (student_id, profile_label, campus, study_year, "
        "monthly_income_cents) VALUES (?, ?, ?, ?, ?)",
        [
            ("STU-001", "Profile A", "Main Campus", 1, 5000000),
            ("STU-002", "Profile B", "Main Campus", 2, 4500000),
        ],
    )
    connection.executemany(
        "INSERT INTO categories (category, is_discretionary) VALUES (?, ?)",
        [(name, int(flag)) for name, flag in config.CATEGORY_DISCRETIONARY.items()],
    )

    rows: list[tuple] = [
        ("T-CAFE-1", "STU-001", "2026-07-02", 10000, "Food", "Lunch bowl",
         "M-Pesa", "Campus Cafeteria", 0, 0, None),
        ("T-MATATU", "STU-002", "2026-07-15", 5000, "Transport", "Ride to campus",
         "Cash", "Quick Matatu", 0, 0, None),
        ("T-CAFE-2", "STU-001", "2026-08-03", 20000, "Food", "Dinner bowl",
         "M-Pesa", "Campus Cafeteria", 0, 0, None),
        ("T-CINEMA", "STU-002", "2026-08-20", 30000, "Entertainment", "Movie night",
         "Card", "Star Cinema", 0, 1,
         "3.2x the student's average Entertainment spend"),
        ("T-RENT", "STU-001", "2026-09-05", 90000, "Rent", "=SUM(A1:A2)",
         "Bank Transfer", "Landlord", 0, 0, None),
        ("T-XSS", "STU-002", "2026-09-10", 7500, "Education", "Injected merchant",
         "M-Pesa", "<script>alert('x')</script>", 0, 0, None),
    ]
    for index in range(25):
        rows.append(
            (f"T-FOOD-{index:02d}", "STU-002", f"2026-07-{index + 1:02d}", 1000,
             "Food", "Filler lunch", "Cash", "Filler Cafe", 0, 0, None)
        )

    connection.executemany(
        "INSERT INTO transactions (transaction_id, student_id, transaction_date, "
        "amount_cents, category, description, payment_method, merchant, is_recurring, "
        "is_anomaly, record_hash, anomaly_reason, first_loaded_at, last_updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            (row[0], row[1], row[2], row[3], row[4], row[5], row[6], row[7],
             row[8], row[9], f"hash-{row[0]}", row[10], LOADED_AT, LOADED_AT)
            for row in rows
        ],
    )
    connection.execute(
        "INSERT INTO pipeline_runs (run_id, started_at, finished_at, status, input_file) "
        "VALUES (?, ?, ?, 'success', ?)",
        ("TEST-RUN", LOADED_AT, LOADED_AT, "student_expenses.csv"),
    )
    connection.commit()
    connection.close()


class DashboardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory()
        cls.root = Path(cls._tmp.name)
        cls.db_path = cls.root / "fixture.db"
        _seed(cls.db_path)
        cls.report_path = cls.root / "spending_report.html"
        cls.report_path.write_text(REPORT_SENTINEL, encoding="utf-8")
        cls.server = web.create_server(
            cls.db_path, port=0, report_path=cls.report_path
        )
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f"http://127.0.0.1:{cls.server.server_address[1]}"

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=5)
        cls._tmp.cleanup()

    def fetch(self, path: str, *, method: str = "GET") -> tuple[int, dict, str]:
        request = urllib.request.Request(self.base + path, method=method)
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                return (
                    response.status,
                    dict(response.headers.items()),
                    response.read().decode("utf-8"),
                )
        except urllib.error.HTTPError as error:
            return error.code, dict(error.headers.items()), error.read().decode("utf-8")

    @staticmethod
    def page_url(**params: str) -> str:
        return "/?" + urllib.parse.urlencode(params)

    def sql_aggregate(
        self, where: str = "1 = 1", params: tuple = ()
    ) -> tuple[int, float]:
        connection = sqlite3.connect(self.db_path)
        try:
            count, cents = connection.execute(
                f"SELECT COUNT(*), COALESCE(SUM(amount_cents), 0) "
                f"FROM transactions WHERE {where}",
                params,
            ).fetchone()
        finally:
            connection.close()
        return int(count), cents / 100.0

    @staticmethod
    def row_count(page: str) -> int:
        return page.count('data-label="Date"')

    @staticmethod
    def first_result_row(page: str) -> str:
        body = re.search(r"<tbody>(.*?)</tbody>", page, re.S)
        assert body is not None
        return body.group(1).split("</tr>")[0]

    def test_dashboard_matches_sql_and_offers_controls(self) -> None:
        status, headers, page = self.fetch("/")
        self.assertEqual(status, 200)
        self.assertEqual(headers["Content-Type"], "text/html; charset=utf-8")
        self.assertIn("Synthetic data.", page)
        self.assertIn("Spending <span>Explorer</span>", page)
        for control in ("from", "to", "student", "category", "payment", "flag",
                        "sort", "per_page", "q"):
            self.assertIn(f'name="{control}"', page)
        for header in ("Date", "Student", "Category", "Merchant and description",
                       "Payment", "Amount KES", "Review"):
            self.assertIn(f">{header}</th>", page)

        count, total = self.sql_aggregate()
        self.assertEqual(count, 31)
        self.assertIn(f"KES {total:,.2f}", page)
        self.assertIn("Showing 1–25 of", page)
        self.assertIn("31 matching transactions", page)
        self.assertEqual(self.row_count(page), 25)
        self.assertIn('href="/report"', page)

    def test_category_filter_changes_every_number(self) -> None:
        count, total = self.sql_aggregate("category = ?", ("Food",))
        status, _, page = self.fetch(self.page_url(category="Food", per_page="100"))
        self.assertEqual(status, 200)
        self.assertEqual(count, 27)
        self.assertEqual(self.row_count(page), 27)
        self.assertIn(f"KES {total:,.2f}", page)
        self.assertIn("27 transactions from 2 students", page)
        self.assertIn("Campus Cafeteria", page)
        self.assertNotIn("Star Cinema", page)

    def test_date_range_filter(self) -> None:
        count, total = self.sql_aggregate(
            "transaction_date BETWEEN ? AND ?", ("2026-08-01", "2026-08-31")
        )
        _, _, page = self.fetch(
            self.page_url(**{"from": "2026-08-01", "to": "2026-08-31"})
        )
        self.assertEqual(count, 2)
        self.assertEqual(self.row_count(page), 2)
        self.assertIn(f"KES {total:,.2f}", page)
        self.assertIn("Campus Cafeteria", page)
        self.assertIn("Star Cinema", page)
        self.assertNotIn("Quick Matatu", page)

    def test_filters_compose(self) -> None:
        count, total = self.sql_aggregate(
            "category = ? AND transaction_date BETWEEN ? AND ?",
            ("Food", "2026-08-01", "2026-08-31"),
        )
        _, _, page = self.fetch(
            self.page_url(category="Food", **{"from": "2026-08-01",
                                              "to": "2026-08-31"})
        )
        self.assertEqual(count, 1)
        self.assertEqual(self.row_count(page), 1)
        self.assertIn(f"KES {total:,.2f}", page)
        self.assertIn("Dinner bowl", page)
        self.assertNotIn("Movie night", page)

    def test_search_is_literal_and_case_insensitive(self) -> None:
        _, _, page = self.fetch(self.page_url(q="cafeteria"))
        self.assertEqual(self.row_count(page), 2)
        self.assertIn("KES 300.00", page)

        _, _, page = self.fetch(self.page_url(q="Lunch bowl"))
        self.assertEqual(self.row_count(page), 1)

        for wildcard in ("%", "_"):
            status, _, page = self.fetch(self.page_url(q=wildcard))
            self.assertEqual(status, 200)
            self.assertEqual(self.row_count(page), 0)
            self.assertIn("Nothing matches yet", page)

        injection = "' OR 1=1 --"
        status, _, page = self.fetch(self.page_url(q=injection))
        self.assertEqual(status, 200)
        self.assertEqual(self.row_count(page), 0)
        self.assertIn("Nothing matches yet", page)

        _, _, page = self.fetch("/")
        self.assertEqual(self.row_count(page), 25)

    def test_flagged_only_filter(self) -> None:
        _, _, page = self.fetch(self.page_url(flag="anomalies"))
        self.assertEqual(self.row_count(page), 1)
        self.assertIn("Star Cinema", page)
        self.assertIn("1 transaction is flagged for review.", page)
        self.assertNotIn("Landlord", page)

    def test_sort_order_uses_a_whitelist(self) -> None:
        _, _, largest = self.fetch(self.page_url(sort="largest"))
        self.assertIn("Landlord", self.first_result_row(largest))
        _, _, smallest = self.fetch(self.page_url(sort="smallest"))
        self.assertIn("Filler Cafe", self.first_result_row(smallest))
        self.assertIn("10.00", self.first_result_row(smallest))

        status, _, page = self.fetch(
            self.page_url(sort="amount_cents DESC; DROP TABLE transactions")
        )
        self.assertEqual(status, 200)
        self.assertIn("That sort order is not available.", page)
        self.assertEqual(self.row_count(page), 25)
        self.assertEqual(self.sql_aggregate()[0], 31)

    def test_pagination_and_page_clamping(self) -> None:
        _, _, page = self.fetch(self.page_url(page="2"))
        self.assertEqual(self.row_count(page), 6)
        self.assertIn("Showing 26–31 of", page)
        self.assertIn("Page 2 of 2", page)

        _, _, page = self.fetch(self.page_url(page="99"))
        self.assertEqual(self.row_count(page), 6)
        self.assertIn("Page 2 of 2", page)

        _, _, page = self.fetch(self.page_url(per_page="50"))
        self.assertEqual(self.row_count(page), 31)
        self.assertNotIn('class="pager"', page)

        _, _, page = self.fetch(self.page_url(per_page="7"))
        self.assertIn("Rows per page must be 25, 50 or 100.", page)
        self.assertEqual(self.row_count(page), 25)

    def test_invalid_filters_are_reported_and_safely_reset(self) -> None:
        status, _, page = self.fetch(
            self.page_url(
                **{
                    "from": "not-a-date",
                    "category": "Groceries",
                    "payment": "Crypto",
                    "flag": "maybe",
                    "sort": "amount_cents DESC",
                    "per_page": "7",
                    "page": "x",
                    "q": "x" * 120,
                }
            )
        )
        self.assertEqual(status, 200)
        for message in (
            "must be a real date",
            "not in the warehouse",
            "review filter must be",
            "That sort order is not available.",
            "Rows per page must be 25, 50 or 100.",
            "whole number of 1 or more",
            "shortened to 80 characters",
        ):
            self.assertIn(message, page)

        _, _, page = self.fetch(
            self.page_url(**{"from": "2026-09-01", "to": "2026-07-01"})
        )
        self.assertIn("must not be after the end date", page)
        self.assertIn("KES 1,875.00", page)

    def test_database_text_is_html_escaped(self) -> None:
        _, _, page = self.fetch(self.page_url(q="script"))
        self.assertIn("&lt;script&gt;alert", page)
        self.assertNotIn("<script>alert", page)

    def test_csv_export_matches_filters(self) -> None:
        status, headers, body = self.fetch("/export.csv?category=Food&sort=largest")
        self.assertEqual(status, 200)
        self.assertTrue(headers["Content-Type"].startswith("text/csv"))
        self.assertIn("attachment", headers["Content-Disposition"])
        self.assertIn("student-spending-", headers["Content-Disposition"])

        reader = csv.DictReader(io.StringIO(body))
        rows = list(reader)
        self.assertEqual(len(rows), 27)
        self.assertEqual(sum(float(row["amount_kes"]) for row in rows), 550.0)
        self.assertEqual(rows[0]["amount_kes"], "200.00")
        self.assertEqual({row["category"] for row in rows}, {"Food"})

    def test_csv_export_guards_formula_text(self) -> None:
        _, _, body = self.fetch("/export.csv?category=Rent")
        rows = list(csv.DictReader(io.StringIO(body)))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["transaction_id"], "T-RENT")
        self.assertEqual(rows[0]["description"], "'=SUM(A1:A2)")

    def test_csv_export_rejects_invalid_filters(self) -> None:
        status, _, body = self.fetch("/export.csv?from=broken")
        self.assertEqual(status, 400)
        self.assertIn("Filters need attention", body)

        status, _, body = self.fetch("/export.csv?category=Groceries")
        self.assertEqual(status, 400)

    def test_report_route_and_missing_report(self) -> None:
        status, headers, body = self.fetch("/report")
        self.assertEqual(status, 200)
        self.assertIn("REPORT SENTINEL", body)
        self.assertTrue(headers["Content-Type"].startswith("text/html"))

        self.report_path.unlink()
        try:
            status, _, body = self.fetch("/report")
            self.assertEqual(status, 404)
            self.assertIn("No report yet", body)
            _, _, page = self.fetch("/")
            self.assertNotIn('href="/report"', page)
        finally:
            self.report_path.write_text(REPORT_SENTINEL, encoding="utf-8")

    def test_unknown_path_head_and_method_restrictions(self) -> None:
        status, _, page = self.fetch("/missing-page")
        self.assertEqual(status, 404)
        self.assertIn("Page not found", page)

        status, headers, body = self.fetch("/", method="HEAD")
        self.assertEqual(status, 200)
        self.assertEqual(body, "")
        self.assertGreater(int(headers["Content-Length"]), 0)

        status, headers, body = self.fetch("/", method="POST")
        self.assertEqual(status, 405)
        self.assertEqual(headers["Allow"], "GET, HEAD")
        self.assertIn("Read-only dashboard", body)

        status, _, body = self.fetch("/favicon.ico")
        self.assertEqual(status, 204)
        self.assertEqual(body, "")

    def test_security_headers(self) -> None:
        _, headers, _ = self.fetch("/")
        self.assertIn("default-src 'none'", headers["Content-Security-Policy"])
        self.assertIn("form-action 'self'", headers["Content-Security-Policy"])
        self.assertEqual(headers["X-Content-Type-Options"], "nosniff")
        self.assertEqual(headers["Cache-Control"], "no-store")
        self.assertEqual(headers["Referrer-Policy"], "no-referrer")
        self.assertNotIn("Python", headers["Server"])

    def test_readonly_connection_rejects_writes(self) -> None:
        connection = web.connect_readonly(self.db_path)
        self.addCleanup(connection.close)
        with self.assertRaises(sqlite3.OperationalError):
            connection.execute("CREATE TABLE probe (id INTEGER)")

    def test_serve_refuses_missing_warehouse(self) -> None:
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = web.serve(self.root / "absent.db", port=0)
        self.assertEqual(code, 2)
        self.assertIn("not found", output.getvalue().lower())

    def test_cli_dispatches_serve_without_touching_the_pipeline(self) -> None:
        with mock.patch("student_spending.web.serve", return_value=7) as serve_mock:
            code = cli.main(["serve", "--port", "0"])
        self.assertEqual(code, 7)
        serve_mock.assert_called_once()
        _, kwargs = serve_mock.call_args
        self.assertEqual(kwargs["host"], "127.0.0.1")
        self.assertEqual(kwargs["port"], 0)
        self.assertFalse(kwargs["open_browser"])

    def test_pipeline_invocations_are_unchanged(self) -> None:
        parser = cli.build_parser()
        self.assertIsNone(parser.parse_args([]).command)
        self.assertIsNone(parser.parse_args(["--full-refresh"]).command)
        self.assertTrue(parser.parse_args(["--full-refresh"]).full_refresh)
        self.assertEqual(parser.parse_args(["serve"]).command, "serve")


if __name__ == "__main__":
    unittest.main()
