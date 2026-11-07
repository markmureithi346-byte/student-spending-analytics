from __future__ import annotations

import contextlib
import csv
import http.client
import io
import json
import re
import socket
import sqlite3
import tempfile
import threading
import unittest
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from datetime import datetime, timezone
from unittest import mock

from student_spending import cli, config, database, personal, platform, web

REPORT_SENTINEL = "<!DOCTYPE html><html><body>REPORT SENTINEL</body></html>"
LOADED_AT = "2026-09-30T12:00:00+00:00"

CLEAN_TRANSACTIONS = """transaction_id,student_id,transaction_date,amount_kes,category,description,payment_method,merchant,is_recurring
TXN-1001,STU-001,2026-07-01,300.00,Food,Tea,Cash,Campus Cafe,false
TXN-1002,STU-001,2026-07-02,300.00,Food,Lunch,Cash,Campus Cafe,false
TXN-1003,STU-001,2026-07-03,300.00,Food,Snack,Cash,Campus Cafe,false
TXN-1004,STU-001,2026-07-04,400.00,Education,Book,Card,Bookshop,false
"""

SECOND_TRANSACTIONS = """transaction_id,student_id,transaction_date,amount_kes,category,description,payment_method,merchant,is_recurring
TXN-3001,STU-002,2026-08-01,500.00,Food,Breakfast,Card,Mama Oliech Kitchen,false
TXN-3002,STU-002,2026-08-02,700.00,Education,Notes,Card,Bookshop,false
"""

QUALITY_TRANSACTIONS = """transaction_id,student_id,transaction_date,amount_kes,category,description,payment_method,merchant,is_recurring
TXN-2001,STU-001,2026-07-01,300.00,Education,Notes,Cash,Bookshop,false
TXN-2002,STU-001,2026-07-02,300.00,Education,Notes,Cash,Bookshop,false
TXN-2003,STU-001,2026-07-03,300.00,Education,Notes,Cash,Bookshop,false
TXN-2004,STU-001,2026-07-04,5000.00,Education,Laptop,Cash,Bookshop,false
"""

NO_VALID_TRANSACTIONS = """transaction_id,student_id,transaction_date,amount_kes,category,description,payment_method,merchant,is_recurring
TXN-9001,STU-999,2026-07-01,300.00,Groceries,Tea,Cash,Campus Cafe,false
"""


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


def signup_cookie(
    base: str,
    *,
    email: str = "student@example.test",
    name: str = "Test Student",
    password: str = "synthetic1",
) -> str:
    """Create an account over HTTP and return its session Cookie header."""
    parsed = urllib.parse.urlsplit(base)
    connection = http.client.HTTPConnection(parsed.hostname, parsed.port, timeout=60)
    try:
        body = urllib.parse.urlencode(
            {
                "display_name": name,
                "email": email,
                "password": password,
                "confirm": password,
                "privacy_ack": "yes",
            }
        ).encode("utf-8")
        connection.request(
            "POST",
            "/signup",
            body=body,
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Origin": base,
            },
        )
        response = connection.getresponse()
        response.read()
        if response.status != 303:
            raise AssertionError(f"sign-up failed: {response.status}")
        header = response.getheader("Set-Cookie") or ""
        return header.split(";", 1)[0]
    finally:
        connection.close()


def csrf_for(base: str, cookie: str) -> str:
    """Read the CSRF token bound to a signed-in test session."""
    parsed = urllib.parse.urlsplit(base)
    connection = http.client.HTTPConnection(parsed.hostname, parsed.port, timeout=30)
    try:
        connection.request("GET", "/account", headers={"Cookie": cookie})
        response = connection.getresponse()
        page = response.read().decode("utf-8", "replace")
        if response.status != 200:
            return ""
        match = re.search(r'name="csrf" value="([^"]+)"', page)
        return match.group(1) if match else ""
    finally:
        connection.close()


class HealthCheckTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.db_path = self.root / "fixture.db"
        _seed(self.db_path)
        self.report_path = self.root / "spending_report.html"
        self.report_path.write_text(REPORT_SENTINEL, encoding="utf-8")
        self.server = web.create_server(
            self.db_path,
            port=0,
            report_path=self.report_path,
            accounts_path=self.root / "accounts.db",
        )
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        self._tmp.cleanup()

    def fetch_health(self) -> tuple[int, dict]:
        try:
            with urllib.request.urlopen(self.base + "/healthz", timeout=10) as response:
                return response.status, json.loads(response.read())
        except urllib.error.HTTPError as error:
            return error.code, json.loads(error.read())

    def test_missing_warehouse_degrades_without_crashing(self) -> None:
        self.db_path.unlink()
        status, payload = self.fetch_health()
        self.assertEqual(status, 503)
        self.assertEqual(payload["status"], "degraded")
        self.assertFalse(payload["checks"]["warehouse"])


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
            cls.db_path,
            port=0,
            report_path=cls.report_path,
            accounts_path=cls.root / "accounts.db",
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

    def test_health_check_reports_database_state(self) -> None:
        status, headers, body = self.fetch("/healthz")
        self.assertEqual(status, 200)
        self.assertEqual(headers["Content-Type"], "application/json; charset=utf-8")
        payload = json.loads(body)
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["checks"], {"warehouse": True, "accounts": True})
        self.assertTrue(payload["version"])

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

    def test_category_shares_add_up_to_one_hundred(self) -> None:
        _, _, page = self.fetch(self.page_url(per_page="100"))
        region = page[page.index('id="breakdown"'):]
        shares = [
            float(value)
            for value in re.findall(r'<span class="share-value">([\d.]+)%</span>', region)
        ]
        self.assertGreater(len(shares), 1)
        self.assertEqual(round(sum(shares), 1), 100.0)

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
        self.assertEqual(headers["Referrer-Policy"], "same-origin")
        self.assertEqual(headers["X-Frame-Options"], "DENY")
        self.assertEqual(headers["Cross-Origin-Opener-Policy"], "same-origin")
        self.assertEqual(headers["Cross-Origin-Resource-Policy"], "same-origin")
        self.assertIn("camera=()", headers["Permissions-Policy"])
        self.assertIn("payment=()", headers["Permissions-Policy"])
        self.assertNotIn("Strict-Transport-Security", headers)
        self.assertNotIn("Python", headers["Server"])

    def test_secure_cookies_are_opt_in(self) -> None:
        _, plain = web._session_cookie("token")
        self.assertIn("HttpOnly", plain)
        self.assertIn("SameSite=Strict", plain)
        self.assertNotIn("Secure", plain)
        _, secure = web._session_cookie("token", secure=True)
        self.assertIn("Secure", secure)
        _, cleared = web._cleared_cookie(secure=True)
        self.assertIn("Max-Age=0", cleared)
        self.assertIn("Secure", cleared)

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
        self.assertIsNone(kwargs["secure_cookies"])

    def test_cli_prune_uploads_is_a_dry_run_by_default(self) -> None:
        output = io.StringIO()
        with mock.patch(
            "student_spending.platform.prune_analyses",
            return_value=["20260101T000000Z-abcdef"],
        ) as prune_mock:
            with contextlib.redirect_stdout(output):
                code = cli.main(["prune-uploads", "--days", "14"])
        self.assertEqual(code, 0)
        prune_mock.assert_called_once_with(14, dry_run=True)
        self.assertIn("Would delete 1 uploaded analysis", output.getvalue())
        self.assertIn("Rerun with --apply", output.getvalue())

        with mock.patch(
            "student_spending.platform.prune_analyses", return_value=[]
        ) as prune_mock:
            with contextlib.redirect_stdout(io.StringIO()):
                code = cli.main(["prune-uploads", "--days", "1", "--apply"])
        self.assertEqual(code, 0)
        prune_mock.assert_called_once_with(1, dry_run=False)

        with mock.patch(
            "student_spending.platform.prune_analyses",
            side_effect=ValueError("older_than_days must be at least 1"),
        ):
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                code = cli.main(["prune-uploads", "--days", "0"])
        self.assertEqual(code, 2)
        self.assertIn("at least 1", output.getvalue())

    def test_pipeline_invocations_are_unchanged(self) -> None:
        parser = cli.build_parser()
        self.assertIsNone(parser.parse_args([]).command)
        self.assertIsNone(parser.parse_args(["--full-refresh"]).command)
        self.assertTrue(parser.parse_args(["--full-refresh"]).full_refresh)
        self.assertEqual(parser.parse_args(["serve"]).command, "serve")


class UploadPlatformTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory()
        cls.root = Path(cls._tmp.name)
        cls.db_path = cls.root / "fixture.db"
        _seed(cls.db_path)
        cls.report_path = cls.root / "baseline_report.html"
        cls.report_path.write_text(REPORT_SENTINEL, encoding="utf-8")
        cls._config_patch = mock.patch.multiple(
            config,
            UPLOAD_DATA_DIR=cls.root / "uploads" / "data",
            UPLOAD_WAREHOUSE_DIR=cls.root / "uploads" / "warehouse",
            UPLOAD_REPORT_DIR=cls.root / "uploads" / "reports",
        )
        cls._config_patch.start()
        cls.server = web.create_server(
            cls.db_path,
            port=0,
            report_path=cls.report_path,
            accounts_path=cls.root / "accounts.db",
        )
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.port = cls.server.server_address[1]
        cls.base = f"http://127.0.0.1:{cls.port}"
        cls.cookie = signup_cookie(cls.base)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=5)
        cls._config_patch.stop()
        cls._tmp.cleanup()

    def fetch(
        self, path: str, *, method: str = "GET", cookie: str | None = None
    ) -> tuple[int, dict, str]:
        request = urllib.request.Request(
            self.base + path,
            method=method,
            headers={"Cookie": cookie or self.cookie},
        )
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                return (
                    response.status,
                    dict(response.headers.items()),
                    response.read().decode("utf-8"),
                )
        except urllib.error.HTTPError as error:
            return error.code, dict(error.headers.items()), error.read().decode("utf-8")

    def post_raw(
        self,
        content_type: str,
        body: bytes,
        *,
        headers: dict[str, str] | None = None,
        path: str = "/upload",
    ) -> tuple[int, dict, str]:
        if content_type.startswith("application/x-www-form-urlencoded"):
            token = csrf_for(self.base, self.cookie)
            if token and b"csrf=" not in body:
                body += (b"&" if body else b"") + urllib.parse.urlencode(
                    {"csrf": token}
                ).encode("utf-8")
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=60)
        try:
            request_headers = {
                "Content-Type": content_type,
                "Cookie": self.cookie,
                "Origin": self.base,
            }
            request_headers.update(headers or ())
            connection.request("POST", path, body=body, headers=request_headers)
            response = connection.getresponse()
            payload = response.read()
            return (
                response.status,
                {name.lower(): value for name, value in response.getheaders()},
                payload.decode("utf-8", "replace"),
            )
        finally:
            connection.close()

    @staticmethod
    def csv_files(
        *,
        transactions: str = CLEAN_TRANSACTIONS,
    ) -> dict[str, tuple[str, bytes]]:
        return {
            "transactions": ("transactions.csv", transactions.encode("utf-8")),
        }

    def multipart(
        self,
        files: dict[str, tuple[str, bytes]],
        *,
        title: str | None = "",
        authorised: bool = True,
        extra: list[tuple[str, str]] | None = None,
        duplicate_title: bool = False,
    ) -> tuple[str, bytes]:
        boundary = "----studentSpendingTestBoundary"
        chunks: list[bytes] = []

        def add_text(name: str, value: str) -> None:
            chunks.append(
                f'--{boundary}\r\nContent-Disposition: form-data; '
                f'name="{name}"\r\n\r\n'.encode("utf-8")
                + value.encode("utf-8")
                + b"\r\n"
            )

        def add_file(name: str, filename: str, payload: bytes) -> None:
            chunks.append(
                f'--{boundary}\r\nContent-Disposition: form-data; '
                f'name="{name}"; filename="{filename}"\r\n'
                "Content-Type: text/csv\r\n\r\n".encode("utf-8")
                + payload
                + b"\r\n"
            )

        if title is not None:
            add_text("title", title)
            if duplicate_title:
                add_text("title", title + " again")
        token = csrf_for(self.base, self.cookie)
        if token:
            add_text("csrf", token)
        if authorised:
            add_text("authorised", "yes")
        for name, value in extra or []:
            add_text(name, value)
        for name, entry in files.items():
            add_file(name, entry[0], entry[1])
        chunks.append(f"--{boundary}--\r\n".encode("utf-8"))
        return f"multipart/form-data; boundary={boundary}", b"".join(chunks)

    def upload(
        self,
        files: dict[str, tuple[str, bytes]] | None = None,
        *,
        title: str | None = "",
        authorised: bool = True,
        extra: list[tuple[str, str]] | None = None,
        duplicate_title: bool = False,
        headers: dict[str, str] | None = None,
    ) -> tuple[int, dict, str]:
        content_type, body = self.multipart(
            files if files is not None else self.csv_files(),
            title=title,
            authorised=authorised,
            extra=extra,
            duplicate_title=duplicate_title,
        )
        return self.post_raw(content_type, body, headers=headers)

    def upload_ok(
        self,
        files: dict[str, tuple[str, bytes]] | None = None,
        *,
        title: str = "Test analysis",
    ) -> str:
        status, headers, page = self.upload(files, title=title)
        self.assertEqual(status, 303, page[:300])
        location = headers.get("location", "")
        match = re.fullmatch(
            r"/\?analysis=([0-9]{8}T[0-9]{6}Z-[0-9a-f]{6})", location
        )
        self.assertIsNotNone(match, location)
        return match.group(1)

    @staticmethod
    def first_result_row(page: str) -> str:
        body = re.search(r"<tbody>(.*?)</tbody>", page, re.S)
        assert body is not None
        return body.group(1).split("</tr>")[0]

    def analysis_dirs(self) -> set[str]:
        root = Path(config.UPLOAD_DATA_DIR)
        if not root.is_dir():
            return set()
        return {entry.name for entry in root.iterdir() if entry.is_dir()}

    def baseline_state(self) -> tuple[int, str]:
        connection = sqlite3.connect(self.db_path)
        try:
            count = connection.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]
            run = connection.execute(
                "SELECT run_id FROM pipeline_runs ORDER BY rowid DESC LIMIT 1"
            ).fetchone()
        finally:
            connection.close()
        return int(count), str(run[0]) if run else ""

    def test_upload_page_and_home_link(self) -> None:
        status, _, page = self.fetch("/upload")
        self.assertEqual(status, 200)
        for control in ("title", "transactions", "authorised"):
            self.assertIn(f'name="{control}"', page)
        self.assertNotIn('name="profiles"', page)
        self.assertNotIn('name="budgets"', page)
        self.assertIn('enctype="multipart/form-data"', page)
        self.assertIn('action="/upload"', page)
        self.assertIn('href="/samples/student_expenses.csv"', page)
        self.assertNotIn("/samples/student_profiles.csv", page)
        self.assertNotIn("/samples/student_budgets.csv", page)
        self.assertIn("2 MB", page)
        self.assertIn("No profiles or budgets file is required.", page)
        self.assertIn("Only data you may process.", page)

        _, _, home = self.fetch("/")
        self.assertIn('href="/upload"', home)
        self.assertIn("Analyze new data", home)

    def test_sample_routes_serve_only_known_files(self) -> None:
        status, headers, body = self.fetch("/samples/student_expenses.csv")
        self.assertEqual(status, 200)
        self.assertTrue(headers["Content-Type"].startswith("text/csv"))
        self.assertIn("attachment", headers["Content-Disposition"])
        self.assertTrue(body.startswith("transaction_id,student_id,"))

        status, _, body = self.fetch("/samples/student_profiles.csv")
        self.assertEqual(status, 404)
        self.assertIn("Sample not found", body)

        status, _, body = self.fetch("/samples/unknown.csv")
        self.assertEqual(status, 404)
        self.assertIn("Sample not found", body)

        status, _, body = self.fetch("/samples/%2e%2e%2fstudent_expenses.csv")
        self.assertEqual(status, 404)
        self.assertIn("Sample not found", body)

    def test_successful_upload_builds_isolated_analysis(self) -> None:
        before = self.baseline_state()
        analysis_id = self.upload_ok(title="Clean July analysis")

        data_root = Path(config.UPLOAD_DATA_DIR) / analysis_id
        for name in ("transactions.csv", "metadata.json"):
            self.assertTrue((data_root / name).is_file(), name)
        self.assertFalse((data_root / "profiles.csv").exists())
        self.assertFalse((data_root / "budgets.csv").exists())
        db_path = Path(config.UPLOAD_WAREHOUSE_DIR) / f"{analysis_id}.db"
        report_path = (
            Path(config.UPLOAD_REPORT_DIR) / analysis_id / "spending_report.html"
        )
        self.assertTrue(db_path.is_file())
        self.assertTrue(report_path.is_file())

        metadata = json.loads((data_root / "metadata.json").read_text(encoding="utf-8"))
        self.assertEqual(metadata["status"], "success")
        self.assertEqual(metadata["rows_accepted"], 4)
        self.assertEqual(metadata["title"], "Clean July analysis")
        self.assertEqual(set(metadata["inputs"]), {"transactions"})
        self.assertEqual(metadata["inputs"]["transactions"]["rows"], 4)

        status, _, page = self.fetch(f"/?analysis={analysis_id}")
        self.assertEqual(status, 200)
        self.assertIn("Clean July analysis", page)
        self.assertIn("4 matching transactions", page)
        self.assertIn("KES 1,300.00", page)
        self.assertIn(f'name="analysis" value="{analysis_id}"', page)
        self.assertIn(f'href="/report?analysis={analysis_id}"', page)
        self.assertIn(f"analysis={analysis_id}", page)
        self.assertIn("/export.csv?", page)
        self.assertIn("Analyze new data", page)

        status, _, report_body = self.fetch(f"/report?analysis={analysis_id}")
        self.assertEqual(status, 200)
        self.assertIn("Student Spending Analytics Report", report_body)
        self.assertIn("No budget plan was provided", report_body)
        self.assertNotIn("REPORT SENTINEL", report_body)

        status, _, csv_body = self.fetch(f"/export.csv?analysis={analysis_id}")
        self.assertEqual(status, 200)
        rows = list(csv.DictReader(io.StringIO(csv_body)))
        self.assertEqual(len(rows), 4)
        self.assertEqual(sum(float(row["amount_kes"]) for row in rows), 1300.0)
        self.assertEqual({row["student_id"] for row in rows}, {"STU-001"})

        _, _, history = self.fetch("/upload")
        self.assertIn(analysis_id, history)
        self.assertIn("Clean July analysis", history)
        self.assertIn("Open analysis", history)
        self.assertIn("success", history)

        self.assertEqual(self.baseline_state(), before)
        self.assertEqual(self.baseline_state(), (31, "TEST-RUN"))

    def test_analysis_filter_links_keep_the_workspace(self) -> None:
        analysis_id = self.upload_ok(title="Filter check")
        status, _, page = self.fetch(
            f"/?analysis={analysis_id}&category=Education&per_page=100"
        )
        self.assertEqual(status, 200)
        self.assertIn("1 transaction from 1 student totals KES 400.00", page)
        self.assertEqual(page.count('data-label="Date"'), 1)
        self.assertIn(f'name="analysis" value="{analysis_id}"', page)
        self.assertIn(f'href="/?analysis={analysis_id}"', page)
        export_link = re.search(r'href="(/export\.csv\?[^"]+)"', page)
        self.assertIsNotNone(export_link)
        export_params = urllib.parse.parse_qs(
            urllib.parse.urlsplit(export_link.group(1).replace("&amp;", "&")).query
        )
        self.assertEqual(export_params["analysis"], [analysis_id])
        self.assertEqual(export_params["category"], ["Education"])

        status, _, csv_body = self.fetch(
            f"/export.csv?analysis={analysis_id}&category=Education"
        )
        self.assertEqual(status, 200)
        rows = list(csv.DictReader(io.StringIO(csv_body)))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["amount_kes"], "400.00")

        _, _, upload_page = self.fetch(f"/upload?analysis={analysis_id}")
        self.assertIn("Open current analysis", upload_page)

    def test_quality_failure_is_visible_but_usable(self) -> None:
        analysis_id = self.upload_ok(
            self.csv_files(transactions=QUALITY_TRANSACTIONS),
            title="Flagged education",
        )
        metadata_path = (
            Path(config.UPLOAD_DATA_DIR) / analysis_id / "metadata.json"
        )
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        self.assertEqual(metadata["status"], "quality_failed")
        self.assertEqual(metadata["quality_failures"], 1)

        status, _, page = self.fetch(f"/?analysis={analysis_id}")
        self.assertEqual(status, 200)
        self.assertIn("Quality alert.", page)
        self.assertIn("1 automated quality check failed", page)
        self.assertIn("4 matching transactions", page)
        self.assertIn("1 transaction is flagged for review.", page)
        self.assertIn(
            "Data quality checks",
            self.fetch(f"/report?analysis={analysis_id}")[2],
        )

        _, _, history = self.fetch("/upload")
        self.assertIn("quality alert", history)

    def test_validation_rejects_bad_forms(self) -> None:
        before = self.analysis_dirs()
        unexpected_profile = self.csv_files()
        unexpected_profile["profiles"] = ("profiles.csv", b"student_id\nSTU-001\n")
        bad_extension = self.csv_files()
        bad_extension["transactions"] = ("transactions.txt", b"a,b\n1,2\n")
        bad_header = self.csv_files(
            transactions=(
                "transaction_id,student_id,transaction_date,amount_kes,category,"
                "description,payment_method,is_recurring\n"
                "TXN-1,STU-001,2026-07-01,100.00,Food,Tea,Cash,false\n"
            )
        )
        header_only = self.csv_files(
            transactions=(
                "transaction_id,student_id,transaction_date,amount_kes,category,"
                "description,payment_method,merchant,is_recurring\n"
            )
        )
        binary = self.csv_files(
            transactions=CLEAN_TRANSACTIONS.encode("utf-8").replace(
                b"Campus Cafe", b"Campus\x00Cafe"
            ).decode("latin-1")
        )

        cases = [
            ("missing confirmation", dict(authorised=False), 400,
             "Confirm that you have the right to process this file"),
            ("duplicate title", dict(duplicate_title=True), 400,
             "appeared more than once"),
            ("unexpected text field", dict(extra=[("probe", "x")]), 400,
             "Unexpected field"),
            ("unexpected profile file", dict(files=unexpected_profile), 400,
             "Unexpected field"),
            ("missing transactions file", dict(files={}), 400,
             "Add the missing file"),
            ("wrong extension", dict(files=bad_extension), 400,
             "must be a .csv file"),
            ("missing column", dict(files=bad_header), 400,
             "missing required column"),
            ("header only", dict(files=header_only), 400,
             "header but no data rows"),
            ("binary payload", dict(files=binary), 400, "binary data"),
            ("long title", dict(title="x" * 81), 400,
             "80 characters or fewer"),
            ("too many fields",
             dict(extra=[(f"probe{index}", "x") for index in range(13)]), 413,
             "too many fields"),
        ]
        for name, arguments, expected_status, message in cases:
            with self.subTest(case=name):
                status, _, page = self.upload(**arguments)
                self.assertEqual(status, expected_status, page[:300])
                self.assertIn(message, page)

        self.assertEqual(self.analysis_dirs(), before)

    def test_request_guards(self) -> None:
        content_type, body = self.multipart(self.csv_files())

        status, _, page = self.post_raw(
            content_type, body, headers={"Origin": "http://evil.example"}
        )
        self.assertEqual(status, 403)
        self.assertIn("Uploads must come from this dashboard", page)

        status, _, page = self.post_raw(
            content_type, body, headers={"Sec-Fetch-Site": "cross-site"}
        )
        self.assertEqual(status, 403)

        status, _, _ = self.post_raw(
            content_type, body, headers={"Origin": "null"}
        )
        self.assertEqual(status, 403)

        status, _, page = self.post_raw("application/json", b"{}")
        self.assertEqual(status, 415)
        self.assertIn("multipart form", page)

        status, _, page = self.post_raw(content_type, b"")
        self.assertEqual(status, 400)
        self.assertIn("upload was empty", page)

        status, _, page = self.post_raw(
            content_type,
            b"",
            headers={"Content-Length": str(platform.MAX_REQUEST_BYTES + 1)},
        )
        self.assertEqual(status, 413)
        self.assertIn("larger than the allowed limit", page)

        with socket.create_connection(("127.0.0.1", self.port), timeout=10) as sock:
            sock.sendall(
                b"POST /upload HTTP/1.1\r\nHost: 127.0.0.1\r\n"
                + f"Cookie: {self.cookie}\r\n".encode()
                + b"Origin: http://127.0.0.1\r\n"
                + b"Content-Type: multipart/form-data; boundary=x\r\n"
                b"Connection: close\r\n\r\n"
            )
            raw = b""
            while True:
                chunk = sock.recv(65536)
                if not chunk:
                    break
                raw += chunk
        self.assertIn(b" 411 ", raw.split(b"\r\n", 1)[0])
        self.assertIn(b"Content-Length header", raw)

        status, headers, page = self.fetch("/missing-page", method="POST")
        self.assertEqual(status, 405)
        self.assertEqual(headers["Allow"], "GET, HEAD")
        self.assertIn("Read-only dashboard", page)

        status, _, _ = self.post_raw(
            content_type, body, headers={"Origin": self.base}
        )
        self.assertEqual(status, 303)

    def test_pipeline_failure_returns_422_and_cleans_up(self) -> None:
        before_dirs = self.analysis_dirs()
        before_state = self.baseline_state()
        status, _, page = self.upload(
            self.csv_files(transactions=NO_VALID_TRANSACTIONS),
            title="No clean rows",
        )
        self.assertEqual(status, 422, page[:300])
        self.assertIn("No clean transactions could be loaded", page)
        self.assertEqual(self.analysis_dirs(), before_dirs)
        self.assertEqual(self.baseline_state(), before_state)

    def test_analysis_ids_are_strictly_validated(self) -> None:
        for path in (
            "/?analysis=not-an-id",
            "/?analysis=../../etc/passwd",
            "/?analysis=20261026T102751Z-ABCDEF",
            "/report?analysis=../../etc/passwd",
            "/export.csv?analysis=../../etc/passwd",
        ):
            with self.subTest(path=path):
                status, _, body = self.fetch(path)
                self.assertEqual(status, 404)
                self.assertIn("Analysis not found", body)

        status, _, body = self.fetch("/upload?analysis=../../etc/passwd")
        self.assertEqual(status, 200)
        self.assertIn('action="/upload"', body)

    def test_two_uploads_stay_isolated(self) -> None:
        first = self.upload_ok(title="First dataset")
        second = self.upload_ok(
            self.csv_files(transactions=SECOND_TRANSACTIONS),
            title="Second dataset",
        )
        self.assertNotEqual(first, second)

        _, _, first_page = self.fetch(f"/?analysis={first}")
        self.assertIn("First dataset", first_page)
        self.assertNotIn("Second dataset", first_page)
        self.assertIn("4 matching transactions", first_page)
        self.assertIn("KES 1,300.00", first_page)

        _, _, second_page = self.fetch(f"/?analysis={second}")
        self.assertIn("Second dataset", second_page)
        self.assertNotIn("First dataset", second_page)
        self.assertIn("2 matching transactions", second_page)
        self.assertIn("KES 1,200.00", second_page)

        self.assertNotEqual(
            Path(config.UPLOAD_WAREHOUSE_DIR) / f"{first}.db",
            Path(config.UPLOAD_WAREHOUSE_DIR) / f"{second}.db",
        )
        self.assertEqual(self.baseline_state(), (31, "TEST-RUN"))

    def test_analyses_are_private_to_their_owner(self) -> None:
        analysis_id = self.upload_ok(title="Owned analysis")
        other = signup_cookie(
            self.base, email="other-owner@example.test", name="Other Owner"
        )

        status, _, page = self.fetch(f"/?analysis={analysis_id}", cookie=other)
        self.assertEqual(status, 404)
        self.assertIn("Analysis not found", page)

        status, _, page = self.fetch("/upload", cookie=other)
        self.assertEqual(status, 200)
        self.assertNotIn("Owned analysis", page)
        self.assertIn("No uploaded analyses yet", page)

        status, _, page = self.fetch(
            f"/delete-analysis?analysis={analysis_id}", cookie=other
        )
        self.assertEqual(status, 200)
        self.assertIn("That analysis is no longer available.", page)
        self.assertIn(analysis_id, self.analysis_dirs())

        status, _, page = self.fetch(f"/?analysis={analysis_id}")
        self.assertEqual(status, 200)
        self.assertIn("Owned analysis", page)

    def test_owner_can_delete_an_analysis(self) -> None:
        analysis_id = self.upload_ok(title="Delete me")
        status, _, page = self.fetch(f"/delete-analysis?analysis={analysis_id}")
        self.assertEqual(status, 200)
        self.assertIn("Delete analysis", page)
        self.assertIn(analysis_id, page)

        status, headers, _ = self.post_raw(
            "application/x-www-form-urlencoded",
            f"analysis_id={analysis_id}".encode(),
            path="/delete-analysis",
        )
        self.assertEqual(status, 303)
        self.assertEqual(headers["location"], "/upload?deleted=1")
        self.assertNotIn(analysis_id, self.analysis_dirs())
        self.assertFalse(
            (Path(config.UPLOAD_WAREHOUSE_DIR) / f"{analysis_id}.db").exists()
        )

        status, _, page = self.fetch(f"/?analysis={analysis_id}")
        self.assertEqual(status, 404)
        self.assertIn("Analysis not found", page)

    def test_titles_are_escaped_in_dashboard_and_history(self) -> None:
        analysis_id = self.upload_ok(title="<script>alert('x')</script>")
        status, _, page = self.fetch(f"/?analysis={analysis_id}")
        self.assertEqual(status, 200)
        self.assertIn("&lt;script&gt;alert", page)
        self.assertNotIn("<script>alert", page)

        _, _, history = self.fetch("/upload")
        self.assertIn("&lt;script&gt;alert", history)
        self.assertNotIn("<script>alert", history)


class MoneyPlanTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory()
        cls.root = Path(cls._tmp.name)
        cls.db_path = cls.root / "fixture.db"
        _seed(cls.db_path)
        cls.report_path = cls.root / "baseline_report.html"
        cls.report_path.write_text(REPORT_SENTINEL, encoding="utf-8")
        cls.server = web.create_server(
            cls.db_path,
            port=0,
            report_path=cls.report_path,
            accounts_path=cls.root / "accounts.db",
        )
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.port = cls.server.server_address[1]
        cls.base = f"http://127.0.0.1:{cls.port}"
        cls.cookie = signup_cookie(cls.base)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=5)
        cls._tmp.cleanup()

    def fetch(self, path: str, *, method: str = "GET") -> tuple[int, dict, str]:
        request = urllib.request.Request(
            self.base + path, method=method, headers={"Cookie": self.cookie}
        )
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                return (
                    response.status,
                    dict(response.headers.items()),
                    response.read().decode("utf-8"),
                )
        except urllib.error.HTTPError as error:
            return error.code, dict(error.headers.items()), error.read().decode("utf-8")

    def post_form(
        self,
        fields: list[tuple[str, str]],
        *,
        headers: dict[str, str] | None = None,
        content_type: str = "application/x-www-form-urlencoded",
        raw_body: bytes | None = None,
        path: str = "/plan",
    ) -> tuple[int, dict, str]:
        body = (
            raw_body
            if raw_body is not None
            else urllib.parse.urlencode(fields).encode("utf-8")
        )
        if raw_body is None:
            token = csrf_for(self.base, self.cookie)
            if token and b"csrf=" not in body:
                body += (b"&" if body else b"") + urllib.parse.urlencode(
                    {"csrf": token}
                ).encode("utf-8")
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        try:
            request_headers = {
                "Content-Type": content_type,
                "Cookie": self.cookie,
                "Origin": self.base,
            }
            request_headers.update(headers or ())
            connection.request("POST", path, body=body, headers=request_headers)
            response = connection.getresponse()
            payload = response.read()
            return (
                response.status,
                {name.lower(): value for name, value in response.getheaders()},
                payload.decode("utf-8", "replace"),
            )
        finally:
            connection.close()

    @staticmethod
    def plan_fields(
        *,
        name: str = "Amina",
        money: str = "14000",
        period: str = "monthly",
        method: str = "envelope",
        note: str = "Weekly envelopes; rent first.",
        categories: tuple[tuple[str, str, str], ...] = (
            ("Rent", "6000", "essential"),
            ("Food", "5000", "essential"),
            ("Fun", "1500", "flexible"),
            ("Books", "", "flexible"),
            ("Savings", "1000", "essential"),
        ),
        spendings: tuple[tuple[str, str, str], ...] = (
            ("Rent", "6000", "October rent"),
            ("Food", "3000", "Groceries"),
            ("Food", "1500", "Lunch"),
            ("Fun", "1800", "Concert"),
            ("Books", "200", "Notebook"),
        ),
        advice_ack: str | None = "yes",
    ) -> list[tuple[str, str]]:
        fields = [
            ("student_name", name),
            ("money_available", money),
            ("period", period),
            ("method", method),
            ("method_note", note),
        ]
        for number, (category_name, planned, kind) in enumerate(categories, start=1):
            fields.extend(
                [
                    (f"category_name_{number}", category_name),
                    (f"category_amount_{number}", planned),
                    (f"category_essential_{number}", kind),
                ]
            )
        for number, (category, amount, entry_note) in enumerate(
            spendings, start=1
        ):
            fields.extend(
                [
                    (f"spending_category_{number}", category),
                    (f"spending_amount_{number}", amount),
                    (f"spending_note_{number}", entry_note),
                ]
            )
        if advice_ack is not None:
            fields.append(("advice_ack", advice_ack))
        return fields

    def create_plan(
        self, fields: list[tuple[str, str]] | None = None
    ) -> str:
        status, headers, page = self.post_form(fields or self.plan_fields())
        self.assertEqual(status, 200, page[:300])
        self.assertNotIn("location", headers)
        return page

    def test_plan_page_and_entry_points(self) -> None:
        status, _, page = self.fetch("/plan")
        self.assertEqual(status, 200)
        for control in (
            "student_name",
            "money_available",
            "method",
            "method_note",
            "advice_ack",
            "category_name_1",
            "spending_category_1",
            "spending_amount_1",
        ):
            self.assertIn(f'name="{control}"', page)
        self.assertNotIn('name="category_name_2"', page)
        self.assertNotIn('name="spending_category_2"', page)
        self.assertNotIn("spending_date_1", page)
        self.assertIn("stamped with this device's clock", page)
        self.assertIn('action="/plan#analysis"', page)
        self.assertIn("There is no fixed category list", page)
        self.assertIn("A planning tool, not advice.", page)
        self.assertIn('href="/upload"', page)

        _, _, home = self.fetch("/")
        self.assertIn('href="/plan"', home)
        self.assertIn("Plan my money", home)

        _, _, upload_page = self.fetch("/upload")
        self.assertIn('href="/plan"', upload_page)

        status, headers, body = self.fetch("/plan", method="HEAD")
        self.assertEqual(status, 200)
        self.assertEqual(body, "")
        self.assertGreater(int(headers["Content-Length"]), 0)
        self.assertIn('name="category_rows" value="1"', page)
        self.assertIn('name="spending_rows" value="1"', page)
        self.assertIn('aria-label="Add another category"', page)
        self.assertIn('aria-label="Add another spending row"', page)
        self.assertIn("1 of 100 category rows", page)
        self.assertIn("1 of 100 spending rows", page)
        self.assertIn('formaction="/plan#categories-end"', page)
        self.assertIn('formaction="/plan#spending-end"', page)
        self.assertIn('id="categories-end"', page)
        self.assertIn('id="spending-end"', page)
        self.assertGreater(
            page.index('aria-label="Add another category"'),
            page.index('name="category_name_1"'),
        )
        self.assertGreater(
            page.index('aria-label="Add another spending row"'),
            page.index('name="spending_category_1"'),
        )
        self.assertNotIn('class="plan-row cat-cols plan-row-new"', page)
        self.assertNotIn('class="plan-row spend-cols plan-row-new"', page)
        self.assertNotIn("autofocus", page)
        self.assertIn("html { scroll-behavior: auto; }", page)

    def test_add_category_keeps_typed_values_without_saving(self) -> None:
        fields = self.plan_fields(
            categories=(("Rent", "6000", "essential"),),
            spendings=(("Rent", "500", "October rent"),),
        )
        fields.extend(
            [
                ("category_rows", "1"),
                ("spending_rows", "1"),
                ("action", "add_category"),
            ]
        )
        status, _, page = self.post_form(fields)
        self.assertEqual(status, 200)
        self.assertIn('name="category_name_2"', page)
        self.assertNotIn('name="category_name_3"', page)
        self.assertIn('name="category_rows" value="2"', page)
        self.assertIn('value="Amina"', page)
        self.assertIn('value="Rent"', page)
        self.assertIn('value="October rent"', page)
        self.assertIn("2 of 100 category rows", page)
        self.assertIn('id="plan-cat-2"', page)
        self.assertEqual(page.count('class="plan-row cat-cols plan-row-new"'), 1)
        self.assertIn('aria-label="Category 2 name" autocomplete="off" autofocus', page)
        self.assertIn('id="plan-cat-1"', page)
        self.assertGreater(
            page.index('aria-label="Add another category"'),
            page.index('name="category_name_2"'),
        )
        self.assertNotIn("What the numbers say", page)

    def test_add_spending_keeps_typed_values_without_saving(self) -> None:
        fields = self.plan_fields(
            categories=(("Rent", "6000", "essential"),),
            spendings=(("Rent", "500", "October rent"),),
        )
        fields.extend(
            [
                ("category_rows", "1"),
                ("spending_rows", "1"),
                ("action", "add_spending"),
            ]
        )
        status, _, page = self.post_form(fields)
        self.assertEqual(status, 200)
        self.assertIn('name="spending_category_2"', page)
        self.assertNotIn('name="spending_category_3"', page)
        self.assertIn('name="spending_rows" value="2"', page)
        self.assertIn('value="Amina"', page)
        self.assertIn('value="October rent"', page)
        self.assertIn("2 of 100 spending rows", page)
        self.assertIn('id="plan-spend-2"', page)
        self.assertEqual(page.count('class="plan-row spend-cols plan-row-new"'), 1)
        self.assertIn(
            'aria-label="Spending row 2 category" autocomplete="off" autofocus', page
        )
        self.assertIn('id="plan-spend-1"', page)
        self.assertGreater(
            page.index('aria-label="Add another spending row"'),
            page.index('name="spending_category_2"'),
        )
        self.assertNotIn("What the numbers say", page)

    def test_extra_category_rows_reach_the_inline_analysis(self) -> None:
        categories = tuple(
            (f"Category {number}", "0", "flexible") for number in range(1, 14)
        )
        fields = self.plan_fields(
            categories=categories,
            spendings=(("Category 1", "10", "Tea"),),
        )
        fields.extend([("category_rows", "13"), ("spending_rows", "1")])
        page = self.create_plan(fields)

        self.assertIn("Category 13", page)
        self.assertIn("13 categories", page)
        self.assertIn('name="category_name_13"', page)
        self.assertIn("analysis-categories", page)

    def test_spending_rows_stop_at_the_limit(self) -> None:
        fields = self.plan_fields()
        fields.extend(
            [
                ("category_rows", "1"),
                ("spending_rows", "100"),
                ("action", "add_spending"),
            ]
        )
        status, _, page = self.post_form(fields)
        self.assertEqual(status, 200)
        self.assertIn('name="spending_category_100"', page)
        self.assertNotIn('name="spending_category_101"', page)
        self.assertIn("100 spending rows is the maximum.", page)
        self.assertNotIn('aria-label="Add another spending row"', page)

        fields[-2] = ("spending_rows", "999")
        status, _, page = self.post_form(fields)
        self.assertEqual(status, 200)
        self.assertIn('name="spending_category_100"', page)
        self.assertNotIn('name="spending_category_101"', page)

    def test_maximum_rows_are_analysed_inline(self) -> None:
        categories = tuple(
            (f"Category {number}", "0", "flexible") for number in range(1, 101)
        )
        spendings = tuple(
            (f"Category {number}", "10", f"Item {number}")
            for number in range(1, 101)
        )
        fields = self.plan_fields(categories=categories, spendings=spendings)
        fields.extend([("category_rows", "100"), ("spending_rows", "100")])
        page = self.create_plan(fields)

        self.assertIn('name="category_name_100"', page)
        self.assertIn('name="spending_note_100"', page)
        self.assertIn("100 categories", page)
        self.assertIn("100 spending entries", page)
        self.assertIn("analysis-spending", page)

    def test_category_rows_stop_at_the_limit(self) -> None:
        fields = self.plan_fields()
        fields.extend(
            [
                ("category_rows", "100"),
                ("spending_rows", "1"),
                ("action", "add_category"),
            ]
        )
        status, _, page = self.post_form(fields)
        self.assertEqual(status, 200)
        self.assertIn('name="category_name_100"', page)
        self.assertNotIn('name="category_name_101"', page)
        self.assertIn("100 category rows is the maximum.", page)
        self.assertNotIn('aria-label="Add another category"', page)

        fields[-3] = ("category_rows", "999")
        status, _, page = self.post_form(fields)
        self.assertEqual(status, 200)
        self.assertIn('name="category_name_100"', page)
        self.assertNotIn('name="category_name_101"', page)

    def test_plan_submission_renders_analysis_in_the_same_page(self) -> None:
        status, headers, page = self.post_form(self.plan_fields())
        self.assertEqual(status, 200)
        self.assertNotIn("location", headers)
        self.assertEqual(headers["cache-control"], "no-store")
        for text in (
            'id="analysis"',
            "What the numbers say",
            "KES 14,000.00",
            "KES 13,500.00",
            "KES 12,500.00",
            "KES 1,500.00",
            "plan-actual",
            "plan-compare",
            "Over plan",
            "No plan",
            "Not used",
            "October rent",
            "Weekly envelopes; rent first.",
            "Essential",
            "Flexible",
            "1 category is over plan by KES 300.00 in total: Fun.",
            "analysis-categories",
            "analysis-spending",
            "analysis-method",
            "analysis-receipt",
            "generated in this page",
        ):
            self.assertIn(text, page)
        self.assertIn("<svg", page)
        self.assertIn('class="spark"', page)
        self.assertIn('href="#analysis-receipt">Open the receipt</a>', page)
        self.assertLess(
            page.index('id="analysis-receipt"'),
            page.index('id="analysis-categories"'),
        )
        self.assertNotIn("/plan?plan=", page)
        self.assertNotIn("data/plans/", page)
        self.assertIsNone(re.search(r"/plan\?plan=p-[A-Za-z0-9_-]{16}", page))

        self.assertIn('name="student_name" type="text"', page)
        self.assertIn('value="Amina"', page)
        self.assertIn('value="Rent"', page)
        self.assertIn('action="/plan#analysis"', page)

    def test_categories_at_eighty_percent_are_flagged(self) -> None:
        page = self.create_plan()
        self.assertIn("Close to plan", page)
        self.assertIn("used 80% or more of the planned amount", page)
        self.assertIn('<span class="plan-tag near">80%+ of plan</span>', page)

        wide = self.create_plan(
            self.plan_fields(
                categories=(
                    ("Rent", "6000", "essential"),
                    ("Food", "5000", "essential"),
                ),
                spendings=(("Rent", "6000", "October rent"),),
            )
        )
        self.assertNotIn("Close to plan", wide)

    def test_plan_can_be_downloaded_as_csv(self) -> None:
        status, headers, body = self.post_form(
            self.plan_fields(), path="/plan.csv"
        )
        self.assertEqual(status, 200)
        self.assertEqual(headers["content-type"], "text/csv; charset=utf-8")
        self.assertIn(
            'attachment; filename="plan-it-monthly-', headers["content-disposition"]
        )
        self.assertIn("Plan It money plan export", body)
        self.assertIn("Food,Essential,5000.00,4500.00,500.00", body)
        self.assertIn("Concert", body)
        self.assertIn(web.legal.DISCLAIMER, body)
        self.assertNotIn("<html", body)

    def test_plan_query_parameters_render_a_fresh_form(self) -> None:
        for path in (
            "/plan?plan=../../etc/passwd",
            "/plan?plan=p-short",
            "/plan?edit=p-short",
        ):
            with self.subTest(path=path):
                status, _, page = self.fetch(path)
                self.assertEqual(status, 200)
                self.assertIn('name="student_name"', page)
                self.assertNotIn("Amina", page)
                self.assertNotIn("What the numbers say", page)

    def test_validation_errors_preserve_input_and_render_no_analysis(self) -> None:
        cases = [
            (self.plan_fields(advice_ack=None),
             "Confirm that you understand Plan It is a planning tool"),
            (
                self.plan_fields(categories=(("Food", "1000", "essential"),)),
                "Add at least two categories with names.",
            ),
            (
                self.plan_fields(
                    spendings=(("Groceries", "100", ""),)
                ),
                "not one of your categories",
            ),
            (self.plan_fields(money="bad"), "must be a number"),
        ]
        for fields, message in cases:
            with self.subTest(message=message):
                status, _, page = self.post_form(fields)
                self.assertEqual(status, 422)
                self.assertIn(message, page)
                self.assertIn('value="Amina"', page)
                self.assertIn("Check these details.", page)
                self.assertNotIn("What the numbers say", page)

    def test_request_guards(self) -> None:
        fields = self.plan_fields()

        status, _, page = self.post_form(
            fields, headers={"Origin": "http://evil.example"}
        )
        self.assertEqual(status, 403)
        self.assertIn("own form", page)

        status, _, _ = self.post_form(
            fields, headers={"Sec-Fetch-Site": "cross-site"}
        )
        self.assertEqual(status, 403)

        status, _, page = self.post_form(
            [], content_type="application/json", raw_body=b"{}"
        )
        self.assertEqual(status, 415)
        self.assertIn("own form", page)

        status, _, page = self.post_form([], raw_body=b"")
        self.assertEqual(status, 400)
        self.assertIn("plan form was empty", page)

        status, _, page = self.post_form(
            fields,
            headers={
                "Content-Length": str(personal.MAX_PLAN_REQUEST_BYTES + 1)
            },
        )
        self.assertEqual(status, 413)
        self.assertIn("larger than the allowed limit", page)

        with socket.create_connection(("127.0.0.1", self.port), timeout=10) as sock:
            sock.sendall(
                b"POST /plan HTTP/1.1\r\nHost: 127.0.0.1\r\n"
                + f"Cookie: {self.cookie}\r\n".encode()
                + b"Origin: http://127.0.0.1\r\n"
                + b"Content-Type: application/x-www-form-urlencoded\r\n"
                b"Connection: close\r\n\r\n"
            )
            raw = b""
            while True:
                chunk = sock.recv(65536)
                if not chunk:
                    break
                raw += chunk
        self.assertIn(b" 411 ", raw.split(b"\r\n", 1)[0])
        self.assertIn(b"Content-Length header", raw)

        status, headers, page = self.post_form(fields, path="/missing-page")
        self.assertEqual(status, 405)
        self.assertEqual(headers["allow"], "GET, HEAD")
        self.assertIn("Read-only dashboard", page)

        status, headers, page = self.post_form(fields, headers={"Origin": self.base})
        self.assertEqual(status, 200)
        self.assertNotIn("location", headers)
        self.assertIn("What the numbers say", page)

    def test_injected_text_is_escaped(self) -> None:
        page = self.create_plan(
            self.plan_fields(
                name="<script>alert('name')</script>",
                note="<script>note()</script>",
                categories=(
                    ("<script>cat()</script>", "1000", "essential"),
                    ("<img src=x>", "500", "flexible"),
                ),
                spendings=(
                    ("<script>cat()</script>", "100", "<script>entry()</script>"),
                ),
            )
        )
        self.assertIn("&lt;script&gt;", page)
        self.assertIn("&lt;img src=x&gt;", page)
        self.assertNotIn("<script>", page)
        self.assertNotIn("<img src=x>", page)

    def test_no_planned_amounts_still_analyzes(self) -> None:
        page = self.create_plan(
            self.plan_fields(
                categories=(("Food", "", "essential"), ("Fun", "", "flexible")),
                spendings=(
                    ("Food", "800", ""),
                    ("Fun", "500", ""),
                ),
            )
        )
        self.assertIn("No planned amounts were entered", page)
        self.assertIn("actual spending only", page)
        self.assertIn("KES 1,300.00", page)
        self.assertIn("No plan", page)
        self.assertIn("plan-compare", page)

    def test_receipt_summarises_the_same_analysis(self) -> None:
        page = self.create_plan()
        for text in (
            'id="analysis-receipt"',
            'href="#analysis-receipt"',
            "Money plan receipt",
            "Your plan, itemised",
            "Planned total",
            "Recorded spending",
            "Money available",
            "Left unspent",
            "not a financial document",
            "receipt-barcode",
            "receipt-stamp",
        ):
            self.assertIn(text, page)
        self.assertIn('<span class="receipt-name">Rent</span>', page)
        self.assertIn('<span class="receipt-share">48.0%</span>', page)
        self.assertIn('<span class="receipt-amount">6,000.00</span>', page)
        self.assertIn('<span class="receipt-amount">4,500.00</span>', page)
        self.assertIn("1,500.00", page)
        self.assertNotIn("receipt-saved", page)
        self.assertNotIn("/plan?receipt", page)

    def test_receipt_is_stamped_with_the_device_clock(self) -> None:
        recorded = datetime(2026, 11, 4, 15, 30, tzinfo=timezone.utc)
        with mock.patch.object(web, "datetime") as clock:
            clock.now.return_value.astimezone.return_value = recorded
            page = self.create_plan()

        stamp = '<time datetime="2026-11-04T15:30+00:00">04 Nov 2026, 15:30</time>'
        self.assertEqual(page.count(stamp), 2)
        self.assertIn("<dt>Recorded</dt>", page)
        self.assertIn("<dt>Period</dt><dd>Monthly</dd>", page)
        self.assertIn("04 Nov 2026", page)
        self.assertIn("15:30", page)
        self.assertIn(
            "You recorded 5 spending rows, averaging KES 2,500.00 per row.", page
        )

    def test_displayed_category_shares_add_up_to_one_hundred(self) -> None:
        categories = tuple(
            (f"Equal {number}", "1000", "flexible") for number in range(1, 8)
        )
        spendings = tuple(
            (f"Equal {number}", "100", "") for number in range(1, 8)
        )
        fields = self.plan_fields(categories=categories, spendings=spendings)
        fields.extend([("category_rows", "7"), ("spending_rows", "7")])
        page = self.create_plan(fields)

        start = page.index('id="analysis-categories"')
        end = page.index('id="analysis-spending"')
        region = page[start:end]
        shares = re.findall(r'<span class="share-value">([\d.]+)%</span>', region)
        self.assertEqual(shares.count("14.3"), 6)
        self.assertEqual(shares.count("14.2"), 1)
        self.assertNotIn("100.1%", region)

    def test_percentage_copy_names_each_denominator(self) -> None:
        page = self.create_plan()
        self.assertIn("Share of recorded spending", page)
        self.assertIn("of the money available", page)
        self.assertIn("of the planned total", page)
        self.assertIn("adds up to exactly 100.0%", page)

    def test_plan_page_offers_a_period_choice(self) -> None:
        _, _, page = self.fetch("/plan")
        self.assertIn('<select id="period" name="period">', page)
        self.assertIn('<option value="monthly" selected>Monthly</option>', page)
        self.assertIn('<option value="weekly">Weekly</option>', page)
        self.assertIn("Money available per month (KES)", page)
        self.assertIn("period changes the wording", page)
        self.assertIn("coach&rsquo;s", page)
        self.assertIn("advice, not the numbers", page)

    def test_weekly_plan_changes_the_wording_not_the_numbers(self) -> None:
        page = self.create_plan(self.plan_fields(period="weekly"))
        self.assertIn("Money available per week (KES)", page)
        self.assertIn('<option value="weekly" selected>Weekly</option>', page)
        self.assertIn("available for the week", page)
        self.assertIn("<dt>Period</dt><dd>Weekly</dd>", page)
        self.assertIn("Money available (weekly)", page)
        self.assertIn("<span>Period: <strong>Weekly</strong></span>", page)
        self.assertIn("next week", page)
        self.assertNotIn("next month", page)
        self.assertIn("KES 14,000.00", page)
        self.assertIn("KES 13,500.00", page)
        self.assertIn("KES 12,500.00", page)

    def test_unknown_period_is_rejected_without_analysis(self) -> None:
        status, _, page = self.post_form(self.plan_fields(period="daily"))
        self.assertEqual(status, 422)
        self.assertIn(
            "Choose whether the money is for a month or a week.", page
        )
        self.assertNotIn("What the numbers say", page)

    def test_suggestions_are_rendered_from_the_analysis(self) -> None:
        page = self.create_plan()
        for text in (
            "How to spend it better",
            'class="suggestion-list"',
            "Bring over-plan categories back to plan",
            "1 category is over plan by KES 300.00 in total: Fun.",
            "Some spending has no plan",
            "KES 200.00 was spent in categories with no planned amount: Books.",
            "Assign the unallocated money",
            "KES 500.00 of the money available is not in any category plan.",
            "Some money is still unspent",
            "KES 1,500.00 of the money available has no recorded spending.",
            "suggestion warn",
            "suggestion note",
            "suggestion good",
            "not financial advice and nothing leaves this server.",
        ):
            self.assertIn(text, page)
        self.assertLess(
            page.index('id="analysis"'), page.index('id="analysis-receipt"')
        )
        self.assertLess(
            page.index("How to spend it better"), page.index('id="analysis-receipt"')
        )

    def test_coach_panel_embeds_the_plan_snapshot(self) -> None:
        page = self.create_plan()
        for text in (
            'id="coach"',
            'action="/plan#coach"',
            '<input type="hidden" name="action" value="ask_coach">',
            'id="coach_question" name="coach_question" type="text"',
            'maxlength="200"',
            "Ask the money coach",
            "A local rule set, not an AI model",
            'name="coach_topic"',
            "Where can I cut spending?",
            "What does the receipt time mean?",
            '<input type="hidden" name="period" value="monthly">',
            '<input type="hidden" name="category_name_1" value="Rent">',
            '<input type="hidden" name="spending_note_1" value="October rent">',
            '<input type="hidden" name="advice_ack" value="yes">',
            'href="#coach"',
        ):
            self.assertIn(text, page)
        self.assertNotIn('class="coach-answer"', page)

    def test_coach_answers_in_the_same_page_without_redirect(self) -> None:
        fields = self.plan_fields() + [
            ("action", "ask_coach"),
            ("coach_question", "How can I save more?"),
        ]
        status, headers, page = self.post_form(fields)
        self.assertEqual(status, 200)
        self.assertNotIn("location", headers)
        self.assertEqual(headers["cache-control"], "no-store")
        self.assertIn("You asked: <span>How can I save more?</span>", page)
        self.assertIn("Local rules &middot; no network", page)
        self.assertIn("Savings is planned at KES 1,000.00", page)
        self.assertIn("KES 500.00", page)
        self.assertIn("KES 1,500.00 is also unspent", page)
        self.assertIn('id="analysis"', page)
        self.assertIn("What the numbers say", page)
        self.assertIn("How to spend it better", page)

    def test_coach_quick_question_button_answers(self) -> None:
        fields = self.plan_fields() + [
            ("action", "ask_coach"),
            ("coach_topic", "What is left?"),
        ]
        status, headers, page = self.post_form(fields)
        self.assertEqual(status, 200)
        self.assertNotIn("location", headers)
        self.assertIn("You asked: <span>What is left?</span>", page)
        self.assertIn("KES 1,500.00 of the money available is unspent", page)

    def test_coach_quick_question_wins_over_stale_text(self) -> None:
        fields = self.plan_fields() + [
            ("action", "ask_coach"),
            ("coach_question", "How can I save more?"),
            ("coach_topic", "What is left?"),
        ]
        status, _, page = self.post_form(fields)
        self.assertEqual(status, 200)
        self.assertIn("You asked: <span>What is left?</span>", page)
        self.assertNotIn("You asked: <span>How can I save more?</span>", page)
        self.assertIn('value="How can I save more?"', page)

    def test_coach_question_is_escaped(self) -> None:
        fields = self.plan_fields() + [
            ("action", "ask_coach"),
            ("coach_question", '<img src=x onerror="alert(1)">'),
        ]
        status, _, page = self.post_form(fields)
        self.assertEqual(status, 200)
        self.assertNotIn("<img src=x", page)
        self.assertIn(
            "&lt;img src=x onerror=&quot;alert(1)&quot;&gt;", page
        )

    def test_coach_rejects_a_broken_plan(self) -> None:
        fields = self.plan_fields(money="") + [
            ("action", "ask_coach"),
            ("coach_question", "What is left?"),
        ]
        status, headers, page = self.post_form(fields)
        self.assertEqual(status, 422)
        self.assertNotIn("location", headers)
        self.assertIn("Enter the money available.", page)
        self.assertNotIn("Local rules &middot; no network", page)

    def test_weekly_coach_answer_uses_the_week(self) -> None:
        fields = self.plan_fields(period="weekly") + [
            ("action", "ask_coach"),
            ("coach_question", "Is this weekly or monthly?"),
        ]
        status, _, page = self.post_form(fields)
        self.assertEqual(status, 200)
        self.assertIn("set to a weekly period", page)
        self.assertIn("treated as a week figure", page)


class AuthTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory()
        cls.root = Path(cls._tmp.name)
        cls.db_path = cls.root / "fixture.db"
        _seed(cls.db_path)
        cls.report_path = cls.root / "spending_report.html"
        cls.report_path.write_text(REPORT_SENTINEL, encoding="utf-8")
        cls.accounts_db = cls.root / "accounts.db"
        cls.server = web.create_server(
            cls.db_path,
            port=0,
            report_path=cls.report_path,
            accounts_path=cls.accounts_db,
        )
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.port = cls.server.server_address[1]
        cls.base = f"http://127.0.0.1:{cls.port}"
        cls.cookie = signup_cookie(
            cls.base, email="member@example.test", name="Member Student"
        )

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=5)
        cls._tmp.cleanup()

    def setUp(self) -> None:
        self.server.login_attempts.clear("127.0.0.1")

    def request(
        self,
        method: str,
        path: str,
        *,
        fields: dict[str, str] | None = None,
        headers: dict[str, str] | None = None,
        body: bytes | None = None,
    ) -> tuple[int, dict, str]:
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=30)
        try:
            request_headers = dict(headers or {})
            if fields is not None or body is not None:
                request_headers.setdefault(
                    "Content-Type", "application/x-www-form-urlencoded"
                )
            if method == "POST":
                request_headers.setdefault("Origin", self.base)
            if (
                method == "POST"
                and fields is not None
                and path not in {"/login", "/signup", "/reset"}
                and "csrf" not in fields
            ):
                token = csrf_for(
                    self.base, request_headers.get("Cookie", self.cookie)
                )
                if token:
                    fields = dict(fields)
                    fields["csrf"] = token
            payload = (
                urllib.parse.urlencode(fields).encode("utf-8")
                if fields is not None
                else body
            )
            connection.request(method, path, body=payload, headers=request_headers)
            response = connection.getresponse()
            text = response.read().decode("utf-8", "replace")
            return (
                response.status,
                {name.lower(): value for name, value in response.getheaders()},
                text,
            )
        finally:
            connection.close()

    def signup_fields(self, **overrides: str) -> dict[str, str]:
        fields = {
            "display_name": "New Student",
            "email": "new@example.test",
            "password": "synthetic1",
            "confirm": "synthetic1",
            "privacy_ack": "yes",
        }
        fields.update(overrides)
        return fields

    def login_fields(self, **overrides: str) -> dict[str, str]:
        fields = {"email": "member@example.test", "password": "synthetic1"}
        fields.update(overrides)
        return fields

    def account_rows(self) -> list[sqlite3.Row]:
        connection = sqlite3.connect(self.accounts_db)
        connection.row_factory = sqlite3.Row
        try:
            return connection.execute(
                "SELECT display_name, email, password_hash FROM accounts ORDER BY email"
            ).fetchall()
        finally:
            connection.close()

    def test_login_and_signup_pages_render_forms(self) -> None:
        status, headers, page = self.request("GET", "/login")
        self.assertEqual(status, 200)
        self.assertEqual(headers["cache-control"], "no-store")
        self.assertIn("default-src 'none'", headers["content-security-policy"])
        for text in (
            'action="/login"',
            'name="email"',
            'name="password"',
            'name="next"',
            'href="/signup?next=%2Fplan"',
            "Local account",
        ):
            self.assertIn(text, page)

        status, _, page = self.request("GET", "/signup")
        self.assertEqual(status, 200)
        for text in (
            'action="/signup"',
            'name="display_name"',
            'name="email"',
            'name="password"',
            'name="confirm"',
            "local account",
            "Never enter card numbers, bank or mobile-money PINs",
        ):
            self.assertIn(text, page)

    def test_signin_pages_redirect_a_signed_in_account(self) -> None:
        status, headers, _ = self.request(
            "GET", "/login?next=/upload", headers={"Cookie": self.cookie}
        )
        self.assertEqual(status, 303)
        self.assertEqual(headers["location"], "/upload")

        status, headers, _ = self.request(
            "GET", "/signup?next=/", headers={"Cookie": self.cookie}
        )
        self.assertEqual(status, 303)
        self.assertEqual(headers["location"], "/")

    def test_signup_creates_hashed_account_and_session_cookie(self) -> None:
        status, headers, _ = self.request("POST", "/signup", fields=self.signup_fields())
        self.assertEqual(status, 303)
        self.assertEqual(headers["location"], "/account?new=1")
        cookie = headers["set-cookie"]
        self.assertIn("ssa_session=", cookie)
        self.assertIn("HttpOnly", cookie)
        self.assertIn("SameSite=Strict", cookie)
        self.assertIn("Path=/", cookie)
        self.assertIn("Max-Age=28800", cookie)

        rows = {row["email"]: row for row in self.account_rows()}
        self.assertIn("new@example.test", rows)
        stored = rows["new@example.test"]["password_hash"]
        self.assertTrue(stored.startswith("scrypt$16384$8$1$"))
        self.assertNotIn("synthetic1", stored)
        self.assertEqual(rows["new@example.test"]["display_name"], "New Student")

        session_cookie = cookie.split(";", 1)[0]
        status, _, page = self.request(
            "GET", "/plan", headers={"Cookie": session_cookie}
        )
        self.assertEqual(status, 200)
        self.assertIn("Signed in as", page)
        self.assertIn("New Student", page)

    def test_signup_validation_preserves_fields_and_rejects_duplicates(self) -> None:
        status, headers, page = self.request(
            "POST",
            "/signup",
            fields=self.signup_fields(
                email="broken@example.test",
                password="short",
                confirm="different",
            ),
        )
        self.assertEqual(status, 422)
        self.assertNotIn("set-cookie", headers)
        for text in (
            "at least 10 characters",
            "two passwords do not match",
            'value="New Student"',
            'value="broken@example.test"',
        ):
            self.assertIn(text, page)

        status, _, page = self.request(
            "POST",
            "/signup",
            fields=self.signup_fields(email="MEMBER@example.test", display_name="Clash"),
        )
        self.assertEqual(status, 422)
        self.assertIn("already exists", page)
        self.assertEqual(
            sum(1 for row in self.account_rows() if row["email"] == "member@example.test"),
            1,
        )

        status, _, page = self.request(
            "POST", "/signup", fields=self.signup_fields(email="not-an-email")
        )
        self.assertEqual(status, 422)
        self.assertIn("does not look valid", page)

        status, _, page = self.request(
            "POST",
            "/signup",
            fields=self.signup_fields(
                email="noconsent@example.test", privacy_ack=""
            ),
        )
        self.assertEqual(status, 422)
        self.assertIn("privacy notice and terms", page)
        self.assertNotIn(
            "noconsent@example.test",
            {row["email"] for row in self.account_rows()},
        )

    def test_signin_rejects_bad_credentials_without_a_cookie(self) -> None:
        status, headers, page = self.request(
            "POST", "/login", fields=self.login_fields(password="wrongpass1")
        )
        self.assertEqual(status, 401)
        self.assertNotIn("set-cookie", headers)
        self.assertIn("did not match", page)

        status, headers, page = self.request(
            "POST",
            "/login",
            fields=self.login_fields(email="nobody@example.test", password="wrongpass1"),
        )
        self.assertEqual(status, 401)
        self.assertNotIn("set-cookie", headers)
        self.assertIn("did not match", page)
        self.assertNotIn("unknown account", page.lower())

        status, headers, page = self.request(
            "POST", "/login", fields={"email": "", "password": ""}
        )
        self.assertEqual(status, 422)
        self.assertNotIn("set-cookie", headers)
        self.assertIn("Enter both the email and the password", page)

    def test_signin_sets_cookie_and_only_follows_safe_next_paths(self) -> None:
        status, headers, _ = self.request(
            "POST", "/login", fields=self.login_fields(next="/upload")
        )
        self.assertEqual(status, 303)
        self.assertEqual(headers["location"], "/upload")
        self.assertIn("ssa_session=", headers["set-cookie"])

        for unsafe in ("//evil.example", "https://evil.example", "/missing"):
            with self.subTest(next=unsafe):
                status, headers, _ = self.request(
                    "POST", "/login", fields=self.login_fields(next=unsafe)
                )
                self.assertEqual(status, 303)
                self.assertEqual(headers["location"], "/plan")

    def test_signin_lands_on_the_destination_without_a_delay(self) -> None:
        status, headers, _ = self.request(
            "POST", "/login", fields=self.login_fields(next="/upload")
        )
        self.assertEqual(status, 303)
        self.assertEqual(headers["location"], "/upload")
        cookie = headers["set-cookie"].split(";", 1)[0]

        status, headers, _ = self.request(
            "GET", "/welcome?next=%2Fupload", headers={"Cookie": cookie}
        )
        self.assertEqual(status, 303)
        self.assertEqual(headers["location"], "/upload")

    def test_welcome_requires_signin_and_sanitises_next(self) -> None:
        status, headers, _ = self.request("GET", "/welcome?next=/upload")
        self.assertEqual(status, 303)
        self.assertEqual(headers["location"], "/login?next=%2Fupload")

        status, headers, _ = self.request(
            "GET", "/welcome?next=https://evil.example",
            headers={"Cookie": self.cookie},
        )
        self.assertEqual(status, 303)
        self.assertEqual(headers["location"], "/plan")

    def test_account_page_shows_the_recovery_code_once(self) -> None:
        status, headers, _ = self.request(
            "POST",
            "/signup",
            fields=self.signup_fields(email="codes@example.test", display_name="Code Student"),
        )
        self.assertEqual(status, 303)
        cookie = headers["set-cookie"].split(";", 1)[0]

        status, _, page = self.request(
            "GET", "/account?new=1", headers={"Cookie": cookie}
        )
        self.assertEqual(status, 200)
        self.assertIn("Save this recovery code now", page)
        self.assertIn("Signed in as", page)
        self.assertIn("Code Student", page)
        self.assertIn("Privacy consent", page)
        self.assertIn("Draft - to be reviewed by a qualified Kenyan lawyer", page)
        self.assertIn(web.legal.DISCLAIMER, page)
        match = re.search(r'class="account-code">([A-Z0-9-]{19})</code>', page)
        self.assertIsNotNone(match, page[:500])

        status, _, second = self.request(
            "GET", "/account", headers={"Cookie": cookie}
        )
        self.assertEqual(status, 200)
        self.assertNotIn("Save this recovery code now", second)
        self.assertNotIn(match.group(1), second)

    def test_recovery_code_resets_password_and_is_single_use(self) -> None:
        status, headers, _ = self.request(
            "POST",
            "/signup",
            fields=self.signup_fields(email="recover@example.test", display_name="Recover Student"),
        )
        self.assertEqual(status, 303)
        cookie = headers["set-cookie"].split(";", 1)[0]
        _, _, page = self.request("GET", "/account?new=1", headers={"Cookie": cookie})
        code = re.search(r'class="account-code">([A-Z0-9-]{19})</code>', page)
        self.assertIsNotNone(code)
        recovery = code.group(1)

        status, headers, page = self.request(
            "POST",
            "/reset",
            fields={
                "email": "recover@example.test",
                "recovery_code": recovery,
                "password": "replacement1",
                "confirm": "replacement1",
            },
        )
        self.assertEqual(status, 303)
        self.assertEqual(headers["location"], "/login?reset=1")
        self.assertIsNone(
            self.server.accounts.authenticate("recover@example.test", "synthetic1")
        )
        self.assertIsNotNone(
            self.server.accounts.authenticate("recover@example.test", "replacement1")
        )

        status, _, page = self.request(
            "POST",
            "/reset",
            fields={
                "email": "recover@example.test",
                "recovery_code": recovery,
                "password": "another1234",
                "confirm": "another1234",
            },
        )
        self.assertEqual(status, 422)
        self.assertIn("did not match, or the code was already used", page)

        status, headers, _ = self.request(
            "GET", "/plan", headers={"Cookie": cookie}
        )
        self.assertEqual(status, 303)
        self.assertIn("/login?next=", headers["location"])

    def test_password_change_signs_out_every_session(self) -> None:
        status, headers, _ = self.request(
            "POST",
            "/signup",
            fields=self.signup_fields(email="change@example.test", display_name="Change Student"),
        )
        self.assertEqual(status, 303)
        cookie = headers["set-cookie"].split(";", 1)[0]

        status, _, page = self.request(
            "POST",
            "/account/password",
            fields={
                "current_password": "wrongpass1",
                "new_password": "replacement1",
                "confirm": "replacement1",
            },
            headers={"Cookie": cookie},
        )
        self.assertEqual(status, 422)
        self.assertIn("current password did not match", page)

        status, headers, _ = self.request(
            "POST",
            "/account/password",
            fields={
                "current_password": "synthetic1",
                "new_password": "replacement1",
                "confirm": "replacement1",
            },
            headers={"Cookie": cookie},
        )
        self.assertEqual(status, 303)
        self.assertEqual(headers["location"], "/login?changed=1")
        self.assertIn("Max-Age=0", headers["set-cookie"])

        status, headers, _ = self.request(
            "GET", "/plan", headers={"Cookie": cookie}
        )
        self.assertEqual(status, 303)
        self.assertIn("/login?next=", headers["location"])
        self.assertIsNotNone(
            self.server.accounts.authenticate("change@example.test", "replacement1")
        )

    def test_export_requires_password_and_omits_hashes(self) -> None:
        status, headers, _ = self.request(
            "POST",
            "/signup",
            fields=self.signup_fields(email="export@example.test", display_name="Export Student"),
        )
        self.assertEqual(status, 303)
        cookie = headers["set-cookie"].split(";", 1)[0]

        status, _, page = self.request(
            "POST",
            "/account/export",
            fields={"password": "wrongpass1"},
            headers={"Cookie": cookie},
        )
        self.assertEqual(status, 422)
        self.assertIn("password did not match", page)

        status, headers, page = self.request(
            "POST",
            "/account/export",
            fields={"password": "synthetic1"},
            headers={"Cookie": cookie},
        )
        self.assertEqual(status, 200)
        self.assertIn("application/json", headers["content-type"])
        self.assertIn("attachment;", headers["content-disposition"])
        payload = json.loads(page)
        self.assertEqual(payload["account"]["email"], "export@example.test")
        self.assertEqual(payload["policy_version"], web.legal.POLICY_VERSION)
        self.assertEqual(payload["disclaimer"], web.legal.DISCLAIMER)
        self.assertNotIn("synthetic1", page)
        self.assertNotIn("scrypt$", page)

    def test_delete_account_removes_sessions_and_account(self) -> None:
        status, headers, _ = self.request(
            "POST",
            "/signup",
            fields=self.signup_fields(email="delete@example.test", display_name="Delete Student"),
        )
        self.assertEqual(status, 303)
        cookie = headers["set-cookie"].split(";", 1)[0]

        status, _, page = self.request(
            "POST",
            "/account/delete",
            fields={"password": "wrongpass1", "confirm_delete": "yes"},
            headers={"Cookie": cookie},
        )
        self.assertEqual(status, 422)
        self.assertIn("password did not match", page)

        status, headers, _ = self.request(
            "POST",
            "/account/delete",
            fields={"password": "synthetic1", "confirm_delete": "yes"},
            headers={"Cookie": cookie},
        )
        self.assertEqual(status, 303)
        self.assertEqual(headers["location"], "/login?deleted=1")
        self.assertIn("Max-Age=0", headers["set-cookie"])
        self.assertIsNone(
            self.server.accounts.authenticate("delete@example.test", "synthetic1")
        )

        status, headers, _ = self.request(
            "GET", "/plan", headers={"Cookie": cookie}
        )
        self.assertEqual(status, 303)
        self.assertIn("/login?next=", headers["location"])

    def test_legal_pages_carry_the_required_notices(self) -> None:
        status, _, page = self.request("GET", "/privacy")
        self.assertEqual(status, 200)
        self.assertIn(web.legal.DRAFT_NOTICE, page)
        self.assertIn("Draft - to be reviewed by a qualified Kenyan lawyer before launch.", page)
        self.assertIn("Office of the Data Protection Commissioner", page)
        self.assertIn("72 hours", page)

        status, _, page = self.request("GET", "/terms")
        self.assertEqual(status, 200)
        self.assertIn(web.legal.DISCLAIMER, page)
        self.assertIn(web.legal.MPESA_NOTICE, page)
        self.assertIn("not licensed by the Central Bank of", page)
        self.assertIn("THIRD_PARTY_LICENSES.md", page)

    def test_anonymous_requests_to_personal_tools_are_gated(self) -> None:
        for path in ("/plan", "/upload", "/account"):
            with self.subTest(path=path):
                status, headers, _ = self.request("GET", path)
                self.assertEqual(status, 303)
                self.assertEqual(
                    headers["location"],
                    f"/login?next={urllib.parse.quote(path, safe='')}",
                )

        status, headers, _ = self.request(
            "POST", "/plan", fields={"student_name": "Amina"}
        )
        self.assertEqual(status, 303)
        self.assertIn("next=%2Fplan", headers["location"])
        self.assertEqual(headers.get("connection", "").lower(), "close")

        status, headers, _ = self.request("POST", "/upload", body=b"")
        self.assertEqual(status, 303)
        self.assertIn("next=%2Fupload", headers["location"])

        status, _, page = self.request("GET", "/")
        self.assertEqual(status, 200)
        self.assertIn("Sample dashboard", page)
        self.assertIn('href="/login"', page)
        self.assertIn('href="/signup"', page)

        status, _, page = self.request("GET", "/report")
        self.assertEqual(status, 200)
        self.assertIn("REPORT SENTINEL", page)

    def test_authenticated_forms_require_the_session_csrf_token(self) -> None:
        status, _, page = self.request(
            "GET", "/account", headers={"Cookie": self.cookie}
        )
        self.assertEqual(status, 200)
        self.assertIn('name="csrf" value="', page)
        self.assertEqual(page.count('name="csrf"'), 5)

        for token in ("", "not-the-token"):
            with self.subTest(token=token):
                status, _, body = self.request(
                    "POST",
                    "/account/consent",
                    fields={"privacy_ack": "yes", "csrf": token},
                    headers={"Cookie": self.cookie},
                )
                self.assertEqual(status, 403)
                self.assertIn("did not come from this page", body)

        status, _, body = self.request(
            "POST",
            "/account/consent",
            fields={"privacy_ack": "yes"},
            headers={"Cookie": self.cookie},
        )
        self.assertEqual(status, 303)
        self.assertEqual(body, "")

    def test_logout_clears_the_session_and_cookie(self) -> None:
        _, headers, _ = self.request(
            "POST",
            "/signup",
            fields=self.signup_fields(email="leaver@example.test"),
        )
        cookie = headers["set-cookie"].split(";", 1)[0]

        status, headers, _ = self.request(
            "POST",
            "/logout",
            fields={},
            headers={"Cookie": cookie, "Origin": self.base},
        )
        self.assertEqual(status, 303)
        self.assertEqual(headers["location"], "/login?signedout=1")
        self.assertIn("Max-Age=0", headers["set-cookie"])

        status, headers, _ = self.request("GET", "/plan", headers={"Cookie": cookie})
        self.assertEqual(status, 303)
        self.assertIn("/login?next=", headers["location"])

        _, _, page = self.request("GET", "/login?signedout=1")
        self.assertIn("You are signed out", page)

        status, _, page = self.request(
            "POST",
            "/logout",
            fields={},
            headers={"Cookie": self.cookie, "Origin": "http://evil.example"},
        )
        self.assertEqual(status, 403)
        self.assertIn("own form", page)

    def test_forged_and_expired_sessions_are_rejected(self) -> None:
        forged = "ssa_session=" + "x" * 43
        status, headers, _ = self.request("GET", "/plan", headers={"Cookie": forged})
        self.assertEqual(status, 303)
        self.assertIn("/login?next=", headers["location"])

        account = self.server.accounts.create_account(
            "Expiry Student", "expiry@example.test", "synthetic1"
        )
        token = self.server.accounts.create_session(account.account_id)
        connection = sqlite3.connect(self.accounts_db)
        try:
            with connection:
                connection.execute(
                    "UPDATE sessions SET expires_at = '2000-01-01T00:00:00+00:00' "
                    "WHERE account_id = ?",
                    (account.account_id,),
                )
        finally:
            connection.close()

        status, headers, _ = self.request(
            "GET", "/plan", headers={"Cookie": f"ssa_session={token}"}
        )
        self.assertEqual(status, 303)
        self.assertIn("/login?next=", headers["location"])

    def test_repeated_signin_failures_are_rate_limited(self) -> None:
        fields = self.login_fields(email="nobody@example.test", password="wrongpass1")
        for _ in range(web.AUTH_ATTEMPT_LIMIT):
            status, _, _ = self.request("POST", "/login", fields=fields)
            self.assertEqual(status, 401)

        status, headers, page = self.request("POST", "/login", fields=fields)
        self.assertEqual(status, 429)
        self.assertEqual(
            headers["retry-after"], str(web.AUTH_ATTEMPT_WINDOW_SECONDS)
        )
        self.assertIn("Too many sign-in attempts", page)
        self.assertNotIn("set-cookie", headers)


if __name__ == "__main__":
    unittest.main()
