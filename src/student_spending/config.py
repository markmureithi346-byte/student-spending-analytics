"""Shared paths and business rules for every pipeline stage."""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

def _locate_project_root() -> Path:
    """Checkout root when run from source, else the working directory.

    An editable install imports this file from ``src/``, so the checkout is two
    levels up. A regular wheel install lives in site-packages, where that path
    is meaningless; such runs resolve paths against the current directory.
    """
    source_root = Path(__file__).resolve().parents[2]
    if (source_root / "sql" / "schema.sql").is_file():
        return source_root
    return Path.cwd()


PROJECT_ROOT = _locate_project_root()

RAW_DATA_DIR = PROJECT_ROOT / "data" / "raw"
PROCESSED_DATA_DIR = PROJECT_ROOT / "data" / "processed"
QUARANTINE_DIR = PROJECT_ROOT / "data" / "quarantine"
WAREHOUSE_DIR = PROJECT_ROOT / "warehouse"
REPORTS_DIR = PROJECT_ROOT / "reports"
LOG_DIR = PROJECT_ROOT / "logs"
SCHEMA_PATH = PROJECT_ROOT / "sql" / "schema.sql"

DEFAULT_DB_PATH = WAREHOUSE_DIR / "student_spending.db"
DEFAULT_TRANSACTIONS_CSV = RAW_DATA_DIR / "student_expenses.csv"
DEFAULT_PROFILES_CSV = RAW_DATA_DIR / "student_profiles.csv"
DEFAULT_BUDGETS_CSV = RAW_DATA_DIR / "student_budgets.csv"

# Canonical category names. The boolean marks discretionary spending, which is
# the part of a budget a student can realistically flex.
CATEGORY_DISCRETIONARY: dict[str, bool] = {
    "Food": False,
    "Transport": False,
    "Rent": False,
    "Utilities": False,
    "Education": False,
    "Airtime and Internet": False,
    "Entertainment": True,
    "Personal Care": True,
    "Other": True,
}

ALLOWED_CATEGORIES = tuple(CATEGORY_DISCRETIONARY)

CATEGORY_ALIASES: dict[str, str] = {
    name.lower(): name for name in CATEGORY_DISCRETIONARY
}
CATEGORY_ALIASES.update(
    {
        "airtime & internet": "Airtime and Internet",
        "airtime and internet": "Airtime and Internet",
        "airtime": "Airtime and Internet",
        "internet": "Airtime and Internet",
        "transportation": "Transport",
        "personalcare": "Personal Care",
        "personal-care": "Personal Care",
        "utilities and water": "Utilities",
    }
)

PAYMENT_METHOD_ALIASES: dict[str, str] = {
    "m-pesa": "M-Pesa",
    "mpesa": "M-Pesa",
    "m pesa": "M-Pesa",
    "m_pesa": "M-Pesa",
    "cash": "Cash",
    "card": "Card",
    "debit card": "Card",
    "credit card": "Card",
    "bank": "Bank Transfer",
    "bank transfer": "Bank Transfer",
    "banktransfer": "Bank Transfer",
    "transfer": "Bank Transfer",
}
DEFAULT_PAYMENT_METHOD = "Other"

MIN_TRANSACTION_DATE = date(2020, 1, 1)
MAX_TRANSACTION_AMOUNT_CENTS = 10_000_000  # KES 100,000.00

ANOMALY_MULTIPLIER = 3
ANOMALY_FLOOR_CENTS = 250_000  # KES 2,500.00
MAX_ANOMALY_RATE = 0.05

AMOUNT_QUANTUM = Decimal("0.01")


def utc_now() -> str:
    """Current UTC timestamp in a sortable, human-readable format."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()
