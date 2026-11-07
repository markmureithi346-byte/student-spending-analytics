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
        for bad in ("short1", "ninechar1", "onlyletters", "1234567890", "x" * 200):
            with self.subTest(value=bad):
                with self.assertRaises(accounts.AccountError):
                    accounts.validate_password(bad)
        self.assertEqual(accounts.validate_password("synthetic1"), "synthetic1")
        self.assertEqual(len("synthetic1"), accounts.MIN_PASSWORD_LENGTH)

    def test_recovery_codes_are_grouped_and_uppercase(self) -> None:
        code = accounts.new_recovery_code()
        self.assertRegex(code, r"^[A-Z0-9]{4}(-[A-Z0-9]{4}){3}$")
        self.assertNotEqual(code, accounts.new_recovery_code())


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

    def test_consent_records_the_policy_version(self) -> None:
        created = self.store.create_account(
            "Amina Demo", "amina@example.test", "synthetic1", consented=True
        )
        self.assertIsNotNone(created.consent_at)
        self.assertEqual(created.policy_version, accounts.POLICY_VERSION)

        other = self.store.create_account(
            "Other Student", "other@example.test", "synthetic1"
        )
        self.assertIsNone(other.consent_at)
        self.assertTrue(self.store.set_consent(other.account_id))
        refreshed = self.store.authenticate("other@example.test", "synthetic1")
        assert refreshed is not None
        self.assertIsNotNone(refreshed.consent_at)
        self.assertEqual(refreshed.policy_version, accounts.POLICY_VERSION)

    def test_recovery_code_is_stored_as_a_digest_and_is_single_use(self) -> None:
        account = self.store.create_account(
            "Amina Demo", "amina@example.test", "synthetic1"
        )
        self.assertIsNone(self.store.generate_recovery_code(account.account_id, "wrongpass1"))
        code = self.store.generate_recovery_code(account.account_id, "synthetic1")
        assert code is not None

        connection = sqlite3.connect(self.store.path)
        try:
            stored = connection.execute(
                "SELECT recovery_hash FROM accounts WHERE account_id = ?",
                (account.account_id,),
            ).fetchone()[0]
        finally:
            connection.close()
        self.assertNotIn(code.replace("-", ""), stored)
        self.assertRegex(stored, r"^[0-9a-f]{64}$")

        old_session = self.store.create_session(account.account_id)
        self.assertFalse(
            self.store.reset_password("amina@example.test", "0000-0000-0000-0000", "replacement1")
        )
        self.assertTrue(
            self.store.reset_password("amina@example.test", code, "replacement1")
        )
        self.assertIsNone(self.store.authenticate("amina@example.test", "synthetic1"))
        self.assertIsNotNone(self.store.authenticate("amina@example.test", "replacement1"))
        self.assertIsNone(self.store.account_for_token(old_session))
        self.assertFalse(
            self.store.reset_password("amina@example.test", code, "synthetic1")
        )

    def test_change_password_requires_current_and_ends_sessions(self) -> None:
        account = self.store.create_account(
            "Amina Demo", "amina@example.test", "synthetic1"
        )
        token = self.store.create_session(account.account_id)
        self.assertFalse(
            self.store.change_password(account.account_id, "wrongpass1", "replacement1")
        )
        self.assertIsNotNone(self.store.account_for_token(token))

        self.assertTrue(
            self.store.change_password(account.account_id, "synthetic1", "replacement1")
        )
        self.assertIsNone(self.store.account_for_token(token))
        self.assertIsNone(self.store.authenticate("amina@example.test", "synthetic1"))
        self.assertIsNotNone(self.store.authenticate("amina@example.test", "replacement1"))

    def test_delete_account_removes_sessions_and_the_record(self) -> None:
        account = self.store.create_account(
            "Amina Demo", "amina@example.test", "synthetic1"
        )
        token = self.store.create_session(account.account_id)
        self.assertTrue(self.store.delete_account(account.account_id))
        self.assertIsNone(self.store.account_for_token(token))
        self.assertIsNone(self.store.authenticate("amina@example.test", "synthetic1"))
        self.assertFalse(self.store.delete_account(account.account_id))


if __name__ == "__main__":
    unittest.main()
