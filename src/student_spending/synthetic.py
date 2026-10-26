"""Deterministic generator for the synthetic student spending dataset.

Everything here is fake by construction. The generator deliberately plants
data quality defects so the pipeline has something real to detect; the same
seed always produces byte-identical files.
"""

from __future__ import annotations

import csv
import io
import random
from datetime import date, timedelta
from pathlib import Path

TRANSACTION_HEADER = (
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

PROFILE_HEADER = ("student_id", "profile_label", "campus", "study_year", "monthly_income_kes")
BUDGET_HEADER = ("student_id", "budget_month", "category", "budget_kes")

MONTHS = ("2026-07", "2026-08", "2026-09")

# student_id, profile_label, campus, study_year, monthly_income_kes
PROFILES = (
    ("STU-001", "Profile A", "Main Campus", 2, 32000),
    ("STU-002", "Profile B", "Main Campus", 1, 21000),
    ("STU-003", "Profile C", "Westlands Campus", 3, 45000),
    ("STU-004", "Profile D", "Kikuyu Campus", 4, 38000),
    ("STU-005", "Profile E", "Main Campus", 2, 25000),
    ("STU-006", "Profile F", "Westlands Campus", 1, 18500),
)

RENT_BY_STUDENT = {
    "STU-001": 11000,
    "STU-002": 9500,
    "STU-003": 15000,
    "STU-004": 12500,
    "STU-005": 10500,
    "STU-006": 9000,
}

DESCRIPTIONS = {
    "Food": ["Lunch at campus", "Groceries", "Chapati and beans", "Coffee", "Dinner", "Snacks", "Market run"],
    "Transport": ["Matatu fare", "Bolt ride", "Uber ride", "Shuttle ticket", "Fuel top-up"],
    "Rent": ["Monthly hostel rent", "Room rent"],
    "Utilities": ["Electricity token", "Water bill", "Hostel utilities"],
    "Education": ["Textbook", "Printing and binding", "Lab materials", "Tuition instalment", "Online course"],
    "Airtime and Internet": ["Airtime top-up", "Data bundle", "Wifi subscription"],
    "Entertainment": ["Cinema ticket", "Football match", "Music subscription", "Concert ticket", "Game purchase"],
    "Personal Care": ["Haircut", "Pharmacy", "Toiletries", "Laundry"],
    "Other": ["Gift", "Club contribution", "Miscellaneous"],
}

MERCHANTS = {
    "Food": ["Campus Cafeteria", "Java House", "Quickmart", "Kwa Mali", "Mama Oliech Kitchen", "Chicken Inn"],
    "Transport": ["Matatu Route 46", "Uber", "Bolt", "Campus Shuttle", "Total Petrol Station"],
    "Rent": ["Nyayo Hostels", "Sunrise Apartments", "Campus Bedsitters"],
    "Utilities": ["KPLC", "Nairobi Water", "Campus Utilities"],
    "Education": ["University Bookshop", "Printing Hub", "Faculty Fees Office", "Stationery Mart"],
    "Airtime and Internet": ["Safaricom", "Airtel", "Zuku", "Jamii Telecom"],
    "Entertainment": ["Westgate Cinema", "Nairobi Sports Club", "Spotify", "Steam"],
    "Personal Care": ["Supercuts Salon", "Chemist Warehouse", "Naivas Pharmacy", "Barber Hub"],
    "Other": ["Gift Shop", "Misc Vendor", "Campus Fundraiser"],
}

PAYMENT_BY_CATEGORY = {
    "Rent": ["Bank Transfer", "M-Pesa"],
    "Utilities": ["M-Pesa", "Bank Transfer"],
    "Education": ["M-Pesa", "Card", "Bank Transfer"],
    "Airtime and Internet": ["M-Pesa"],
    "Food": ["M-Pesa", "M-Pesa", "Cash", "Card"],
    "Transport": ["M-Pesa", "Cash"],
    "Entertainment": ["M-Pesa", "Card"],
    "Personal Care": ["M-Pesa", "Cash", "Card"],
    "Other": ["M-Pesa", "Cash"],
}

FORCED_OVERRUNS = {
    ("STU-001", "2026-09", "Food"): 0.60,
    ("STU-003", "2026-08", "Entertainment"): 0.55,
    ("STU-006", "2026-07", "Transport"): 0.65,
    ("STU-002", "2026-08", "Airtime and Internet"): 0.70,
}


def _month_start(month: str) -> date:
    year, month_number = month.split("-")
    return date(int(year), int(month_number), 1)


def _days_in_month(month: str) -> int:
    start = _month_start(month)
    following = date(start.year + (start.month == 12), start.month % 12 + 1, 1)
    return (following - start).days


def _format_row(row: dict[str, str]) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow([row[column] for column in TRANSACTION_HEADER])
    return buffer.getvalue()


def _generate_base_rows(rng: random.Random) -> tuple[list[dict[str, str]], dict[tuple[str, str, str], float]]:
    rows: list[dict[str, str]] = []
    totals: dict[tuple[str, str, str], float] = {}
    counter = 0

    for student_id, _label, _campus, _year, _income in PROFILES:
        for month in MONTHS:
            start = _month_start(month)
            last_day = _days_in_month(month)

            def add(
                category: str,
                low: float,
                high: float,
                *,
                day: int | None = None,
                recurring: bool = False,
                amount: float | None = None,
                description: str | None = None,
                merchant: str | None = None,
            ) -> None:
                nonlocal counter
                counter += 1
                chosen_day = day if day is not None else rng.randint(1, last_day)
                when = start + timedelta(days=max(1, min(chosen_day, last_day)) - 1)
                value = amount if amount is not None else round(rng.uniform(low, high), 2)
                rows.append(
                    {
                        "transaction_id": f"TXN-{counter:04d}",
                        "student_id": student_id,
                        "transaction_date": when.isoformat(),
                        "amount_kes": f"{value:.2f}",
                        "category": category,
                        "description": description or rng.choice(DESCRIPTIONS[category]),
                        "payment_method": rng.choice(PAYMENT_BY_CATEGORY[category]),
                        "merchant": merchant or rng.choice(MERCHANTS[category]),
                        "is_recurring": "true" if recurring else "false",
                    }
                )
                key = (student_id, month, category)
                totals[key] = totals.get(key, 0.0) + value

            add("Rent", 0, 0, day=1, recurring=True, amount=float(RENT_BY_STUDENT[student_id]))
            add("Utilities", 900, 2600, day=rng.randint(3, 6), recurring=True)
            add("Education", 1800, 5200, day=rng.randint(7, 20))
            add("Education", 1200, 3800, day=rng.randint(20, 27))
            add("Airtime and Internet", 500, 1800, day=rng.randint(2, 5), recurring=True)
            add("Airtime and Internet", 400, 1500, day=rng.randint(14, 22))
            for _ in range(6):
                add("Food", 150, 950)
            for _ in range(rng.randint(4, 5)):
                add("Transport", 80, 650)
            for _ in range(rng.randint(1, 2)):
                add("Entertainment", 400, 2200)
            add("Personal Care", 300, 1400)
            if rng.random() < 0.6:
                add("Other", 150, 900)

    # Two deliberately large but legitimate purchases, so the anomaly rule has
    # something to flag without any record being invalid.
    rows.append(
        {
            "transaction_id": f"TXN-{counter + 1:04d}",
            "student_id": "STU-003",
            "transaction_date": "2026-08-12",
            "amount_kes": "24000.00",
            "category": "Education",
            "description": "Laptop repair",
            "payment_method": "M-Pesa",
            "merchant": "Tech Repairs Nairobi",
            "is_recurring": "false",
        }
    )
    totals[("STU-003", "2026-08", "Education")] += 24000.0
    rows.append(
        {
            "transaction_id": f"TXN-{counter + 2:04d}",
            "student_id": "STU-005",
            "transaction_date": "2026-09-18",
            "amount_kes": "18500.00",
            "category": "Education",
            "description": "Exam fee balance",
            "payment_method": "Bank Transfer",
            "merchant": "Faculty Fees Office",
            "is_recurring": "false",
        }
    )
    totals[("STU-005", "2026-09", "Education")] += 18500.0

    return rows, totals


def _inject_defects(rng: random.Random, rows: list[dict[str, str]]) -> tuple[list[str], dict[str, int]]:
    """Mutate and append problematic rows; return raw malformed lines and a tally."""
    defects: dict[str, int] = {}

    def count(name: str, amount: int = 1) -> None:
        defects[name] = defects.get(name, 0) + amount

    def sample(amount: int) -> list[dict[str, str]]:
        return rng.sample(rows, amount)

    for index, row in enumerate(sample(6), start=1):
        row["category"] = (
            row["category"].lower(),
            row["category"].upper(),
            row["category"] + " ",
            row["category"].replace("and", "&"),
            "  " + row["category"],
            row["category"].lower().replace(" ", ""),
        )[index - 1]
        count("category_capitalisation")
    for index, row in enumerate(sample(4)):
        row["payment_method"] = ("mpesa", "M-PESA", "M_Pesa", "cash")[index]
        count("payment_method_variants")
    for row in sample(3):
        row["description"] = ""
        count("blank_description")
    for row in sample(2):
        row["merchant"] = ""
        count("blank_merchant")

    issue_counter = 9001

    def issue(**overrides: str) -> dict[str, str]:
        nonlocal issue_counter
        base = {
            "transaction_id": f"TXN-{issue_counter}",
            "student_id": "STU-002",
            "transaction_date": "2026-08-14",
            "amount_kes": "480.00",
            "category": "Food",
            "description": "Lunch at campus",
            "payment_method": "M-Pesa",
            "merchant": "Campus Cafeteria",
            "is_recurring": "false",
        }
        issue_counter += 1
        base.update(overrides)
        rows.append(base)
        return base

    for when in ("2026-13-05", "05/08/2026", "not-a-date", "2026-02-30"):
        issue(transaction_date=when)
        count("invalid_date")
    for amount in ("0.00", "-250.00", "0"):
        issue(amount_kes=amount)
        count("non_positive_amount")
    for category in ("Gambling", "Crypto", "Uncategorised"):
        issue(category=category)
        count("unexpected_category")
    for student in ("STU-901", "STU-902"):
        issue(student_id=student)
        count("unknown_student")
    for field in ("student_id", "transaction_date", "amount_kes", "category", "transaction_id"):
        issue(**{field: ""})
        count("missing_required_value")
    issue(amount_kes="twelve hundred")
    count("non_numeric_amount")
    issue(transaction_date="2027-01-15")
    count("future_date")

    raw_lines = [
        "TXN-9801,STU-001,2026-08-14,850.00,Food,Lunch, and snacks,M-Pesa,Java House,false\n",
        "TXN-9802,STU-002,2026-08-15,1200.00,Food,Lunch\n",
        "TXN-9803,STU-003,2026-09-02,300.00,Transport,,Uber,false\n",
    ]
    count("malformed_row", len(raw_lines))

    duplicate_sources = rng.sample(
        [row for row in rows if row["transaction_id"].startswith("TXN-0")], 7
    )
    for row in duplicate_sources[:4]:
        rows.append(dict(row))
        count("identical_duplicate_row")
    for row in duplicate_sources[4:]:
        clone = dict(row)
        clone["amount_kes"] = f"{float(clone['amount_kes']) + 250:.2f}"
        clone["description"] = "corrected entry"
        rows.append(clone)
        count("conflicting_duplicate_row", 2)

    return raw_lines, defects


def _generate_budgets(
    rng: random.Random,
    totals: dict[tuple[str, str, str], float],
) -> list[dict[str, str]]:
    budgets: list[dict[str, str]] = []
    for student_id, _label, _campus, _year, _income in PROFILES:
        for month in MONTHS:
            for category in DESCRIPTIONS:
                actual = totals.get((student_id, month, category), 0.0)
                factor = FORCED_OVERRUNS.get((student_id, month, category), rng.uniform(0.9, 1.45))
                target = max(100.0, round(actual * factor / 50.0) * 50.0)
                budgets.append(
                    {
                        "student_id": student_id,
                        "budget_month": month,
                        "category": category,
                        "budget_kes": f"{target:.2f}",
                    }
                )
    return budgets


def generate_dataset(output_dir: Path, seed: int = 42) -> dict[str, object]:
    """Write the three raw CSV files and return a summary of what was created."""
    rng = random.Random(seed)
    output_dir.mkdir(parents=True, exist_ok=True)

    rows, totals = _generate_base_rows(rng)
    raw_lines, defects = _inject_defects(rng, rows)
    budgets = _generate_budgets(rng, totals)

    lines = [_format_row(row) for row in rows] + raw_lines
    rng.shuffle(lines)
    transactions_path = output_dir / "student_expenses.csv"
    with transactions_path.open("w", encoding="utf-8", newline="") as handle:
        handle.write(",".join(TRANSACTION_HEADER) + "\n")
        handle.writelines(lines)

    profiles_path = output_dir / "student_profiles.csv"
    with profiles_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(PROFILE_HEADER)
        writer.writerows(PROFILES)

    budgets_path = output_dir / "student_budgets.csv"
    with budgets_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(BUDGET_HEADER)
        for budget in budgets:
            writer.writerow([budget[column] for column in BUDGET_HEADER])

    return {
        "transactions": len(lines),
        "profiles": len(PROFILES),
        "budgets": len(budgets),
        "defects": defects,
        "paths": {
            "transactions": transactions_path,
            "profiles": profiles_path,
            "budgets": budgets_path,
        },
    }
