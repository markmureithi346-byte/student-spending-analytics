"""Read raw CSV sources and report what was found.

Extraction is deliberately dumb: it does not fix data. It only answers two
questions - can this file be read at all, and which rows are structurally
intact? Business rules live in ``validate``.
"""

from __future__ import annotations

import csv
import logging
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path

from . import config
from .errors import ExtractionError

logger = logging.getLogger(__name__)

TRANSACTION_COLUMNS = (
    "transaction_id",
    "student_id",
    "transaction_date",
    "amount_kes",
    "category",
    "description",
    "payment_method",
    "merchant",
    "is_recurring",
)

PROFILE_COLUMNS = (
    "student_id",
    "profile_label",
    "campus",
    "study_year",
    "monthly_income_kes",
)

BUDGET_COLUMNS = ("student_id", "budget_month", "category", "budget_kes")


@dataclass(frozen=True)
class RawRecord:
    """One physical CSV row, either parsed into fields or marked unparseable."""

    line_number: int
    fields: dict[str, str] | None
    error: str | None = None


def _read_header_row(path: Path, expected: tuple[str, ...]) -> tuple[list[str], list[list[str]]]:
    if not path.exists():
        raise ExtractionError(f"input file not found: {path}")
    if not path.is_file():
        raise ExtractionError(f"input path is not a file: {path}")
    if path.stat().st_size == 0:
        raise ExtractionError(f"input file is empty: {path}")

    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.reader(handle)
        try:
            header = [column.strip() for column in next(reader)]
        except StopIteration:
            raise ExtractionError(f"input file has no header row: {path}") from None
        missing = [column for column in expected if column not in header]
        if missing:
            raise ExtractionError(
                f"{path} is missing required column(s): {', '.join(missing)}"
            )
        body = [row for row in reader]
    return header, body


def extract_transactions(path: Path) -> list[RawRecord]:
    """Return every data row, flagging rows whose field count is wrong."""
    header, body = _read_header_row(path, TRANSACTION_COLUMNS)
    index = {name: header.index(name) for name in TRANSACTION_COLUMNS}

    records: list[RawRecord] = []
    blank_lines = 0
    for line_number, row in enumerate(body, start=2):
        if not row or all(not cell.strip() for cell in row):
            blank_lines += 1
            continue
        if len(row) != len(header):
            records.append(
                RawRecord(
                    line_number=line_number,
                    fields=None,
                    error=(
                        f"expected {len(header)} fields, found {len(row)} "
                        f"(unescaped comma or missing value)"
                    ),
                )
            )
            continue
        records.append(
            RawRecord(
                line_number=line_number,
                fields={name: row[index[name]].strip() for name in TRANSACTION_COLUMNS},
            )
        )

    if not records:
        raise ExtractionError(f"no data rows found in {path}")
    if blank_lines:
        logger.info("ignored %d blank line(s) in %s", blank_lines, path.name)
    logger.info("extracted %d raw row(s) from %s", len(records), path.name)
    return records


def read_profiles(path: Path) -> list[dict[str, object]]:
    """Read the student dimension. Anything invalid fails the whole load."""
    header, body = _read_header_row(path, PROFILE_COLUMNS)
    index = {name: header.index(name) for name in PROFILE_COLUMNS}

    profiles: list[dict[str, object]] = []
    seen: set[str] = set()
    for line_number, row in enumerate(body, start=2):
        if not row or all(not cell.strip() for cell in row):
            continue
        values = {name: row[index[name]].strip() for name in PROFILE_COLUMNS}
        student_id = values["student_id"]
        if not student_id:
            raise ExtractionError(f"{path} line {line_number}: blank student_id")
        if student_id in seen:
            raise ExtractionError(
                f"{path} line {line_number}: duplicate student_id {student_id!r}"
            )
        try:
            study_year = int(values["study_year"])
            income_cents = int(
                (Decimal(values["monthly_income_kes"]) * 100).quantize(Decimal("1"))
            )
        except (ValueError, InvalidOperation):
            raise ExtractionError(
                f"{path} line {line_number}: study_year and monthly_income_kes must be numeric"
            ) from None
        if not 1 <= study_year <= 6:
            raise ExtractionError(
                f"{path} line {line_number}: study_year must be between 1 and 6"
            )
        if income_cents < 0:
            raise ExtractionError(
                f"{path} line {line_number}: monthly_income_kes cannot be negative"
            )
        seen.add(student_id)
        profiles.append(
            {
                "student_id": student_id,
                "profile_label": values["profile_label"] or student_id,
                "campus": values["campus"] or "Unknown",
                "study_year": study_year,
                "monthly_income_cents": income_cents,
            }
        )

    if not profiles:
        raise ExtractionError(f"no student profiles found in {path}")
    logger.info("read %d student profile(s) from %s", len(profiles), path.name)
    return profiles


def derive_profiles(records: list[RawRecord]) -> list[dict[str, object]]:
    """Build the smallest valid student dimension from transaction student IDs.

    A single-file upload has no profile CSV. The transaction row is the source of
    truth for which students exist; descriptive fields are left unknown rather
    than invented. ``study_year`` 0 and income 0 mean "not supplied".
    """
    student_ids: set[str] = set()
    for record in records:
        if record.fields is None:
            continue
        student_id = record.fields.get("student_id", "").strip()
        if student_id:
            student_ids.add(student_id)
    if not student_ids:
        raise ExtractionError("no student_id values found in the transactions file")

    profiles = [
        {
            "student_id": student_id,
            "profile_label": student_id,
            "campus": "Not provided",
            "study_year": 0,
            "monthly_income_cents": 0,
        }
        for student_id in sorted(student_ids)
    ]
    logger.info("derived %d student profile(s) from transaction rows", len(profiles))
    return profiles


def read_budgets(
    path: Path,
    known_students: set[str],
    known_categories: set[str],
) -> tuple[list[dict[str, object]], int]:
    """Read budget targets, skipping rows that reference unknown entities."""
    header, body = _read_header_row(path, BUDGET_COLUMNS)
    index = {name: header.index(name) for name in BUDGET_COLUMNS}

    budgets: list[dict[str, object]] = []
    skipped = 0
    for line_number, row in enumerate(body, start=2):
        if not row or all(not cell.strip() for cell in row):
            continue
        values = {name: row[index[name]].strip() for name in BUDGET_COLUMNS}
        month = values["budget_month"]
        try:
            amount = Decimal(values["budget_kes"])
        except InvalidOperation:
            amount = None
        if (
            len(month) != 7
            or month[4] != "-"
            or not month[:4].isdigit()
            or not month[5:].isdigit()
            or values["student_id"] not in known_students
            or values["category"] not in known_categories
            or amount is None
            or amount < 0
            or not amount.is_finite()
        ):
            skipped += 1
            logger.warning(
                "%s line %d: skipped invalid budget row %r", path.name, line_number, values
            )
            continue
        budgets.append(
            {
                "student_id": values["student_id"],
                "budget_month": month,
                "category": values["category"],
                "budget_cents": int(amount * 100),
            }
        )

    logger.info(
        "read %d budget row(s) from %s (%d skipped)", len(budgets), path.name, skipped
    )
    return budgets, skipped
