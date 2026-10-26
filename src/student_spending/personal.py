"""Collect one student's money plan and compare it with their own spending.

The form is turned into integer cents before anything is stored or calculated.
Categories are free text chosen by the student, spending entries must reference
one of those categories, and every amount is bounded. Nothing connects to a
bank, card or payment account: the analysis only compares numbers the student
typed, and saved plans stay as JSON under ``data/plans/`` on this machine.

Money is stored in cents to match the pipeline's integers and to avoid binary
floating-point drift in the comparison figures.
"""

from __future__ import annotations

import json
import re
import secrets
import urllib.parse
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from . import config

MAX_NAME_LENGTH = 60
MAX_METHOD_NOTE_LENGTH = 300
MAX_CATEGORY_NAME_LENGTH = 32
MAX_ENTRY_NOTE_LENGTH = 120
MAX_CATEGORIES = 12
MAX_SPENDINGS = 24
CATEGORY_ROWS = 12
SPENDING_ROWS = 24
MAX_PLANNED_CENTS = 100_000_000  # KES 1,000,000.00 per category
MAX_SPENDING_CENTS = config.MAX_TRANSACTION_AMOUNT_CENTS
MAX_PLAN_REQUEST_BYTES = 256 * 1024
MAX_FORM_FIELDS = 250
MAX_SAVED_PLAN_BYTES = 256 * 1024

PLAN_ID_PATTERN = re.compile(r"^p-[A-Za-z0-9_-]{16}$")
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
    spent_on: str = ""
    category: str = ""
    amount: str = ""
    note: str = ""


@dataclass(frozen=True)
class PlanDraft:
    student_name: str = ""
    money_available: str = ""
    method: str = "none"
    method_note: str = ""
    categories: tuple[CategoryDraft, ...] = ()
    spendings: tuple[SpendingDraft, ...] = ()
    synthetic: bool = False

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
    spent_on: date
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


@dataclass(frozen=True)
class SavedPlan:
    plan_id: str
    created_at: str
    plan: MoneyPlan


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
    first_date: date
    last_date: date
    days_covered: int
    active_days: int
    average_daily_cents: float
    categories: tuple[CategoryResult, ...]
    ranked_categories: tuple[CategoryResult, ...]
    over_plan: tuple[CategoryResult, ...]
    unplanned: tuple[CategoryResult, ...]


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
                spent_on=_first(form, f"spending_date_{number}"),
                category=_first(form, f"spending_category_{number}"),
                amount=_first(form, f"spending_amount_{number}"),
                note=_first(form, f"spending_note_{number}"),
            )
            for number in spending_numbers
        ),
        synthetic=_first(form, "synthetic").lower() in {"yes", "on", "true", "1"},
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
            for value in (row.spent_on, row.category, row.amount, row.note)
        ):
            continue
        used_rows += 1

        spent_on: date | None = None
        raw_date = row.spent_on.strip()
        if not raw_date:
            errors.append(f"Spending row {number} needs a date.")
        else:
            try:
                spent_on = date.fromisoformat(raw_date)
            except ValueError:
                errors.append(f"Spending row {number} needs a real date in YYYY-MM-DD form.")

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

        if spent_on is not None and category is not None and amount_cents is not None:
            spendings.append(SpendingEntry(spent_on, category, amount_cents, note))

    if not used_rows:
        errors.append("Add at least one spending entry with a date, category and amount.")
    elif len(spendings) > MAX_SPENDINGS:
        errors.append(f"Use no more than {MAX_SPENDINGS} spending entries.")

    if not draft.synthetic:
        errors.append(
            "Confirm that the numbers are made up before running the analysis."
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
        ),
        [],
    )


def analyse(plan: MoneyPlan) -> PlanAnalysis:
    """Calculate the comparison entirely from the validated plan values."""
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

    essential_planned = sum(item.planned_cents for item in categories if item.essential)
    flexible_planned = planned_cents - essential_planned
    essential_spent = sum(item.spent_cents for item in categories if item.essential)
    flexible_spent = spent_cents - essential_spent

    dates = sorted(entry.spent_on for entry in plan.spendings)
    first_date = dates[0]
    last_date = dates[-1]
    days_covered = (last_date - first_date).days + 1
    active_days = len(set(dates))

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
        first_date=first_date,
        last_date=last_date,
        days_covered=days_covered,
        active_days=active_days,
        average_daily_cents=spent_cents / days_covered,
        categories=tuple(categories),
        ranked_categories=tuple(ranked),
        over_plan=over_plan,
        unplanned=unplanned,
    )


def new_plan_id() -> str:
    return "p-" + secrets.token_urlsafe(12)


def is_valid_plan_id(value: str) -> bool:
    return bool(PLAN_ID_PATTERN.fullmatch(value))


