"""Collect one student's money plan and compare it with their own spending.

The form is turned into integer cents before anything is calculated. Categories
are free text chosen by the student, spending entries must reference one of
those categories, and every amount is bounded. Nothing connects to a bank, card
or payment account: the analysis only compares numbers the student typed, and
the result is rendered in the response rather than written to disk.

Money is parsed into cents to match the pipeline's integers and to avoid binary
floating-point drift in the comparison figures.
"""

from __future__ import annotations

import re
import urllib.parse
from dataclasses import dataclass
from datetime import datetime

from . import config

MAX_NAME_LENGTH = 60
MAX_METHOD_NOTE_LENGTH = 300
MAX_CATEGORY_NAME_LENGTH = 32
MAX_ENTRY_NOTE_LENGTH = 120
MAX_CATEGORIES = 100
MAX_SPENDINGS = 100
CATEGORY_ROWS = 1
SPENDING_ROWS = 1
MAX_PLANNED_CENTS = 100_000_000  # KES 1,000,000.00 per category
MAX_SPENDING_CENTS = config.MAX_TRANSACTION_AMOUNT_CENTS
MAX_PLAN_REQUEST_BYTES = 256 * 1024
# Covers the largest allowed form: 100 category rows and 100 spending rows.
MAX_FORM_FIELDS = 800

_ROW_KEY_PATTERN = re.compile(r"^(?:category|spending)_[a-z]+_(\d+)$")
_AMOUNT_PATTERN = re.compile(
    r"^(?:kes|ksh)?\s*(?P<whole>\d{1,3}(?:,\d{3})*|\d+)(?:\.(?P<fraction>\d{1,2}))?$",
    re.IGNORECASE,
)
_METHOD_KEYS = (
    "none",
    "fifty_thirty_twenty",
    "zero_based",
    "envelope",
    "pay_yourself_first",
    "custom",
)
BUDGET_METHODS: dict[str, str] = {
    "none": "No formal method yet",
    "fifty_thirty_twenty": "50/30/20 split",
    "zero_based": "Zero-based budget",
    "envelope": "Envelope budget",
    "pay_yourself_first": "Pay yourself first",
    "custom": "My own method",
}
PERIODS: dict[str, str] = {
    "monthly": "Monthly",
    "weekly": "Weekly",
}
PERIOD_NOUNS: dict[str, str] = {
    "monthly": "month",
    "weekly": "week",
}


class PlanRequestError(ValueError):
    """A user-correctable problem with the plan request itself."""

    def __init__(self, message: str, *, status: int = 400):
        super().__init__(message)
        self.status = status


@dataclass(frozen=True)
class CategoryDraft:
    name: str = ""
    planned: str = ""
    essential: bool = False


@dataclass(frozen=True)
class SpendingDraft:
    category: str = ""
    amount: str = ""
    note: str = ""


@dataclass(frozen=True)
class PlanDraft:
    student_name: str = ""
    money_available: str = ""
    period: str = "monthly"
    method: str = "none"
    method_note: str = ""
    categories: tuple[CategoryDraft, ...] = ()
    spendings: tuple[SpendingDraft, ...] = ()
    advice_ack: bool = False

    def category(self, number: int) -> CategoryDraft:
        return (
            self.categories[number - 1]
            if 0 < number <= len(self.categories)
            else CategoryDraft()
        )

    def spending(self, number: int) -> SpendingDraft:
        return (
            self.spendings[number - 1]
            if 0 < number <= len(self.spendings)
            else SpendingDraft()
        )


@dataclass(frozen=True)
class CategoryPlan:
    name: str
    planned_cents: int
    essential: bool


@dataclass(frozen=True)
class SpendingEntry:
    category: str
    amount_cents: int
    note: str


@dataclass(frozen=True)
class MoneyPlan:
    student_name: str
    money_available_cents: int
    method: str
    method_note: str
    categories: tuple[CategoryPlan, ...]
    spendings: tuple[SpendingEntry, ...]
    period: str = "monthly"

    @property
    def period_label(self) -> str:
        return PERIODS.get(self.period, PERIODS["monthly"])

    @property
    def period_noun(self) -> str:
        return PERIOD_NOUNS.get(self.period, PERIOD_NOUNS["monthly"])



@dataclass(frozen=True)
class CategoryResult:
    name: str
    essential: bool
    planned_cents: int
    spent_cents: int
    difference_cents: int
    share_pct: float
    entry_count: int
    status: str

    @property
    def flagged(self) -> bool:
        return self.spent_cents > self.planned_cents


