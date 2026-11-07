from __future__ import annotations

import importlib.util
import sqlite3
import tempfile
import unittest
from email.message import Message
from pathlib import Path
from unittest import mock

from student_spending import config, legal, web


class ProductionConfigurationTests(unittest.TestCase):
    def test_development_never_blocks_startup(self) -> None:
        with mock.patch.object(config, "PRODUCTION", False):
            self.assertEqual(config.production_problems(), [])

    def test_production_reports_every_missing_requirement(self) -> None:
        with (
            mock.patch.object(config, "PRODUCTION", True),
            mock.patch.object(config, "PUBLIC_URL", "http://planit.example.com"),
            mock.patch.object(config, "SECURE_COOKIES", False),
            mock.patch.object(config, "OPERATOR_NAME", ""),
            mock.patch.object(config, "OPERATOR_ADDRESS", ""),
            mock.patch.object(config, "PRIVACY_EMAIL", "not-an-email"),
            mock.patch.object(config, "EFFECTIVE_DATE", ""),
            mock.patch.object(config, "HOSTING_PROVIDER", ""),
            mock.patch.object(config, "ODPC_REGISTRATION", "[NOT SET]"),
            mock.patch.object(config, "LIABILITY_CAP", "[NOT SET]"),
            mock.patch.object(config, "LEGAL_REVIEWED", False),
        ):
            problems = config.production_problems()

        joined = "\n".join(problems)
        self.assertIn("PLANIT_PUBLIC_URL", joined)
        self.assertIn("PLANIT_SECURE_COOKIES", joined)
        self.assertIn("PLANIT_OPERATOR_NAME", joined)
        self.assertIn("PLANIT_PRIVACY_EMAIL must be a usable email", joined)
        self.assertIn("PLANIT_ODPC_REGISTRATION", joined)
        self.assertIn("PLANIT_LIABILITY_CAP", joined)
        self.assertIn("PLANIT_LEGAL_REVIEWED=1", joined)

    def test_complete_production_configuration_passes(self) -> None:
        with (
            mock.patch.object(config, "PRODUCTION", True),
            mock.patch.object(config, "PUBLIC_URL", "https://planit.example.com"),
            mock.patch.object(config, "SECURE_COOKIES", True),
            mock.patch.object(config, "OPERATOR_NAME", "Plan It Operator Ltd"),
            mock.patch.object(config, "OPERATOR_ADDRESS", "12 Example Road"),
            mock.patch.object(config, "PRIVACY_EMAIL", "privacy@example.com"),
            mock.patch.object(config, "EFFECTIVE_DATE", "2026-12-01"),
            mock.patch.object(config, "HOSTING_PROVIDER", "Example Hosting"),
            mock.patch.object(config, "ODPC_REGISTRATION", "OPC-12345"),
            mock.patch.object(config, "LIABILITY_CAP", "KES 10,000"),
            mock.patch.object(config, "LEGAL_REVIEWED", True),
        ):
            self.assertEqual(config.production_problems(), [])

    def test_legal_pages_fill_operator_values(self) -> None:
        with (
            mock.patch.object(config, "OPERATOR_NAME", "Plan It Operator Ltd"),
            mock.patch.object(config, "OPERATOR_ADDRESS", "12 Example Road"),
            mock.patch.object(config, "PRIVACY_EMAIL", "privacy@example.com"),
            mock.patch.object(config, "ODPC_REGISTRATION", "OPC-12345"),
            mock.patch.object(config, "LIABILITY_CAP", "Liability is capped."),
            mock.patch.object(config, "EFFECTIVE_DATE", "2026-12-01"),
            mock.patch.object(config, "HOSTING_PROVIDER", "Example Hosting"),
        ):
            privacy = legal.privacy_body()
            terms = legal.terms_body()

        self.assertIn("Plan It Operator Ltd", privacy)
        self.assertIn("privacy@example.com", privacy)
        self.assertIn("OPC-12345", privacy)
        self.assertIn("2026-12-01", privacy)
        self.assertNotIn("[FULL LEGAL NAME OF CONTROLLER]", privacy)
        self.assertNotIn("[PRIVACY EMAIL]", privacy)
        self.assertIn("Liability is capped.", terms)
        self.assertIn("Example Hosting", privacy)


