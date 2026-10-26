from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from student_spending.errors import ExtractionError
from student_spending.extract import (
    BUDGET_COLUMNS,
    PROFILE_COLUMNS,
    TRANSACTION_COLUMNS,
    extract_transactions,
    read_budgets,
    read_profiles,
)

HEADER = ",".join(TRANSACTION_COLUMNS) + "\n"
GOOD_ROW = "TXN-0001,STU-001,2026-08-10,450.00,Food,Lunch,M-Pesa,Cafeteria,false\n"


class TempFileTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.directory = Path(self._tmp.name)

    def write(self, text: str, name: str = "transactions.csv", encoding: str = "utf-8") -> Path:
        path = self.directory / name
        path.write_text(text, encoding=encoding)
        return path


class ExtractTransactionsTests(TempFileTestCase):
    def test_missing_file_raises(self) -> None:
        with self.assertRaises(ExtractionError):
            extract_transactions(self.directory / "absent.csv")

    def test_empty_file_raises(self) -> None:
        with self.assertRaises(ExtractionError):
            extract_transactions(self.write(""))

    def test_header_only_raises(self) -> None:
        with self.assertRaises(ExtractionError) as context:
            extract_transactions(self.write(HEADER))
        self.assertIn("no data rows", str(context.exception))

    def test_missing_required_column_raises(self) -> None:
        header = HEADER.replace(",merchant", "")
        path = self.write(header + "TXN-1,STU-1,2026-08-10,10.00,Food,Lunch,M-Pesa,false\n")
        with self.assertRaises(ExtractionError) as context:
            extract_transactions(path)
        self.assertIn("merchant", str(context.exception))

    def test_malformed_rows_are_captured_not_fatal(self) -> None:
        path = self.write(
            HEADER
            + GOOD_ROW
            + "TXN-0002,STU-001,2026-08-11,200.00,Food,Lunch, and snacks,M-Pesa,Cafeteria,false\n"
            + "TXN-0003,STU-001,2026-08-12,300.00,Food\n"
        )
        records = extract_transactions(path)
        self.assertEqual(len(records), 3)
        self.assertIsNotNone(records[0].fields)
        self.assertIsNone(records[1].fields)
        self.assertIn("expected 9 fields", records[1].error or "")
        self.assertEqual(records[1].line_number, 3)
        self.assertIsNone(records[2].fields)

    def test_utf8_bom_header_is_tolerated(self) -> None:
        path = self.write(HEADER + GOOD_ROW, encoding="utf-8-sig")
        records = extract_transactions(path)
        self.assertEqual(records[0].fields["transaction_id"], "TXN-0001")

    def test_blank_lines_are_ignored(self) -> None:
        path = self.write(HEADER + GOOD_ROW + "\n\n")
        records = extract_transactions(path)
        self.assertEqual(len(records), 1)

    def test_whitespace_around_values_is_trimmed(self) -> None:
        path = self.write(HEADER + " TXN-0001 , STU-001 ,2026-08-10, 450.00 , Food ,Lunch,M-Pesa,Cafeteria,false\n")
        records = extract_transactions(path)
        self.assertEqual(records[0].fields["student_id"], "STU-001")
        self.assertEqual(records[0].fields["amount_kes"], "450.00")


class DimensionExtractionTests(TempFileTestCase):
    def test_profiles_are_read(self) -> None:
        header = ",".join(PROFILE_COLUMNS) + "\n"
        path = self.write(
            header + "STU-001,Profile A,Main Campus,2,32000\n", name="profiles.csv"
        )
        profiles = read_profiles(path)
        self.assertEqual(profiles[0]["student_id"], "STU-001")
        self.assertEqual(profiles[0]["monthly_income_cents"], 3_200_000)

    def test_duplicate_student_profile_raises(self) -> None:
        header = ",".join(PROFILE_COLUMNS) + "\n"
        path = self.write(
            header
            + "STU-001,Profile A,Main Campus,2,32000\n"
            + "STU-001,Profile B,Main Campus,1,21000\n",
            name="profiles.csv",
        )
        with self.assertRaises(ExtractionError):
            read_profiles(path)

    def test_budgets_skip_unknown_references(self) -> None:
        header = ",".join(BUDGET_COLUMNS) + "\n"
        path = self.write(
            header
            + "STU-001,2026-08,Food,5000\n"
            + "STU-999,2026-08,Food,5000\n"
            + "STU-001,2026-08,Gambling,5000\n",
            name="budgets.csv",
        )
        budgets, skipped = read_budgets(path, {"STU-001"}, {"Food"})
        self.assertEqual(len(budgets), 1)
        self.assertEqual(skipped, 2)
        self.assertEqual(budgets[0]["budget_cents"], 500_000)


if __name__ == "__main__":
    unittest.main()
