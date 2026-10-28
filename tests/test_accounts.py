from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from student_spending import accounts


class PasswordHashingTests(unittest.TestCase):
    def test_hash_is_salted_scrypt_and_verifies(self) -> None:
        first = accounts.hash_password("synthetic1")
        second = accounts.hash_password("synthetic1")
        self.assertTrue(first.startswith("scrypt$16384$8$1$"))
        self.assertNotEqual(first, second)
        self.assertNotIn("synthetic1", first)
        self.assertTrue(accounts.verify_password("synthetic1", first))
        self.assertFalse(accounts.verify_password("synthetic2", first))

    def test_malformed_hashes_are_rejected(self) -> None:
        for encoded in ("", "plain-text", "md5$1$2$3$4$5", "scrypt$x$y$z"):
            with self.subTest(encoded=encoded):
                self.assertFalse(accounts.verify_password("synthetic1", encoded))


class ValidationTests(unittest.TestCase):
    def test_display_name_is_tidied_and_bounded(self) -> None:
        self.assertEqual(accounts.validate_display_name("  Amina   Demo "), "Amina Demo")
        for bad in ("", "A", "x" * (accounts.MAX_DISPLAY_NAME_LENGTH + 1)):
            with self.subTest(value=bad):
                with self.assertRaises(accounts.AccountError):
                    accounts.validate_display_name(bad)

    def test_email_is_normalised_and_checked(self) -> None:
        self.assertEqual(
            accounts.validate_email("  AMINA@Example.Test "), "amina@example.test"
        )
        for bad in ("", "plain", "a@b", "a b@example.test"):
            with self.subTest(value=bad):
                with self.assertRaises(accounts.AccountError):
                    accounts.validate_email(bad)

    def test_password_needs_length_letter_and_number(self) -> None:
        for bad in ("short1", "onlyletters", "12345678", "x" * 200):
            with self.subTest(value=bad):
                with self.assertRaises(accounts.AccountError):
                    accounts.validate_password(bad)
        self.assertEqual(accounts.validate_password("synthetic1"), "synthetic1")


class AccountStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.store = accounts.AccountStore(self.root / "accounts.db")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_create_and_authenticate_ignores_email_case(self) -> None:
        created = self.store.create_account("Amina Demo", "Amina@Example.test", "synthetic1")
        self.assertEqual(created.email, "amina@example.test")
        found = self.store.authenticate("AMINA@example.test", "synthetic1")
        self.assertIsNotNone(found)
        assert found is not None
        self.assertEqual(found.account_id, created.account_id)
        self.assertEqual(found.display_name, "Amina Demo")
        self.assertIsNone(self.store.authenticate("amina@example.test", "wrongpass1"))
        self.assertIsNone(self.store.authenticate("other@example.test", "synthetic1"))

    def test_duplicate_email_is_refused(self) -> None:
        self.store.create_account("Amina Demo", "amina@example.test", "synthetic1")
        with self.assertRaises(accounts.AccountError):
            self.store.create_account("Other Student", "AMINA@example.test", "synthetic1")

    def test_sessions_lookup_and_delete(self) -> None:
        account = self.store.create_account("Amina Demo", "amina@example.test", "synthetic1")
        token = self.store.create_session(account.account_id)
        self.assertGreaterEqual(len(token), 40)
        found = self.store.account_for_token(token)
        self.assertIsNotNone(found)
        assert found is not None
        self.assertEqual(found.account_id, account.account_id)
        self.assertIsNone(self.store.account_for_token("x" * 43))
        self.assertIsNone(self.store.account_for_token(""))

        self.store.delete_session(token)
        self.assertIsNone(self.store.account_for_token(token))

    def test_expired_sessions_are_not_returned(self) -> None:
        account = self.store.create_account("Amina Demo", "amina@example.test", "synthetic1")
        token = self.store.create_session(account.account_id)
        connection = sqlite3.connect(self.store.path)
        try:
            with connection:
                connection.execute(
                    "UPDATE sessions SET expires_at = '2000-01-01T00:00:00+00:00'"
                )
        finally:
            connection.close()
        self.assertIsNone(self.store.account_for_token(token))


if __name__ == "__main__":
    unittest.main()
