from __future__ import annotations

import unittest
from datetime import date

from student_spending.extract import RawRecord
from student_spending.validate import CleanTransaction, validate_records

KNOWN = {"STU-001", "STU-002"}
TODAY = date(2026, 10, 26)

BASE = {
    "transaction_id": "TXN-0001",
    "student_id": "STU-001",
    "transaction_date": "2026-08-10",
    "amount_kes": "450.00",
    "category": "Food",
    "description": "Lunch",
    "payment_method": "M-Pesa",
    "merchant": "Cafeteria",
    "is_recurring": "false",
}


def record(line: int = 2, **overrides: str) -> RawRecord:
    fields = dict(BASE)
    fields.update(overrides)
    return RawRecord(line_number=line, fields=fields)


def validate(*records: RawRecord):
    return validate_records(list(records), KNOWN, today=TODAY)


class RowRuleTests(unittest.TestCase):
    def test_valid_row_is_accepted(self) -> None:
        result = validate(record())
        self.assertEqual(len(result.accepted), 1)
        self.assertEqual(result.accepted[0].amount_cents, 45_000)
        self.assertFalse(result.accepted[0].is_recurring)
        self.assertEqual(result.rejected, [])

    def test_category_case_is_normalised(self) -> None:
        for variant in ("food", "FOOD ", "  Food", "Food"):
            with self.subTest(variant=variant):
                result = validate(record(category=variant))
                self.assertEqual(result.accepted[0].category, "Food")

    def test_category_aliases_are_mapped(self) -> None:
        result = validate(record(category="airtime & internet"))
        self.assertEqual(result.accepted[0].category, "Airtime and Internet")

    def test_unknown_payment_method_falls_back_to_other(self) -> None:
        result = validate(record(payment_method="Crypto Wallet"))
        self.assertEqual(result.accepted[0].payment_method, "Other")
        self.assertTrue(any("payment method" in warning for warning in result.warnings))

    def test_blank_description_and_merchant_are_defaulted(self) -> None:
        result = validate(record(description="", merchant=""))
        self.assertEqual(result.accepted[0].description, "Not provided")
        self.assertEqual(result.accepted[0].merchant, "Not provided")

    def test_recurring_values_are_parsed(self) -> None:
        for raw, expected in (("true", True), ("YES", True), ("1", True), ("no", False), ("", False)):
            with self.subTest(raw=raw):
                result = validate(record(is_recurring=raw))
                self.assertIs(result.accepted[0].is_recurring, expected)

    def test_unrecognised_recurring_value_warns(self) -> None:
        result = validate(record(is_recurring="sometimes"))
        self.assertFalse(result.accepted[0].is_recurring)
        self.assertTrue(any("is_recurring" in warning for warning in result.warnings))


