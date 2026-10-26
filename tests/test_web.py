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
from unittest import mock

from student_spending import cli, config, database, platform, web

REPORT_SENTINEL = "<!DOCTYPE html><html><body>REPORT SENTINEL</body></html>"
LOADED_AT = "2026-09-30T12:00:00+00:00"

CLEAN_PROFILES = """student_id,profile_label,campus,study_year,monthly_income_kes
STU-001,Profile A,Main Campus,1,30000
STU-002,Profile B,Main Campus,2,21000
"""

CLEAN_BUDGETS = """student_id,budget_month,category,budget_kes
STU-001,2026-07,Food,2000.00
STU-001,2026-07,Education,1000.00
"""

CLEAN_TRANSACTIONS = """transaction_id,student_id,transaction_date,amount_kes,category,description,payment_method,merchant,is_recurring
TXN-1001,STU-001,2026-07-01,300.00,Food,Tea,Cash,Campus Cafe,false
TXN-1002,STU-001,2026-07-02,300.00,Food,Lunch,Cash,Campus Cafe,false
TXN-1003,STU-001,2026-07-03,300.00,Food,Snack,Cash,Campus Cafe,false
TXN-1004,STU-001,2026-07-04,400.00,Education,Book,Card,Bookshop,false
"""

SECOND_BUDGETS = """student_id,budget_month,category,budget_kes
STU-002,2026-08,Food,2000.00
STU-002,2026-08,Education,1200.00
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

UNKNOWN_TRANSACTIONS = """transaction_id,student_id,transaction_date,amount_kes,category,description,payment_method,merchant,is_recurring
TXN-9001,STU-999,2026-07-01,300.00,Food,Tea,Cash,Campus Cafe,false
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
        self.assertEqual(headers["Referrer-Policy"], "same-origin")
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
            cls.db_path, port=0, report_path=cls.report_path
        )
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.port = cls.server.server_address[1]
        cls.base = f"http://127.0.0.1:{cls.port}"

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=5)
        cls._config_patch.stop()
        cls._tmp.cleanup()

    def fetch(self, path: str, *, method: str = "GET") -> tuple[int, dict, str]:
        request = urllib.request.Request(self.base + path, method=method)
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
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=60)
        try:
            request_headers = {"Content-Type": content_type}
            request_headers.update(headers or {})
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
        profiles: str = CLEAN_PROFILES,
        budgets: str = CLEAN_BUDGETS,
    ) -> dict[str, tuple[str, bytes]]:
        return {
            "transactions": ("transactions.csv", transactions.encode("utf-8")),
            "profiles": ("profiles.csv", profiles.encode("utf-8")),
            "budgets": ("budgets.csv", budgets.encode("utf-8")),
        }

    @staticmethod
    def multipart(
        files: dict[str, tuple[str, bytes]],
        *,
        title: str | None = "",
        synthetic: bool = True,
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
        if synthetic:
            add_text("synthetic", "yes")
        for name, value in extra or []:
            add_text(name, value)
        for name in ("transactions", "profiles", "budgets"):
            entry = files.get(name)
            if entry is not None:
                add_file(name, entry[0], entry[1])
        chunks.append(f"--{boundary}--\r\n".encode("utf-8"))
        return f"multipart/form-data; boundary={boundary}", b"".join(chunks)

    def upload(
        self,
        files: dict[str, tuple[str, bytes]] | None = None,
        *,
        title: str | None = "",
        synthetic: bool = True,
        extra: list[tuple[str, str]] | None = None,
        duplicate_title: bool = False,
        headers: dict[str, str] | None = None,
    ) -> tuple[int, dict, str]:
        content_type, body = self.multipart(
            files if files is not None else self.csv_files(),
            title=title,
            synthetic=synthetic,
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
        for control in ("title", "transactions", "profiles", "budgets", "synthetic"):
            self.assertIn(f'name="{control}"', page)
        self.assertIn('enctype="multipart/form-data"', page)
        self.assertIn('action="/upload"', page)
        self.assertIn('href="/samples/student_expenses.csv"', page)
        self.assertIn('href="/samples/student_profiles.csv"', page)
        self.assertIn('href="/samples/student_budgets.csv"', page)
        self.assertIn("2 MB per file", page)
        self.assertIn("Synthetic data only.", page)

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
        self.assertEqual(status, 200)
        self.assertTrue(body.startswith("student_id,profile_label,"))

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
        for name in ("transactions.csv", "profiles.csv", "budgets.csv", "metadata.json"):
            self.assertTrue((data_root / name).is_file(), name)
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
        good = self.csv_files()
        missing_budgets = self.csv_files()
        missing_budgets.pop("budgets")
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
            ("missing confirmation", dict(synthetic=False), 400,
             "Confirm that the files contain only synthetic data"),
            ("duplicate title", dict(duplicate_title=True), 400,
             "appeared more than once"),
            ("unexpected field", dict(extra=[("probe", "x")]), 400,
             "Unexpected field"),
            ("missing budgets", dict(files=missing_budgets), 400,
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
                b"Content-Type: multipart/form-data; boundary=x\r\n"
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
            self.csv_files(transactions=UNKNOWN_TRANSACTIONS),
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
            self.csv_files(
                transactions=SECOND_TRANSACTIONS, budgets=SECOND_BUDGETS
            ),
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

    def test_titles_are_escaped_in_dashboard_and_history(self) -> None:
        analysis_id = self.upload_ok(title="<script>alert('x')</script>")
        status, _, page = self.fetch(f"/?analysis={analysis_id}")
        self.assertEqual(status, 200)
        self.assertIn("&lt;script&gt;alert", page)
        self.assertNotIn("<script>alert", page)

        _, _, history = self.fetch("/upload")
        self.assertIn("&lt;script&gt;alert", history)
        self.assertNotIn("<script>alert", history)


if __name__ == "__main__":
    unittest.main()