def save_plan(plan: MoneyPlan) -> SavedPlan:
    """Write one plan atomically and return the unguessable id for its page."""
    plan_id = new_plan_id()
    created_at = config.utc_now()
    payload = {
        "version": 1,
        "plan_id": plan_id,
        "created_at": created_at,
        "student_name": plan.student_name,
        "money_available_cents": plan.money_available_cents,
        "method": plan.method,
        "method_note": plan.method_note,
        "categories": [
            {
                "name": category.name,
                "planned_cents": category.planned_cents,
                "essential": category.essential,
            }
            for category in plan.categories
        ],
        "spendings": [
            {
                "date": entry.spent_on.isoformat(),
                "category": entry.category,
                "amount_cents": entry.amount_cents,
                "note": entry.note,
            }
            for entry in plan.spendings
        ],
    }
    root = Path(config.PLAN_DATA_DIR)
    root.mkdir(parents=True, exist_ok=True)
    temporary = root / f".{plan_id}.tmp"
    try:
        temporary.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        temporary.replace(root / f"{plan_id}.json")
    finally:
        temporary.unlink(missing_ok=True)
    return SavedPlan(plan_id=plan_id, created_at=created_at, plan=plan)


def load_plan(plan_id: str) -> SavedPlan | None:
    """Read a plan only when its id and every stored value are valid."""
    if not is_valid_plan_id(plan_id):
        return None
    path = Path(config.PLAN_DATA_DIR) / f"{plan_id}.json"
    try:
        if not path.is_file() or path.stat().st_size > MAX_SAVED_PLAN_BYTES:
            return None
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return _plan_from_payload(plan_id, payload)


def plan_to_draft(plan: MoneyPlan) -> PlanDraft:
    return PlanDraft(
        student_name=plan.student_name,
        money_available=_amount_text(plan.money_available_cents),
        method=plan.method,
        method_note=plan.method_note,
        categories=tuple(
            CategoryDraft(
                name=category.name,
                planned=_amount_text(category.planned_cents),
                essential=category.essential,
            )
            for category in plan.categories
        ),
        spendings=tuple(
            SpendingDraft(
                spent_on=entry.spent_on.isoformat(),
                category=entry.category,
                amount=_amount_text(entry.amount_cents),
                note=entry.note,
            )
            for entry in plan.spendings
        ),
        synthetic=True,
    )


def _plan_from_payload(plan_id: str, payload: object) -> SavedPlan | None:
    if not isinstance(payload, dict) or payload.get("version") != 1:
        return None
    if payload.get("plan_id") != plan_id:
        return None

    created_at = payload.get("created_at")
    if not isinstance(created_at, str) or not created_at or len(created_at) > 40:
        return None

    student_name = payload.get("student_name")
    if not isinstance(student_name, str):
        return None
    student_name = _clean_spaces(student_name)
    if (
        not student_name
        or len(student_name) > MAX_NAME_LENGTH
        or not _printable(student_name)
    ):
        return None

    money_available = _stored_int(
        payload.get("money_available_cents"), 1, MAX_PLANNED_CENTS
    )
    method = payload.get("method")
    if money_available is None or method not in BUDGET_METHODS:
        return None

    method_note = payload.get("method_note")
    if not isinstance(method_note, str):
        return None
    method_note = _clean_spaces(method_note)
    if len(method_note) > MAX_METHOD_NOTE_LENGTH or not _printable(method_note):
        return None

    raw_categories = payload.get("categories")
    if not isinstance(raw_categories, list) or not 2 <= len(raw_categories) <= MAX_CATEGORIES:
        return None
    categories: list[CategoryPlan] = []
    seen: set[str] = set()
    for raw in raw_categories:
        if not isinstance(raw, dict):
            return None
        name = raw.get("name")
        planned = _stored_int(raw.get("planned_cents"), 0, MAX_PLANNED_CENTS)
        essential = raw.get("essential")
        if not isinstance(name, str) or planned is None or not isinstance(essential, bool):
            return None
        name = _clean_spaces(name)
        if (
            not name
            or len(name) > MAX_CATEGORY_NAME_LENGTH
            or not _printable(name)
            or name.casefold() in seen
        ):
            return None
        seen.add(name.casefold())
        categories.append(CategoryPlan(name, planned, essential))

    raw_spendings = payload.get("spendings")
    if not isinstance(raw_spendings, list) or not 1 <= len(raw_spendings) <= MAX_SPENDINGS:
        return None
    spendings: list[SpendingEntry] = []
    for raw in raw_spendings:
        if not isinstance(raw, dict):
            return None
        spent_on = raw.get("date")
        category = raw.get("category")
        amount = _stored_int(raw.get("amount_cents"), 1, MAX_SPENDING_CENTS)
        note = raw.get("note", "")
        if (
            not isinstance(spent_on, str)
            or not isinstance(category, str)
            or amount is None
            or not isinstance(note, str)
        ):
            return None
        try:
            parsed_date = date.fromisoformat(spent_on)
        except ValueError:
            return None
        canonical = {item.name.casefold(): item.name for item in categories}.get(
            category.casefold()
        )
        note = _clean_spaces(note)
        if (
            canonical is None
            or len(note) > MAX_ENTRY_NOTE_LENGTH
            or not _printable(note)
        ):
            return None
        spendings.append(SpendingEntry(parsed_date, canonical, amount, note))

    return SavedPlan(
        plan_id=plan_id,
        created_at=created_at,
        plan=MoneyPlan(
            student_name=student_name,
            money_available_cents=money_available,
            method=str(method),
            method_note=method_note,
            categories=tuple(categories),
            spendings=tuple(spendings),
        ),
    )


def _amount_text(cents: int) -> str:
    return f"{cents // 100}.{cents % 100:02d}"


def _stored_int(value: object, minimum: int, maximum: int) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    if not minimum <= value <= maximum:
        return None
    return value


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