@dataclass(frozen=True)
class PlanAnalysis:
    money_available_cents: int
    planned_cents: int
    spent_cents: int
    remaining_cents: int
    unallocated_cents: int
    spent_share_pct: float
    planned_share_pct: float
    essential_planned_cents: int
    flexible_planned_cents: int
    essential_spent_cents: int
    flexible_spent_cents: int
    essential_share_pct: float
    recorded_at: datetime
    average_entry_cents: float
    categories: tuple[CategoryResult, ...]
    ranked_categories: tuple[CategoryResult, ...]
    over_plan: tuple[CategoryResult, ...]
    unplanned: tuple[CategoryResult, ...]
    near_plan: tuple[CategoryResult, ...] = ()


def parse_amount(raw: str) -> int | None:
    """Parse ``2,500``, ``2 500`` or ``KES 2500.50`` into integer cents."""
    text = raw.strip().replace(" ", "")
    match = _AMOUNT_PATTERN.fullmatch(text)
    if not match:
        return None
    whole = match.group("whole").replace(",", "")
    if len(whole) > 15:
        return None
    fraction = (match.group("fraction") or "").ljust(2, "0")[:2]
    return int(whole) * 100 + int(fraction)


def parse_form(
    content_type: str, body: bytes
) -> dict[str, list[str]]:
    """Decode an ``application/x-www-form-urlencoded`` plan submission."""
    media_type = content_type.split(";", 1)[0].strip().lower()
    if media_type != "application/x-www-form-urlencoded":
        raise PlanRequestError(
            "The money plan must be submitted from its own form.", status=415
        )
    if not body:
        raise PlanRequestError("The plan form was empty.")
    if len(body) > MAX_PLAN_REQUEST_BYTES:
        raise PlanRequestError(
            f"The plan form is larger than {MAX_PLAN_REQUEST_BYTES // 1024} KB.",
            status=413,
        )
    try:
        text = body.decode("utf-8")
    except UnicodeDecodeError:
        raise PlanRequestError("The plan form must be UTF-8 text.") from None
    try:
        return urllib.parse.parse_qs(
            text, keep_blank_values=True, max_num_fields=MAX_FORM_FIELDS
        )
    except ValueError:
        raise PlanRequestError("The plan form has too many fields.") from None


def read_draft(
    form: dict[str, list[str]],
    *,
    category_rows: int = CATEGORY_ROWS,
    spending_rows: int = SPENDING_ROWS,
) -> PlanDraft:
    """Collect raw values so a rejected form can be shown again unchanged."""
    category_numbers = _row_numbers(form, "category", MAX_CATEGORIES, category_rows)
    spending_numbers = _row_numbers(form, "spending", MAX_SPENDINGS, spending_rows)
    return PlanDraft(
        student_name=_first(form, "student_name"),
        money_available=_first(form, "money_available"),
        period=_first(form, "period") or "monthly",
        method=_first(form, "method") or "none",
        method_note=_first(form, "method_note"),
        categories=tuple(
            CategoryDraft(
                name=_first(form, f"category_name_{number}"),
                planned=_first(form, f"category_amount_{number}"),
                essential=_first(form, f"category_essential_{number}").lower()
                in {"essential", "yes", "on", "true"},
            )
            for number in category_numbers
        ),
        spendings=tuple(
            SpendingDraft(
                category=_first(form, f"spending_category_{number}"),
                amount=_first(form, f"spending_amount_{number}"),
                note=_first(form, f"spending_note_{number}"),
            )
            for number in spending_numbers
        ),
        advice_ack=_first(form, "advice_ack").lower() in {"yes", "on", "true", "1"},
    )