class ProxyHeaderTests(unittest.TestCase):
    @staticmethod
    def handler(forwarded: str | None) -> web.DashboardHandler:
        instance = object.__new__(web.DashboardHandler)
        instance.client_address = ("192.0.2.10", 5000)
        instance.headers = Message()
        if forwarded is not None:
            instance.headers["X-Forwarded-For"] = forwarded
        return instance

    def test_forwarded_address_is_ignored_by_default(self) -> None:
        with mock.patch.object(config, "TRUST_PROXY", False):
            self.assertEqual(
                self.handler("203.0.113.9, 10.0.0.1")._client_key(),
                "192.0.2.10",
            )

    def test_forwarded_address_is_used_when_the_proxy_is_trusted(self) -> None:
        with mock.patch.object(config, "TRUST_PROXY", True):
            self.assertEqual(
                self.handler("203.0.113.9, 10.0.0.1")._client_key(),
                "203.0.113.9",
            )

    def test_invalid_forwarded_value_falls_back_to_the_peer(self) -> None:
        with mock.patch.object(config, "TRUST_PROXY", True):
            self.assertEqual(
                self.handler("not-an-address")._client_key(),
                "192.0.2.10",
            )
            self.assertEqual(self.handler(None)._client_key(), "192.0.2.10")


class PackagingTests(unittest.TestCase):
    def test_packaged_schema_matches_the_checkout_copy(self) -> None:
        root = Path(__file__).resolve().parents[1]
        source = (root / "sql" / "schema.sql").read_bytes()
        packaged = (root / "src" / "student_spending" / "schema.sql").read_bytes()
        self.assertEqual(packaged, source)


class BackupScriptTests(unittest.TestCase):
    def test_snapshot_contains_accounts_warehouses_and_uploads(self) -> None:
        root = Path(__file__).resolve().parents[1]
        spec = importlib.util.spec_from_file_location(
            "backup_planit", root / "scripts" / "backup_planit.py"
        )
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            data = base / "data"
            warehouse = base / "warehouse"
            reports = base / "reports"
            uploads = data / "uploads" / "analysis-1"
            uploads.mkdir(parents=True)
            (uploads / "transactions.csv").write_text("a,b\n", encoding="utf-8")

            accounts = data / "accounts.db"
            connection = sqlite3.connect(accounts)
            connection.execute("CREATE TABLE accounts (id INTEGER PRIMARY KEY)")
            connection.execute("INSERT INTO accounts DEFAULT VALUES")
            connection.commit()
            connection.close()

            main_db = warehouse / "student_spending.db"
            main_db.parent.mkdir(parents=True)
            connection = sqlite3.connect(main_db)
            connection.execute("CREATE TABLE transactions (id INTEGER)")
            connection.commit()
            connection.close()

            uploaded_db = warehouse / "uploads" / "analysis-1.db"
            uploaded_db.parent.mkdir(parents=True)
            connection = sqlite3.connect(uploaded_db)
            connection.execute("CREATE TABLE transactions (id INTEGER)")
            connection.commit()
            connection.close()

            with (
                mock.patch.object(config, "ACCOUNTS_DB_PATH", accounts),
                mock.patch.object(config, "DEFAULT_DB_PATH", main_db),
                mock.patch.object(config, "WAREHOUSE_DIR", warehouse),
                mock.patch.object(config, "UPLOAD_DATA_DIR", data / "uploads"),
                mock.patch.object(config, "UPLOAD_REPORT_DIR", reports),
            ):
                self.assertEqual(module.main(["--dest", str(base / "backups")]), 0)

            snapshots = list((base / "backups").iterdir())
            self.assertEqual(len(snapshots), 1)
            snapshot = snapshots[0]
            for relative in (
                "accounts.db",
                "warehouse/student_spending.db",
                "warehouse/uploads/analysis-1.db",
                "uploads/analysis-1/transactions.csv",
            ):
                self.assertTrue((snapshot / relative).is_file(), relative)

            connection = sqlite3.connect(snapshot / "accounts.db")
            try:
                self.assertEqual(
                    connection.execute("SELECT COUNT(*) FROM accounts").fetchone()[0],
                    1,
                )
            finally:
                connection.close()

    def test_empty_installation_returns_a_warning(self) -> None:
        root = Path(__file__).resolve().parents[1]
        spec = importlib.util.spec_from_file_location(
            "backup_planit_empty", root / "scripts" / "backup_planit.py"
        )
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            with (
                mock.patch.object(config, "ACCOUNTS_DB_PATH", base / "missing.db"),
                mock.patch.object(config, "DEFAULT_DB_PATH", base / "missing-main.db"),
                mock.patch.object(config, "WAREHOUSE_DIR", base / "warehouse"),
                mock.patch.object(config, "UPLOAD_DATA_DIR", base / "uploads"),
                mock.patch.object(config, "UPLOAD_REPORT_DIR", base / "reports"),
            ):
                self.assertEqual(module.main(["--dest", str(base / "backups")]), 1)


if __name__ == "__main__":
    unittest.main()
