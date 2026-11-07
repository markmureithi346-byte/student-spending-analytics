"""Shared paths and business rules for every pipeline stage."""

from __future__ import annotations

import os
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from urllib.parse import urlsplit


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def _env_flag(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_path(name: str, default: Path) -> Path:
    raw = _env(name)
    return Path(raw).expanduser().resolve() if raw else default


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

ENVIRONMENT = _env("PLANIT_ENV", "development").lower()
PRODUCTION = ENVIRONMENT == "production"
PUBLIC_URL = _env("PLANIT_PUBLIC_URL").rstrip("/")
SECURE_COOKIES = _env_flag("PLANIT_SECURE_COOKIES", PRODUCTION)
TRUST_PROXY = _env_flag("PLANIT_TRUST_PROXY", False)
HOST = _env("PLANIT_HOST", "127.0.0.1")

DATA_DIR = _env_path("PLANIT_DATA_DIR", PROJECT_ROOT / "data")
RAW_DATA_DIR = _env_path("PLANIT_RAW_DATA_DIR", DATA_DIR / "raw")
UPLOAD_DATA_DIR = _env_path("PLANIT_UPLOAD_DATA_DIR", DATA_DIR / "uploads")
PROCESSED_DATA_DIR = _env_path("PLANIT_PROCESSED_DATA_DIR", DATA_DIR / "processed")
QUARANTINE_DIR = _env_path("PLANIT_QUARANTINE_DIR", DATA_DIR / "quarantine")
WAREHOUSE_DIR = _env_path("PLANIT_WAREHOUSE_DIR", PROJECT_ROOT / "warehouse")
UPLOAD_WAREHOUSE_DIR = _env_path(
    "PLANIT_UPLOAD_WAREHOUSE_DIR", WAREHOUSE_DIR / "uploads"
)
REPORTS_DIR = _env_path("PLANIT_REPORTS_DIR", PROJECT_ROOT / "reports")
UPLOAD_REPORT_DIR = _env_path("PLANIT_UPLOAD_REPORT_DIR", REPORTS_DIR / "uploads")
LOG_DIR = _env_path("PLANIT_LOG_DIR", PROJECT_ROOT / "logs")

_source_schema = PROJECT_ROOT / "sql" / "schema.sql"
_packaged_schema = Path(__file__).with_name("schema.sql")
SCHEMA_PATH = _env_path(
    "PLANIT_SCHEMA", _source_schema if _source_schema.is_file() else _packaged_schema
)

DEFAULT_DB_PATH = _env_path(
    "PLANIT_DB_PATH", WAREHOUSE_DIR / "student_spending.db"
)
ACCOUNTS_DB_PATH = _env_path("PLANIT_ACCOUNTS_DB", DATA_DIR / "accounts.db")
DEFAULT_TRANSACTIONS_CSV = _env_path(
    "PLANIT_TRANSACTIONS_CSV", RAW_DATA_DIR / "student_expenses.csv"
)
DEFAULT_PROFILES_CSV = _env_path(
    "PLANIT_PROFILES_CSV", RAW_DATA_DIR / "student_profiles.csv"
)
DEFAULT_BUDGETS_CSV = _env_path(
    "PLANIT_BUDGETS_CSV", RAW_DATA_DIR / "student_budgets.csv"
)

# Operator details used to fill the privacy notice and terms. Anything still
# empty is shown as a bracketed placeholder, and production mode refuses to
# start until the required values are supplied.
OPERATOR_NAME = _env("PLANIT_OPERATOR_NAME")
OPERATOR_ADDRESS = _env("PLANIT_OPERATOR_ADDRESS")
PRIVACY_EMAIL = _env("PLANIT_PRIVACY_EMAIL")
ODPC_REGISTRATION = _env(
    "PLANIT_ODPC_REGISTRATION", "[ODPC REGISTRATION NUMBER OR \"NOT YET REGISTERED\"]"
)
ODPC_CONTACT = _env(
    "PLANIT_ODPC_CONTACT",
    "Office of the Data Protection Commissioner, Nairobi, Kenya "
    "(https://www.odpc.go.ke)",
)
EFFECTIVE_DATE = _env("PLANIT_EFFECTIVE_DATE")
HOSTING_PROVIDER = _env("PLANIT_HOSTING_PROVIDER")
INTERNATIONAL_TRANSFERS = _env(
    "PLANIT_INTERNATIONAL_TRANSFERS", "None beyond the hosting provider named above."
)
RETENTION_PERIOD = _env("PLANIT_RETENTION_PERIOD", "30 days")
LOG_RETENTION = _env("PLANIT_LOG_RETENTION", "14 days")
BACKUP_RETENTION = _env("PLANIT_BACKUP_RETENTION", "None")
AGE_ASSURANCE = _env(
    "PLANIT_AGE_ASSURANCE",
    "Users confirm that they are 18 or over when they create an account.",
)
COUNTY = _env("PLANIT_COUNTY", "Nairobi")
TRADEMARK = _env(
    "PLANIT_TRADEMARK", "unregistered marks used by the operator of this service"
)
LIABILITY_CAP = _env(
    "PLANIT_LIABILITY_CAP",
    "[LIABILITY CAP AND ANY REQUIRED CONSUMER-RIGHTS WORDING]",
)
LEGAL_REVIEWED = _env_flag("PLANIT_LEGAL_REVIEWED", False)
POLICY_VERSION = _env("PLANIT_POLICY_VERSION", "2026-11-07")


def public_origin() -> str:
    """The configured https origin, or an empty string when unset."""
    return PUBLIC_URL


def production_problems() -> list[str]:
    """Configuration gaps that must be fixed before a public launch."""
    if not PRODUCTION:
        return []
    problems: list[str] = []
    parsed = urlsplit(PUBLIC_URL)
    if parsed.scheme != "https" or not parsed.netloc:
        problems.append(
            "PLANIT_PUBLIC_URL must be the public https:// address of the service."
        )
    if not SECURE_COOKIES:
        problems.append(
            "PLANIT_SECURE_COOKIES must be on in production; the session cookie "
            "would otherwise travel over plain HTTP."
        )
    required = {
        "PLANIT_OPERATOR_NAME": OPERATOR_NAME,
        "PLANIT_OPERATOR_ADDRESS": OPERATOR_ADDRESS,
        "PLANIT_PRIVACY_EMAIL": PRIVACY_EMAIL,
        "PLANIT_EFFECTIVE_DATE": EFFECTIVE_DATE,
        "PLANIT_HOSTING_PROVIDER": HOSTING_PROVIDER,
        "PLANIT_ODPC_REGISTRATION": ODPC_REGISTRATION,
        "PLANIT_LIABILITY_CAP": LIABILITY_CAP,
    }
    for name, value in required.items():
        if not value or value.startswith("["):
            problems.append(f"{name} is required for the published legal pages.")
    if PRIVACY_EMAIL and "@" not in PRIVACY_EMAIL:
        problems.append("PLANIT_PRIVACY_EMAIL must be a usable email address.")
    if not LEGAL_REVIEWED:
        problems.append(
            "PLANIT_LEGAL_REVIEWED=1 must be set after a qualified Kenyan lawyer "
            "has reviewed the privacy notice and terms."
        )
    return problems


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


def ensure_private_dir(path: Path | str) -> Path:
    """Create a directory readable only by the service account where possible."""
    target = Path(path)
    target.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(target, 0o700)
    except OSError:
        pass
    return target


def restrict_file(path: Path | str) -> None:
    """Tighten a file that holds account or uploaded personal data."""
    try:
        os.chmod(Path(path), 0o600)
    except OSError:
        pass