def validate_draft(draft: PlanDraft) -> tuple[MoneyPlan | None, list[str]]:
    """Turn a draft into a typed plan, or explain every problem that blocks it."""
    errors: list[str] = []

    student_name = _clean_spaces(draft.student_name)
    if not student_name:
        errors.append("Add a display name (a nickname is fine).")
    elif len(student_name) > MAX_NAME_LENGTH:
        errors.append(
            f"The display name must be {MAX_NAME_LENGTH} characters or fewer."
        )
    elif not _printable(student_name):
        errors.append("The display name contains characters that cannot be stored.")

    money_available, error = _read_amount(
        draft.money_available, "the money available", MAX_PLANNED_CENTS
    )
    if error:
        errors.append(error)

    if draft.period not in PERIODS:
        errors.append("Choose whether the money is for a month or a week.")
        period = "monthly"
    else:
        period = draft.period

    if draft.method not in BUDGET_METHODS:
        errors.append("Choose a budgeting method from the list.")
        method = "none"
    else:
        method = draft.method

    method_note = _clean_spaces(draft.method_note)
    if len(method_note) > MAX_METHOD_NOTE_LENGTH:
        errors.append(
            "The budgeting note must be "
            f"{MAX_METHOD_NOTE_LENGTH} characters or fewer."
        )
    elif not _printable(method_note):
        errors.append("The budgeting note contains characters that cannot be stored.")

    categories: list[CategoryPlan] = []
    seen: set[str] = set()
    for number, row in enumerate(draft.categories, start=1):
        name = _clean_spaces(row.name)
        raw_planned = row.planned.strip()
        if not name and not raw_planned:
            if row.essential:
                errors.append(
                    f"Category row {number} is marked essential but has no name."
                )
            continue
        if not name:
            errors.append(f"Category row {number} needs a name.")
            continue
        if len(name) > MAX_CATEGORY_NAME_LENGTH:
            errors.append(
                f"Category {name!r} is too long; use "
                f"{MAX_CATEGORY_NAME_LENGTH} characters or fewer."
            )
            continue
        if not _printable(name):
            errors.append(f"Category {name!r} contains characters that cannot be stored.")
            continue
        key = name.casefold()
        if key in seen:
            errors.append(f"Category {name!r} appears more than once; use one row per category.")
            continue
        planned_cents, error = _read_amount(
            row.planned,
            f"the planned amount for {name}",
            MAX_PLANNED_CENTS,
            required=False,
            allow_zero=True,
        )
        if error:
            errors.append(error)
            continue
        seen.add(key)
        categories.append(CategoryPlan(name, planned_cents, row.essential))

    if len(categories) < 2:
        errors.append("Add at least two categories with names.")
    elif len(categories) > MAX_CATEGORIES:
        errors.append(f"Use no more than {MAX_CATEGORIES} categories.")

    known_categories = {category.name.casefold(): category.name for category in categories}
    spendings: list[SpendingEntry] = []
    used_rows = 0
    for number, row in enumerate(draft.spendings, start=1):
        if not any(
            value.strip()
            for value in (row.category, row.amount, row.note)
        ):
            continue
        used_rows += 1

        category = known_categories.get(_clean_spaces(row.category).casefold())
        if not _clean_spaces(row.category):
            errors.append(f"Spending row {number} needs one of your category names.")
        elif category is None:
            errors.append(
                f"Spending row {number} uses {row.category.strip()!r}, "
                "which is not one of your categories."
            )

        amount_cents, error = _read_amount(
            row.amount, f"the amount in spending row {number}", MAX_SPENDING_CENTS
        )
        if error:
            errors.append(error)

        note = _clean_spaces(row.note)
        if len(note) > MAX_ENTRY_NOTE_LENGTH:
            errors.append(
                f"The note in spending row {number} must be "
                f"{MAX_ENTRY_NOTE_LENGTH} characters or fewer."
            )
        elif not _printable(note):
            errors.append(
                f"The note in spending row {number} contains characters that cannot be stored."
            )

        if category is not None and amount_cents is not None:
            spendings.append(SpendingEntry(category, amount_cents, note))

    if not used_rows:
        errors.append("Add at least one spending entry with a category and amount.")
    elif len(spendings) > MAX_SPENDINGS:
        errors.append(f"Use no more than {MAX_SPENDINGS} spending entries.")

    if not draft.advice_ack:
        errors.append(
            "Confirm that you understand Plan It is a planning tool, not "
            "financial advice, before running the analysis."
        )

    if errors:
        return None, errors
    assert money_available is not None
    return (
        MoneyPlan(
            student_name=student_name,
            money_available_cents=money_available,
            method=method,
            method_note=method_note,
            categories=tuple(categories),
            spendings=tuple(spendings),
            period=period,
        ),
        [],
    )


