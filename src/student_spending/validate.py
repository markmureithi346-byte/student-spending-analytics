"""Validate, normalize and deduplicate extracted records.

Policy (documented in README and docs/DATA_QUALITY.md):

* every physical row ends up in exactly one of: accepted, rejected, quarantined
* rows that cannot be safely fixed are quarantined, never silently dropped
* duplicate transaction_id with identical content -> keep first, reject the rest
* duplicate transaction_id with conflicting content -> quarantine every copy,
  because there is no evidence which version is correct
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from . import config
from .extract import RawRecord

logger = logging.getLogger(__name__)

REQUIRED_FIELDS = ("transaction_id", "student_id", "transaction_date", "amount_kes", "category")
NOT_PROVIDED = "Not provided"
TRUE_VALUES = {"true", "yes", "y", "1"}
FALSE_VALUES = {"false", "no", "n", "0", ""}


@dataclass(frozen=True)
class CleanTransaction:
    transaction_id: str
    student_id: str
    transaction_date: str
    amount_cents: int
    category: str
    description: str
    payment_method: str
    merchant: str
    is_recurring: bool
    source_line: int

    def content_signature(self) -> tuple[object, ...]:
        return (
            self.transaction_id,
            self.student_id,
            self.transaction_date,
            self.amount_cents,
            self.category,
            self.description,
            self.payment_method,
            self.merchant,
            self.is_recurring,
        )


@dataclass(frozen=True)
class RejectedRecord:
    source_line: int
    transaction_id: str | None
    student_id: str | None
    outcome: str  # "rejected" or "quarantined"
    reason_code: str
    reason_detail: str
    raw_payload: dict[str, str] | None


@dataclass
class ValidationResult:
    accepted: list[CleanTransaction]
    rejected: list[RejectedRecord]
    warnings: list[str]

    @property
    def rejected_count(self) -> int:
        return sum(1 for record in self.rejected if record.outcome == "rejected")

    @property
    def quarantined_count(self) -> int:
        return sum(1 for record in self.rejected if record.outcome == "quarantined")

    @property
    def rows_read(self) -> int:
        return len(self.accepted) + len(self.rejected)


def _parse_amount(raw: str) -> tuple[int | None, str | None]:
    text = raw.strip().replace(",", "").replace(" ", "")
    if text.upper().startswith("KES"):
        text = text[3:]
    try:
        value = Decimal(text)
    except InvalidOperation:
        return None, f"{raw!r} is not a numeric amount"
    if not value.is_finite():
        return None, f"{raw!r} is not a finite amount"
    cents = int((value * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    return cents, None


def _parse_bool(raw: str, line: int, warnings: list[str]) -> bool:
    text = raw.strip().lower()
    if text in TRUE_VALUES:
        return True
    if text in FALSE_VALUES:
        return False
    warnings.append(f"line {line}: unrecognised is_recurring value {raw!r}, stored as False")
    return False


def _reject(
    record: RawRecord,
    code: str,
    detail: str,
    outcome: str = "quarantined",
) -> RejectedRecord:
    fields = record.fields or {}
    return RejectedRecord(
        source_line=record.line_number,
        transaction_id=fields.get("transaction_id") or None,
        student_id=fields.get("student_id") or None,
        outcome=outcome,
        reason_code=code,
        reason_detail=detail,
        raw_payload=record.fields,
    )


def _validate_one(
    record: RawRecord,
    known_students: set[str],
    today: date,
    warnings: list[str],
) -> CleanTransaction | RejectedRecord:
    if record.fields is None:
        return _reject(record, "MALFORMED_ROW", record.error or "row could not be parsed")

    fields = record.fields
    line = record.line_number

    missing = [name for name in REQUIRED_FIELDS if not fields.get(name, "").strip()]
    if missing:
        return _reject(
            record, "MISSING_REQUIRED_FIELD", "blank required field(s): " + ", ".join(missing)
        )

    transaction_id = fields["transaction_id"]
    if len(transaction_id) > 64:
        return _reject(record, "INVALID_TRANSACTION_ID", "transaction_id exceeds 64 characters")

    student_id = fields["student_id"]
    if student_id not in known_students:
        return _reject(
            record,
            "UNKNOWN_STUDENT",
            f"student_id {student_id!r} has no row in the student profile dimension",
        )

    try:
        parsed_date = date.fromisoformat(fields["transaction_date"])
    except ValueError:
        return _reject(
            record,
            "INVALID_DATE",
            f"{fields['transaction_date']!r} is not a valid YYYY-MM-DD date",
        )
    if parsed_date < config.MIN_TRANSACTION_DATE:
        return _reject(
            record,
            "DATE_OUT_OF_RANGE",
            f"{parsed_date.isoformat()} is before {config.MIN_TRANSACTION_DATE.isoformat()}",
        )
    if parsed_date > today:
        return _reject(
            record, "DATE_IN_FUTURE", f"{parsed_date.isoformat()} is after today ({today.isoformat()})"
        )

    amount_cents, amount_error = _parse_amount(fields["amount_kes"])
    if amount_error is not None:
        return _reject(record, "INVALID_AMOUNT", amount_error)
    if amount_cents is not None and amount_cents <= 0:
        return _reject(
            record, "NON_POSITIVE_AMOUNT", f"amount {fields['amount_kes']!r} must be greater than 0"
        )
    if amount_cents is not None and amount_cents > config.MAX_TRANSACTION_AMOUNT_CENTS:
        return _reject(
            record,
            "AMOUNT_OUT_OF_RANGE",
            f"amount {fields['amount_kes']!r} exceeds the KES 100,000 sanity limit",
        )

    category = config.CATEGORY_ALIASES.get(fields["category"].strip().lower())
    if category is None:
        return _reject(
            record,
            "UNEXPECTED_CATEGORY",
            f"{fields['category']!r} is not one of the {len(config.ALLOWED_CATEGORIES)} allowed categories",
        )

    raw_payment = fields["payment_method"].strip()
    payment_method = config.PAYMENT_METHOD_ALIASES.get(raw_payment.lower())
    if payment_method is None:
        payment_method = config.DEFAULT_PAYMENT_METHOD
        warnings.append(
            f"line {line}: unknown payment method {raw_payment!r} stored as {payment_method!r}"
        )

    description = fields["description"].strip() or NOT_PROVIDED
    merchant = fields["merchant"].strip() or NOT_PROVIDED
    if description == NOT_PROVIDED:
        warnings.append(f"line {line}: missing description stored as {NOT_PROVIDED!r}")
    if merchant == NOT_PROVIDED:
        warnings.append(f"line {line}: missing merchant stored as {NOT_PROVIDED!r}")

    is_recurring = _parse_bool(fields["is_recurring"], line, warnings)

    return CleanTransaction(
        transaction_id=transaction_id,
        student_id=student_id,
        transaction_date=parsed_date.isoformat(),
        amount_cents=amount_cents or 0,
        category=category,
        description=description,
        payment_method=payment_method,
        merchant=merchant,
        is_recurring=is_recurring,
        source_line=line,
    )


def _resolve_duplicates(
    accepted: list[CleanTransaction],
) -> tuple[list[CleanTransaction], list[RejectedRecord]]:
    groups: dict[str, list[CleanTransaction]] = {}
    for transaction in accepted:
        groups.setdefault(transaction.transaction_id, []).append(transaction)

    kept: list[CleanTransaction] = []
    rejections: list[RejectedRecord] = []
    for transaction_id in sorted(groups):
        group = sorted(groups[transaction_id], key=lambda item: item.source_line)
        if len(group) == 1:
            kept.append(group[0])
            continue
        signatures = {transaction.content_signature() for transaction in group}
        if len(signatures) == 1:
            kept.append(group[0])
            for duplicate in group[1:]:
                rejections.append(
                    RejectedRecord(
                        source_line=duplicate.source_line,
                        transaction_id=duplicate.transaction_id,
                        student_id=duplicate.student_id,
                        outcome="rejected",
                        reason_code="DUPLICATE_IDENTICAL",
                        reason_detail=(
                            f"identical copy of line {group[0].source_line}; kept the first occurrence"
                        ),
                        raw_payload=None,
                    )
                )
        else:
            for duplicate in group:
                rejections.append(
                    RejectedRecord(
                        source_line=duplicate.source_line,
                        transaction_id=duplicate.transaction_id,
                        student_id=duplicate.student_id,
                        outcome="quarantined",
                        reason_code="DUPLICATE_CONFLICT",
                        reason_detail=(
                            f"{len(group)} rows share transaction_id {transaction_id!r} "
                            "with different content; all copies held for review"
                        ),
                        raw_payload=None,
                    )
                )
    return kept, rejections


def validate_records(
    records: list[RawRecord],
    known_students: set[str],
    today: date | None = None,
) -> ValidationResult:
    """Apply row rules, then duplicate rules, then account for every row."""
    today = today or date.today()
    warnings: list[str] = []
    accepted: list[CleanTransaction] = []
    rejected: list[RejectedRecord] = []

    for record in records:
        outcome = _validate_one(record, known_students, today, warnings)
        if isinstance(outcome, CleanTransaction):
            accepted.append(outcome)
        else:
            rejected.append(outcome)

    accepted, duplicate_rejections = _resolve_duplicates(accepted)
    rejected.extend(duplicate_rejections)

    result = ValidationResult(
        accepted=sorted(accepted, key=lambda transaction: transaction.source_line),
        rejected=sorted(rejected, key=lambda record: record.source_line),
        warnings=warnings,
    )
    logger.info(
        "validation: accepted=%d rejected=%d quarantined=%d warnings=%d",
        len(result.accepted),
        result.rejected_count,
        result.quarantined_count,
        len(warnings),
    )
    return result