class RejectionRuleTests(unittest.TestCase):
    def assertQuarantined(self, result, code: str) -> None:
        self.assertEqual(result.accepted, [])
        self.assertEqual(len(result.rejected), 1)
        self.assertEqual(result.rejected[0].outcome, "quarantined")
        self.assertEqual(result.rejected[0].reason_code, code)

    def test_malformed_row_is_quarantined(self) -> None:
        result = validate(RawRecord(line_number=5, fields=None, error="expected 9 fields, found 10"))
        self.assertQuarantined(result, "MALFORMED_ROW")

    def test_missing_required_field_is_quarantined(self) -> None:
        result = validate(record(student_id=""))
        self.assertQuarantined(result, "MISSING_REQUIRED_FIELD")

    def test_unknown_student_is_quarantined(self) -> None:
        result = validate(record(student_id="STU-999"))
        self.assertQuarantined(result, "UNKNOWN_STUDENT")

    def test_invalid_dates_are_quarantined(self) -> None:
        for value in ("05/08/2026", "2026-13-05", "2026-02-30", "not-a-date"):
            with self.subTest(value=value):
                result = validate(record(transaction_date=value))
                self.assertEqual(result.rejected[0].reason_code, "INVALID_DATE")

    def test_future_date_is_quarantined(self) -> None:
        result = validate(record(transaction_date="2027-01-15"))
        self.assertQuarantined(result, "DATE_IN_FUTURE")

    def test_non_positive_amount_is_quarantined(self) -> None:
        for value in ("0", "0.00", "-250.00"):
            with self.subTest(value=value):
                result = validate(record(amount_kes=value))
                self.assertEqual(result.rejected[0].reason_code, "NON_POSITIVE_AMOUNT")

    def test_non_numeric_amount_is_quarantined(self) -> None:
        result = validate(record(amount_kes="twelve hundred"))
        self.assertQuarantined(result, "INVALID_AMOUNT")

    def test_amount_above_sanity_limit_is_quarantined(self) -> None:
        result = validate(record(amount_kes="250000.00"))
        self.assertQuarantined(result, "AMOUNT_OUT_OF_RANGE")

    def test_unexpected_category_is_quarantined(self) -> None:
        result = validate(record(category="Gambling"))
        self.assertQuarantined(result, "UNEXPECTED_CATEGORY")

    def test_thousands_separator_and_currency_prefix_are_accepted(self) -> None:
        result = validate(record(amount_kes="KES 1,200.50"))
        self.assertEqual(result.accepted[0].amount_cents, 120_050)


class DuplicateRuleTests(unittest.TestCase):
    def test_identical_duplicate_keeps_first_and_rejects_copy(self) -> None:
        result = validate(record(line=2), record(line=9))
        self.assertEqual(len(result.accepted), 1)
        self.assertEqual(result.accepted[0].source_line, 2)
        self.assertEqual(len(result.rejected), 1)
        self.assertEqual(result.rejected[0].outcome, "rejected")
        self.assertEqual(result.rejected[0].reason_code, "DUPLICATE_IDENTICAL")

    def test_conflicting_duplicate_quarantines_every_copy(self) -> None:
        result = validate(record(line=3, amount_kes="450.00"), record(line=7, amount_kes="900.00"))
        self.assertEqual(result.accepted, [])
        self.assertEqual(len(result.rejected), 2)
        self.assertTrue(all(item.outcome == "quarantined" for item in result.rejected))
        self.assertTrue(all(item.reason_code == "DUPLICATE_CONFLICT" for item in result.rejected))

    def test_whitespace_difference_is_not_a_conflict(self) -> None:
        result = validate(record(line=2), record(line=5, description=" Lunch "))
        self.assertEqual(len(result.accepted), 1)
        self.assertEqual(result.rejected[0].reason_code, "DUPLICATE_IDENTICAL")


class AccountingTests(unittest.TestCase):
    def test_every_row_is_classified_exactly_once(self) -> None:
        records = [
            record(line=2),
            record(line=3, transaction_id="TXN-0002"),
            record(line=4, transaction_id="TXN-0003", amount_kes="0"),
            record(line=5, transaction_id="TXN-0004", category="Gambling"),
            RawRecord(line_number=6, fields=None, error="expected 9 fields, found 6"),
            record(line=7, transaction_id="TXN-0002"),
        ]
        result = validate(*records)
        self.assertEqual(result.rows_read, len(records))
        self.assertEqual(
            result.rows_read,
            len(result.accepted) + result.rejected_count + result.quarantined_count,
        )
        self.assertEqual(len(result.accepted), 2)
        self.assertEqual(result.quarantined_count, 3)
        self.assertEqual(result.rejected_count, 1)

    def test_accepted_records_carry_typed_values(self) -> None:
        result = validate(record(amount_kes="1200.555"))
        self.assertIsInstance(result.accepted[0], CleanTransaction)
        self.assertEqual(result.accepted[0].amount_cents, 120_056)


if __name__ == "__main__":
    unittest.main()