def analyse(plan: MoneyPlan, *, recorded_at: datetime) -> PlanAnalysis:
    """Calculate the comparison from the plan and the submission time.

    ``recorded_at`` must be timezone-aware local time; the caller reads it from
    the device clock so the receipt can say when the analysis was run.
    """
    planned_cents = sum(category.planned_cents for category in plan.categories)
    spent_cents = sum(entry.amount_cents for entry in plan.spendings)

    spent_by_category: dict[str, int] = {}
    count_by_category: dict[str, int] = {}
    for entry in plan.spendings:
        key = entry.category.casefold()
        spent_by_category[key] = spent_by_category.get(key, 0) + entry.amount_cents
        count_by_category[key] = count_by_category.get(key, 0) + 1

    categories: list[CategoryResult] = []
    for category in plan.categories:
        key = category.name.casefold()
        spent = spent_by_category.get(key, 0)
        difference = category.planned_cents - spent
        if category.planned_cents == 0 and spent == 0:
            status = "No activity"
        elif category.planned_cents == 0:
            status = "No plan"
        elif spent > category.planned_cents:
            status = "Over plan"
        elif spent == category.planned_cents:
            status = "On plan"
        elif spent == 0:
            status = "Not used"
        else:
            status = "Under plan"
        categories.append(
            CategoryResult(
                name=category.name,
                essential=category.essential,
                planned_cents=category.planned_cents,
                spent_cents=spent,
                difference_cents=difference,
                share_pct=(100.0 * spent / spent_cents) if spent_cents else 0.0,
                entry_count=count_by_category.get(key, 0),
                status=status,
            )
        )

    ranked = sorted(
        categories,
        key=lambda item: (-item.spent_cents, -item.planned_cents, item.name.casefold()),
    )
    over_plan = tuple(
        item for item in ranked if item.planned_cents > 0 and item.spent_cents > item.planned_cents
    )
    unplanned = tuple(
        item for item in ranked if item.planned_cents == 0 and item.spent_cents > 0
    )
    near_plan = tuple(
        item
        for item in ranked
        if item.planned_cents > 0
        and 0 < item.spent_cents < item.planned_cents
        and item.spent_cents * 100 >= item.planned_cents * 80
    )

    essential_planned = sum(item.planned_cents for item in categories if item.essential)
    flexible_planned = planned_cents - essential_planned
    essential_spent = sum(item.spent_cents for item in categories if item.essential)
    flexible_spent = spent_cents - essential_spent

    entry_count = len(plan.spendings)
    return PlanAnalysis(
        money_available_cents=plan.money_available_cents,
        planned_cents=planned_cents,
        spent_cents=spent_cents,
        remaining_cents=plan.money_available_cents - spent_cents,
        unallocated_cents=plan.money_available_cents - planned_cents,
        spent_share_pct=100.0 * spent_cents / plan.money_available_cents,
        planned_share_pct=100.0 * planned_cents / plan.money_available_cents,
        essential_planned_cents=essential_planned,
        flexible_planned_cents=flexible_planned,
        essential_spent_cents=essential_spent,
        flexible_spent_cents=flexible_spent,
        essential_share_pct=(100.0 * essential_spent / spent_cents) if spent_cents else 0.0,
        recorded_at=recorded_at,
        average_entry_cents=(spent_cents / entry_count) if entry_count else 0.0,
        categories=tuple(categories),
        ranked_categories=tuple(ranked),
        over_plan=over_plan,
        unplanned=unplanned,
        near_plan=near_plan,
    )


def _read_amount(
    raw: str,
    label: str,
    maximum: int,
    *,
    required: bool = True,
    allow_zero: bool = False,
) -> tuple[int | None, str]:
    text = raw.strip()
    if not text:
        if not required:
            return 0, ""
        return None, f"Enter {label}."
    cents = parse_amount(text)
    capitalised = label[:1].upper() + label[1:]
    if cents is None:
        return None, (
            f"{capitalised} must be a number such as 2,500 or 2,500.50."
        )
    if cents > maximum:
        return None, (
            f"{capitalised} cannot be more than KES {maximum / 100:,.2f}."
        )
    if cents == 0 and not allow_zero:
        return None, f"{capitalised} must be more than zero."
    return cents, ""


def _first(form: dict[str, list[str]], key: str) -> str:
    values = form.get(key)
    return values[0] if values else ""


def _clean_spaces(value: str) -> str:
    return " ".join(value.split())


def _printable(value: str) -> bool:
    return all(character.isprintable() for character in value)


def _row_numbers(
    form: dict[str, list[str]], prefix: str, limit: int, default_rows: int
) -> list[int]:
    numbers = {
        int(match.group(1))
        for key in form
        if (match := _ROW_KEY_PATTERN.fullmatch(key))
        and key.startswith(f"{prefix}_")
        and 1 <= int(match.group(1)) <= limit
    }
    return sorted(numbers) if numbers else list(range(1, default_rows + 1))
