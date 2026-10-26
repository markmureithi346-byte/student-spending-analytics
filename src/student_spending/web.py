"""Interactive, read-only spending dashboard served by the standard library.

Every figure on the page comes from a parameterised query against the same SQL
views the static report uses. The server binds to loopback by default, opens
the warehouse in read-only mode and never accepts writes. Filters are ordinary
GET form fields, so the page needs no JavaScript and every view is bookmarkable.
"""

from __future__ import annotations

import csv
import html
import io
import logging
import sqlite3
import threading
import urllib.parse
import webbrowser
from dataclasses import dataclass, replace
from datetime import date
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import config
from .components import bar_chart, grouped_bar_chart, integer, money, percent, share_cell, table
from .personal import (
    BUDGET_METHODS,
    CATEGORY_ROWS,
    MAX_CATEGORIES,
    MAX_CATEGORY_NAME_LENGTH,
    MAX_ENTRY_NOTE_LENGTH,
    MAX_METHOD_NOTE_LENGTH,
    MAX_NAME_LENGTH,
    MAX_PLAN_REQUEST_BYTES,
    MAX_SPENDINGS,
    SPENDING_ROWS,
    PlanDraft,
    PlanRequestError,
    SavedPlan,
    analyse,
    load_plan,
    parse_form,
    plan_to_draft,
    read_draft,
    save_plan,
    validate_draft,
)
from .platform import (
    FILE_FIELDS,
    MAX_CSV_ROWS,
    MAX_FILE_BYTES,
    MAX_REQUEST_BYTES,
    MAX_TITLE_LENGTH,
    AnalysisWorkspace,
    PipelineFailure,
    UploadError,
    create_analysis,
    list_analyses,
    parse_upload,
    workspace_for,
)
from .theme import BASE_CSS

logger = logging.getLogger(__name__)

PER_PAGE_CHOICES = (25, 50, 100)
SORT_CHOICES = {
    "newest": ("Newest first", "transaction_date DESC, transaction_id"),
    "oldest": ("Oldest first", "transaction_date, transaction_id"),
    "largest": ("Largest amount first", "amount_cents DESC, transaction_id"),
    "smallest": ("Smallest amount first", "amount_cents, transaction_id"),
}
FLAG_CHOICES = {
    "all": "All transactions",
    "anomalies": "Flagged for review only",
}
SEARCH_LIMIT = 80
MERCHANT_LIMIT = 8
SAMPLE_FILES = {
    "student_expenses.csv": config.DEFAULT_TRANSACTIONS_CSV,
}

_DASH_CSS = """
.dash-hero .hero-actions { display: flex; flex-wrap: wrap; gap: 10px; margin: 0 0 18px; }
.hero-actions .button.ghost { background: rgba(255,255,255,.1);
  border-color: rgba(255,255,255,.25); color: #f3e8ff; }
.hero-actions .button.ghost:hover { background: rgba(255,255,255,.18); }
.button { display: inline-flex; align-items: center; justify-content: center; gap: 6px;
  padding: 9px 16px; border-radius: 999px; border: 1px solid transparent;
  font: inherit; font-size: 13.5px; font-weight: 700; text-decoration: none;
  cursor: pointer; transition: transform .15s ease, box-shadow .15s ease,
  background-color .15s ease; }
.button.primary { background: linear-gradient(100deg, #7c3aed, #c026d3); color: #fff;
  box-shadow: 0 10px 20px -12px rgba(109, 40, 217, .8); }
.button.primary:hover { transform: translateY(-1px); }
.button.ghost { background: #fff; border-color: #ddcff2; color: #5b21b6; }
.button.ghost:hover { background: #f7f0ff; }
.button.small { padding: 6px 12px; font-size: 12.5px; }
.button.disabled { opacity: .45; cursor: not-allowed; pointer-events: none; }
.filters { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 14px 16px; margin-top: 14px; }
.field { display: flex; flex-direction: column; gap: 5px; min-width: 0; }
.field label { font-size: 11.5px; font-weight: 700; text-transform: uppercase;
  letter-spacing: .06em; color: #5b4a7a; }
.field input, .field select { width: 100%; padding: 9px 11px; border: 1px solid #ddcff2;
  border-radius: 10px; background: #fff; color: var(--ink); font: inherit;
  font-size: 14px; }
.field input:hover, .field select:hover { border-color: #c4a5ea; }
.field input:focus, .field select:focus { outline: 3px solid rgba(124,58,237,.2);
  border-color: var(--accent); }
.field-search { grid-column: span 2; }
.filters .actions { grid-column: span 2; display: flex; flex-wrap: wrap; gap: 10px;
  align-items: center; align-self: end; margin: 0; }
.filters .note { grid-column: 1 / -1; margin: 0; color: var(--muted); font-size: 12px; }
.dash-cards { grid-template-columns: repeat(4, minmax(0, 1fr)); }
.resultbar { display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between;
  gap: 10px 16px; margin: 16px 0 0; padding: 12px 14px; border: 1px solid var(--line);
  border-radius: 14px; background: #fbf8ff; }
.resultbar p { margin: 0; font-size: 13px; color: #4c3a66; }
.resultbar .button { flex: 0 0 auto; }
.active-filters { display: flex; flex-wrap: wrap; align-items: center; gap: 6px;
  margin: 10px 0 0; padding: 0; list-style: none; }
.active-filters li { font-size: 12px; background: #f3edfb; color: #5b21b6;
  padding: 3px 9px; border-radius: 999px; }
.active-filters .clear { background: transparent; color: var(--danger); font-weight: 700;
  text-decoration: none; padding: 3px 4px; }
.active-filters .clear:hover { text-decoration: underline; }
.table-meta { display: flex; flex-wrap: wrap; justify-content: space-between; gap: 8px;
  margin: 0 0 10px; color: var(--muted); font-size: 12.5px; }
.cell-merchant strong { display: block; color: var(--ink); font-weight: 600; }
.cell-merchant .sub { display: block; color: var(--muted); font-size: 12px;
  max-width: 38ch; }
.pill-review { background: var(--danger-soft); color: var(--danger); }
.pager { display: flex; flex-wrap: wrap; align-items: center; gap: 10px; margin-top: 14px; }
.pager .page-label { font-size: 12.5px; color: var(--muted); }
.split { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 18px; }
.split table { min-width: 0; }
.split th, .split td { padding: 8px 10px; }
.flag-note { margin: 10px 0 0; }
.footer-links { display: flex; flex-wrap: wrap; gap: 16px; align-items: center; margin-top: 4px; }
.empty { margin: 10px 0 0; padding: 16px; border: 1px dashed #d8c4f7;
  border-radius: 14px; background: #fbf8ff; color: #4c3a66; }
.empty strong { color: var(--ink); }
.flag-link { font-size: 12.5px; font-weight: 700; color: var(--accent); }
.error-page { margin-top: 60px; }
.error-page p { color: var(--muted); }
.upload-grid { display: grid; grid-template-columns: minmax(0, 1.65fr) minmax(280px, 1fr);
  gap: 18px; margin-top: 18px; align-items: start; }
.upload-form { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 14px 16px; margin-top: 14px; }
.upload-form .field-full { grid-column: 1 / -1; }
.upload-form input[type="file"] { padding: 10px; background: #fbf8ff; }
.upload-form input[type="file"]::file-selector-button {
  margin-right: 10px; padding: 6px 11px; border: 1px solid #ddcff2; border-radius: 999px;
  background: #fff; color: #5b21b6; font: inherit; font-size: 12.5px; font-weight: 700;
  cursor: pointer; }
.upload-form .columns { margin: 0; color: var(--muted); font-size: 11.5px;
  line-height: 1.45; overflow-wrap: anywhere; }
.upload-form .check-field, .plan-form .check-field { grid-column: 1 / -1; display: flex;
  gap: 10px; align-items: flex-start; padding: 12px 14px; border: 1px solid #ddcff2;
  border-radius: 12px; background: #fbf8ff; font-size: 13px; color: #4c3a66; }
.upload-form .check-field input, .plan-form .check-field input { width: 18px;
  height: 18px; margin: 2px 0 0; flex: 0 0 auto; accent-color: var(--accent); }
.upload-form .actions { grid-column: 1 / -1; display: flex; flex-wrap: wrap;
  gap: 10px; align-items: center; }
.upload-note { grid-column: 1 / -1; margin: 0; color: var(--muted); font-size: 12px; }
.sample-links { display: flex; flex-wrap: wrap; gap: 8px 14px; align-items: center;
  margin: 2px 0 0; font-size: 12.5px; }
.sample-links a { color: var(--accent); font-weight: 700; }
.recent-list { list-style: none; margin: 14px 0 0; padding: 0; display: grid; gap: 10px; }
.recent-list li { padding: 12px 14px; border: 1px solid var(--line);
  border-radius: 12px; background: #fbf8ff; }
.recent-main { display: flex; flex-wrap: wrap; gap: 4px 10px; align-items: baseline; }
.recent-main strong { word-break: break-word; }
.recent-meta { margin: 3px 0 0; color: var(--muted); font-size: 12px; }
.recent-actions { display: flex; flex-wrap: wrap; gap: 8px; align-items: center;
  margin-top: 9px; }
.recent-empty { margin: 14px 0 0; padding: 14px; border: 1px dashed #d8c4f7;
  border-radius: 12px; background: #fbf8ff; color: #4c3a66; font-size: 13.5px; }
.upload-steps { margin: 14px 0 0; padding-left: 20px; color: var(--muted);
  font-size: 13px; }
.upload-steps li { margin-bottom: 6px; }
.upload-steps strong { color: var(--ink); }
.plan-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 14px 16px; margin-top: 14px; }
.plan-grid .field-full { grid-column: 1 / -1; }
.plan-form input, .plan-form select, .plan-form textarea { width: 100%;
  padding: 9px 11px; border: 1px solid #ddcff2; border-radius: 10px;
  background: #fff; color: var(--ink); font: inherit; font-size: 14px; }
.plan-form input:hover, .plan-form select:hover, .plan-form textarea:hover {
  border-color: #c4a5ea; }
.plan-form input:focus, .plan-form select:focus, .plan-form textarea:focus {
  outline: 3px solid rgba(124,58,237,.2); border-color: var(--accent); }
.plan-form textarea { min-height: 82px; resize: vertical; }
.plan-rows { margin-top: 14px; }
.plan-row-head, .plan-row { display: grid; gap: 8px; align-items: center; }
.cat-cols { grid-template-columns: 30px minmax(0, 2fr) minmax(0, 1fr) minmax(0, 1fr); }
.spend-cols { grid-template-columns: 30px minmax(0, 1.1fr) minmax(0, 1.5fr)
  minmax(0, .9fr) minmax(0, 1.9fr); }
.plan-row-head { padding: 0 2px 4px; color: #7a6a95; font-size: 10.5px;
  text-transform: uppercase; letter-spacing: .06em; font-weight: 800; }
.plan-row { margin-bottom: 7px; }
.plan-row input, .plan-row select { padding: 8px 9px; font-size: 13px; }
.row-no { color: #9a8cb5; font-size: 11px; font-weight: 700;
  font-variant-numeric: tabular-nums; text-align: right; }
.plan-section-note { margin: 8px 0 0; color: var(--muted); font-size: 12px; }
.plan-title-row { display: flex; flex-wrap: wrap; gap: 8px 16px; align-items: center;
  justify-content: space-between; }
.plan-add { display: flex; flex-wrap: wrap; gap: 8px 12px; align-items: center; }
.plan-add .button { border-style: dashed; }
.plan-add-button { width: 38px; height: 38px; padding: 0; font-size: 22px;
  line-height: 1; }
.plan-add-button span { transform: translateY(-1px); }
.error-list { margin: 5px 0 0; padding-left: 18px; }
.error-list li { margin: 2px 0; }
.plan-actions { display: flex; flex-wrap: wrap; gap: 10px; align-items: center;
  margin-top: 14px; }
.plan-cards { grid-template-columns: repeat(4, minmax(0, 1fr)); }
.plan-meta { display: flex; flex-wrap: wrap; gap: 6px 18px; margin: 0 0 4px;
  color: var(--muted); font-size: 13px; }
.plan-meta strong { color: var(--ink); }
.method-note { margin: 10px 0 0; padding: 12px 14px; border-left: 3px solid #c4b5fd;
  background: #fbf8ff; border-radius: 0 10px 10px 0; color: #4c3a66; font-size: 13.5px; }
.insight-list { margin: 8px 0 0; padding-left: 20px; color: #3f2b5c; font-size: 14px; }
.insight-list li { margin-bottom: 7px; }
.plan-tag { display: inline-block; margin-left: 7px; padding: 1px 7px;
  border-radius: 999px; background: #f3edfb; color: #5b21b6; font-size: 10.5px;
  font-weight: 700; text-transform: uppercase; letter-spacing: .04em; }
.pill.warn { background: #fff7ed; color: #9a3412; }
.pill.neutral { background: #f3edfb; color: #5b21b6; }
.banner.note { background: #fbf8ff; border: 1px solid #e6d6fb; color: #4c3a66; }
.plan-split { display: grid; grid-template-columns: minmax(0, 1.35fr) minmax(0, 1fr);
  gap: 18px; align-items: start; }
@media (max-width: 900px) {
  .plan-cards { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .plan-split { grid-template-columns: 1fr; }
  .upload-grid { grid-template-columns: 1fr; }
  .filters { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .field-search { grid-column: span 2; }
  .filters .actions { grid-column: span 2; }
  .dash-cards { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .split { grid-template-columns: 1fr; }
}
@media (max-width: 640px) {
  .upload-form { grid-template-columns: 1fr; }
  .upload-form .field-full { grid-column: auto; }
  .upload-form .check-field { grid-column: auto; }
  .upload-form .actions { grid-column: auto; }
  .upload-note { grid-column: auto; }
  .plan-grid { grid-template-columns: 1fr; }
  .plan-grid .field-full { grid-column: auto; }
  .plan-form .check-field { grid-column: auto; }
  .plan-row-head { display: none; }
  .cat-cols, .spend-cols { grid-template-columns: 1fr; }
  .plan-row { padding: 10px 12px; border: 1px solid var(--line);
    border-radius: 12px; background: #fcfaff; margin-bottom: 10px; }
  .plan-row .row-no { display: none; }
  .plan-row input, .plan-row select { font-size: 14px; }
  .plan-cards { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .filters { grid-template-columns: 1fr; }
  .field-search { grid-column: auto; }
  .filters .actions { grid-column: auto; }
  .dash-cards { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .resultbar .button { width: 100%; }
  .resultbar { align-items: flex-start; }
}
@media (max-width: 420px) {
  .dash-cards, .plan-cards { grid-template-columns: 1fr; }
}
@media (prefers-reduced-motion: reduce) {
  .button { transition: none; }
}
@media print {
  .filters, .pager, .hero-actions, .resultbar .button, .active-filters { display: none !important; }
}
"""


@dataclass(frozen=True)
class FilterOptions:
    students: list[dict]
    categories: list[str]
    payments: list[str]
    first_date: str
    last_date: str


@dataclass(frozen=True)
class Filters:
    date_from: str
    date_to: str
    student_id: str = ""
    category: str = ""
    payment_method: str = ""
    search: str = ""
    flag: str = "all"
    sort: str = "newest"
    per_page: int = 25
    page: int = 1
    analysis: str = ""

    @property
    def anomalies_only(self) -> bool:
        return self.flag == "anomalies"

    def to_query(self, page: int | None = None) -> dict[str, str]:
        query = {"from": self.date_from, "to": self.date_to}
        if self.analysis:
            query["analysis"] = self.analysis
        if self.student_id:
            query["student"] = self.student_id
        if self.category:
            query["category"] = self.category
        if self.payment_method:
            query["payment"] = self.payment_method
        if self.search:
            query["q"] = self.search
        if self.flag != "all":
            query["flag"] = self.flag
        if self.sort != "newest":
            query["sort"] = self.sort
        if self.per_page != 25:
            query["per_page"] = str(self.per_page)
        target_page = self.page if page is None else page
        if target_page > 1:
            query["page"] = str(target_page)
        return query


@dataclass
class DashboardData:
    kpis: dict
    months: list[dict]
    categories: list[dict]
    merchants: list[dict]
    payments: list[dict]
    transactions: list[dict]
    page: int
    page_count: int
    first_row: int
    last_row: int


def _first(query: dict[str, list[str]], key: str) -> str:
    values = query.get(key)
    return values[0].strip() if values else ""


def _form_row_count(
    form: dict[str, list[str]], key: str, *, default: int, maximum: int
) -> int:
    try:
        value = int(_first(form, key))
    except ValueError:
        return default
    return min(max(value, default), maximum)


def _valid_date(value: str) -> bool:
    if len(value) != 10 or value[4] != "-" or value[7] != "-":
        return False
    try:
        date.fromisoformat(value)
    except ValueError:
        return False
    return True


def _valid_int(value: str, *, minimum: int, maximum: int | None = None) -> int | None:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    if number < minimum:
        return None
    if maximum is not None and number > maximum:
        return None
    return number


def _like_pattern(text: str) -> str:
    escaped = text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def escape_attr(value: object) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def _document(
    title: str,
    body: str,
    *,
    skip_href: str | None = "#summary",
    skip_label: str = "Skip to results",
) -> str:
    skip = (
        f'<a class="skip" href="{escape_attr(skip_href)}">{escape_attr(skip_label)}</a>\n'
        if skip_href
        else ""
    )
    return (
        "<!DOCTYPE html>\n<html lang=\"en\">\n<head>\n<meta charset=\"utf-8\">\n"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n"
        f"<title>{escape_attr(title)}</title>\n"
        "<meta name=\"description\" content=\"Interactive analysis workspace for the "
        "synthetic student spending pipeline.\">\n"
        "<link rel=\"icon\" href=\"data:,\">\n"
        f"<style>{BASE_CSS}{_DASH_CSS}</style>\n</head>\n<body>\n"
        f"{skip}"
        '<div class="scene" aria-hidden="true">'
        '<span class="orb orb-a"></span><span class="orb orb-b"></span>'
        '<span class="orb orb-c"></span></div>\n'
        f"{body}</body>\n</html>\n"
    )


def _error_document(
    title: str,
    message: str,
    *,
    action_href: str = "/",
    action_label: str = "Back to the dashboard",
    eyebrow: str = "Spending explorer",
) -> str:
    body = f"""
<main class="shell">
  <section class="panel error-page">
    <p class="eyebrow">{escape_attr(eyebrow)}</p>
    <h2>{escape_attr(title)}</h2>
    <p>{escape_attr(message)}</p>
    <p><a class="button primary" href="{escape_attr(action_href)}">{escape_attr(action_label)}</a></p>
  </section>
</main>
"""
    return _document(f"{title} · Student Spending", body, skip_href=None)


def load_options(connection: sqlite3.Connection) -> FilterOptions:
    students = [
        dict(row)
        for row in connection.execute(
            "SELECT student_id, profile_label FROM students "
            "ORDER BY profile_label, student_id"
        )
    ]
    categories = [
        str(row[0])
        for row in connection.execute("SELECT category FROM categories ORDER BY category")
    ]
    payments = [
        str(row[0])
        for row in connection.execute(
            "SELECT DISTINCT payment_method FROM v_transactions ORDER BY 1"
        )
    ]
    bounds = connection.execute(
        "SELECT MIN(transaction_date), MAX(transaction_date) FROM transactions"
    ).fetchone()
    return FilterOptions(
        students=students,
        categories=categories,
        payments=payments,
        first_date=bounds[0] or "",
        last_date=bounds[1] or "",
    )


def parse_filters(query: dict[str, list[str]], options: FilterOptions) -> tuple[Filters, list[str]]:
    errors: list[str] = []

    date_from = _first(query, "from") or options.first_date
    date_to = _first(query, "to") or options.last_date
    if date_from and not _valid_date(date_from):
        errors.append("The start date must be a real date in YYYY-MM-DD form.")
        date_from = options.first_date
    if date_to and not _valid_date(date_to):
        errors.append("The end date must be a real date in YYYY-MM-DD form.")
        date_to = options.last_date
    if date_from and date_to and date_from > date_to:
        errors.append("The start date must not be after the end date.")
        date_from, date_to = options.first_date, options.last_date

    student_id = _first(query, "student")
    known_students = {str(student["student_id"]) for student in options.students}
    if student_id and student_id not in known_students:
        errors.append("That student is not in the warehouse.")
        student_id = ""

    category = _first(query, "category")
    if category and category not in options.categories:
        errors.append("That category is not in the warehouse.")
        category = ""

    payment_method = _first(query, "payment")
    if payment_method and payment_method not in options.payments:
        errors.append("That payment method is not in the warehouse.")
        payment_method = ""

    search = _first(query, "q")
    if len(search) > SEARCH_LIMIT:
        errors.append(f"Search text was shortened to {SEARCH_LIMIT} characters.")
        search = search[:SEARCH_LIMIT]

    flag = _first(query, "flag") or "all"
    if flag not in FLAG_CHOICES:
        errors.append("The review filter must be 'all' or 'anomalies'.")
        flag = "all"

    sort = _first(query, "sort") or "newest"
    if sort not in SORT_CHOICES:
        errors.append("That sort order is not available.")
        sort = "newest"

    raw_per_page = _first(query, "per_page")
    per_page = 25
    if raw_per_page:
        parsed_per_page = _valid_int(raw_per_page, minimum=1)
        if parsed_per_page in PER_PAGE_CHOICES:
            per_page = parsed_per_page
        else:
            errors.append("Rows per page must be 25, 50 or 100.")
    raw_page = _first(query, "page")
    page = 1
    if raw_page:
        parsed_page = _valid_int(raw_page, minimum=1)
        if parsed_page is None:
            errors.append("The page number must be a whole number of 1 or more.")
        else:
            page = parsed_page

    return (
        Filters(
            date_from=date_from,
            date_to=date_to,
            student_id=student_id,
            category=category,
            payment_method=payment_method,
            search=search,
            flag=flag,
            sort=sort,
            per_page=per_page,
            page=page,
        ),
        errors,
    )


def build_where(filters: Filters) -> tuple[str, list[object]]:
    clauses: list[str] = []
    params: list[object] = []
    if filters.date_from:
        clauses.append("transaction_date >= ?")
        params.append(filters.date_from)
    if filters.date_to:
        clauses.append("transaction_date <= ?")
        params.append(filters.date_to)
    if filters.student_id:
        clauses.append("student_id = ?")
        params.append(filters.student_id)
    if filters.category:
        clauses.append("category = ?")
        params.append(filters.category)
    if filters.payment_method:
        clauses.append("payment_method = ?")
        params.append(filters.payment_method)
    if filters.anomalies_only:
        clauses.append("is_anomaly = 1")
    if filters.search:
        pattern = _like_pattern(filters.search)
        clauses.append(
            "(merchant LIKE ? ESCAPE '\\' OR description LIKE ? ESCAPE '\\')"
        )
        params.extend([pattern, pattern])
    if not clauses:
        return "1 = 1", params
    return " AND ".join(clauses), params


def load_dashboard(connection: sqlite3.Connection, filters: Filters) -> DashboardData:
    where, params = build_where(filters)
    kpis = dict(
        connection.execute(
            f"""
            SELECT COUNT(*)                                  AS transaction_count,
                   COUNT(DISTINCT student_id)                AS student_count,
                   COALESCE(SUM(amount_cents), 0)            AS total_cents,
                   ROUND(COALESCE(SUM(amount_cents), 0) / 100.0, 2) AS total_kes,
                   ROUND(COALESCE(AVG(amount_cents), 0) / 100.0, 2) AS avg_transaction_kes,
                   COALESCE(SUM(is_anomaly), 0)              AS flagged_count,
                   MIN(transaction_date)                     AS first_date,
                   MAX(transaction_date)                     AS last_date,
                   COALESCE(CAST(julianday(MAX(transaction_date))
                             - julianday(MIN(transaction_date)) + 1 AS INTEGER), 0)
                                                             AS days_covered,
                   COALESCE(ROUND((SUM(amount_cents) / 100.0)
                             / (julianday(MAX(transaction_date))
                                - julianday(MIN(transaction_date)) + 1), 2), 0)
                                                             AS avg_daily_kes
            FROM v_transactions
            WHERE {where}
            """,
            params,
        ).fetchone()
    )

    months = [
        dict(row)
        for row in connection.execute(
            f"""
            SELECT transaction_month,
                   COUNT(DISTINCT student_id) AS active_students,
                   COUNT(*)                  AS transaction_count,
                   SUM(amount_cents) / 100.0 AS total_kes
            FROM v_transactions
            WHERE {where}
            GROUP BY transaction_month
            ORDER BY transaction_month
            """,
            params,
        )
    ]
    categories = [
        dict(row)
        for row in connection.execute(
            f"""
            SELECT category,
                   COUNT(*)                  AS transaction_count,
                   SUM(amount_cents)         AS total_cents,
                   SUM(amount_cents) / 100.0 AS total_kes,
                   ROUND(100.0 * SUM(amount_cents)
                         / SUM(SUM(amount_cents)) OVER (), 2) AS share_pct
            FROM v_transactions
            WHERE {where}
            GROUP BY category
            ORDER BY total_cents DESC, category
            """,
            params,
        )
    ]
    merchants = [
        dict(row)
        for row in connection.execute(
            f"""
            SELECT merchant,
                   COUNT(*)                  AS transaction_count,
                   SUM(amount_cents) / 100.0 AS total_kes
            FROM v_transactions
            WHERE {where}
            GROUP BY merchant
            ORDER BY SUM(amount_cents) DESC, merchant
            LIMIT ?
            """,
            [*params, MERCHANT_LIMIT],
        )
    ]
    payments = [
        dict(row)
        for row in connection.execute(
            f"""
            SELECT payment_method,
                   COUNT(*)                  AS transaction_count,
                   SUM(amount_cents) / 100.0 AS total_kes
            FROM v_transactions
            WHERE {where}
            GROUP BY payment_method
            ORDER BY SUM(amount_cents) DESC, payment_method
            """,
            params,
        )
    ]

    total = int(kpis["transaction_count"])
    page_count = max(1, (total + filters.per_page - 1) // filters.per_page)
    page = min(max(filters.page, 1), page_count)
    offset = (page - 1) * filters.per_page
    transactions = [
        dict(row)
        for row in connection.execute(
            f"""
            SELECT transaction_id,
                   transaction_date,
                   profile_label,
                   student_id,
                   category,
                   merchant,
                   description,
                   payment_method,
                   amount_kes,
                   is_anomaly,
                   anomaly_reason
            FROM v_transactions
            WHERE {where}
            ORDER BY {SORT_CHOICES[filters.sort][1]}
            LIMIT ? OFFSET ?
            """,
            [*params, filters.per_page, offset],
        )
    ]
    first_row = offset + 1 if total else 0
    last_row = offset + len(transactions)

    return DashboardData(
        kpis=kpis,
        months=months,
        categories=categories,
        merchants=merchants,
        payments=payments,
        transactions=transactions,
        page=page,
        page_count=page_count,
        first_row=first_row,
        last_row=last_row,
    )


def load_run(connection: sqlite3.Connection) -> dict:
    row = connection.execute(
        "SELECT run_id, status, finished_at FROM pipeline_runs "
        "ORDER BY rowid DESC LIMIT 1"
    ).fetchone()
    return dict(row) if row is not None else {}


def _href(filters: Filters, *, page: int | None = None) -> str:
    query = urllib.parse.urlencode(filters.to_query(page=page))
    return escape_attr(f"/?{query}" if query else "/")


def _export_href(filters: Filters) -> str:
    query = filters.to_query()
    query.pop("page", None)
    query.pop("per_page", None)
    return escape_attr(f"/export.csv?{urllib.parse.urlencode(query)}")


def _dataset_href(filters: Filters, path: str = "/") -> str:
    if not filters.analysis:
        return escape_attr(path)
    query = urllib.parse.urlencode({"analysis": filters.analysis})
    return escape_attr(f"{path}?{query}")


def _analysis_suffix(analysis: AnalysisWorkspace | None) -> str:
    if analysis is None:
        return ""
    return "?" + urllib.parse.urlencode({"analysis": analysis.analysis_id})


def _kpi_cards(kpis: dict) -> str:
    flagged = int(kpis["flagged_count"])
    cards = [
        ("Total spend", f"KES {money(kpis['total_kes'])}", "matching the current filters"),
        ("Transactions", integer(kpis["transaction_count"]),
         f"{integer(flagged)} flagged for review" if flagged else "none flagged for review"),
        ("Students", integer(kpis["student_count"]), "distinct synthetic profiles"),
        ("Average transaction", f"KES {money(kpis['avg_transaction_kes'])}",
         f"KES {money(kpis['avg_daily_kes'])} per day across "
         f"{integer(kpis['days_covered'])} days"),
    ]
    cells = "".join(
        f'<div class="card"><div class="label">{escape_attr(label)}</div>'
        f'<div class="value">{escape_attr(value)}</div>'
        f'<div class="hint">{escape_attr(hint)}</div></div>'
        for label, value, hint in cards
    )
    return f'<div class="cards dash-cards">{cells}</div>'


def _select_field(
    name: str,
    label: str,
    current: str,
    choices: list[tuple[str, str]],
) -> str:
    options = "".join(
        f'<option value="{escape_attr(value)}"'
        f'{" selected" if value == current else ""}>{escape_attr(text)}</option>'
        for value, text in choices
    )
    return (
        f'<div class="field"><label for="{escape_attr(name)}">{escape_attr(label)}</label>'
        f'<select id="{escape_attr(name)}" name="{escape_attr(name)}">{options}</select></div>'
    )


def _filter_panel(
    filters: Filters,
    options: FilterOptions,
    errors: list[str],
) -> str:
    error_html = ""
    if errors:
        items = " ".join(f"<span>{escape_attr(error)}</span>" for error in errors)
        error_html = f'<div class="banner bad" role="alert"><strong>Check the filters.</strong>{items}</div>'

    student_choices = [("", "All students")] + [
        (str(student["student_id"]), f"{student['profile_label']} ({student['student_id']})")
        for student in options.students
    ]
    category_choices = [("", "All categories")] + [
        (category, category) for category in options.categories
    ]
    payment_choices = [("", "All payment methods")] + [
        (payment, payment) for payment in options.payments
    ]
    flag_choices = list(FLAG_CHOICES.items())
    sort_choices = [(key, value[0]) for key, value in SORT_CHOICES.items()]
    per_page_choices = [(str(size), f"{size} per page") for size in PER_PAGE_CHOICES]

    date_limits = ""
    if options.first_date and options.last_date:
        date_limits = (
            f' min="{escape_attr(options.first_date)}" max="{escape_attr(options.last_date)}"'
        )

    return f"""
  <section class="panel" id="filters" aria-labelledby="filters-title">
    <p class="eyebrow">Filters</p>
    <h2 id="filters-title">Choose what you want to see</h2>
    <p class="lead">Every number below follows these controls. Filters combine, so you
      can narrow to one student, one category and a date window at the same time.</p>
    {error_html}
    <form class="filters" method="get" action="/#summary" aria-labelledby="filters-title">
      {'<input type="hidden" name="analysis" value="' + escape_attr(filters.analysis) + '">' if filters.analysis else ''}
      <div class="field">
        <label for="from">Start date</label>
        <input id="from" name="from" type="date" value="{escape_attr(filters.date_from)}"{date_limits} required>
      </div>
      <div class="field">
        <label for="to">End date</label>
        <input id="to" name="to" type="date" value="{escape_attr(filters.date_to)}"{date_limits} required>
      </div>
      {_select_field("student", "Student", filters.student_id, student_choices)}
      {_select_field("category", "Category", filters.category, category_choices)}
      {_select_field("payment", "Payment method", filters.payment_method, payment_choices)}
      {_select_field("flag", "Review status", filters.flag, flag_choices)}
      {_select_field("sort", "Sort transactions", filters.sort, sort_choices)}
      {_select_field("per_page", "Rows per page", str(filters.per_page), per_page_choices)}
      <div class="field field-search">
        <label for="q">Search merchant or description</label>
        <input id="q" name="q" type="search" maxlength="{SEARCH_LIMIT}"
          value="{escape_attr(filters.search)}" placeholder="e.g. cafeteria"
          autocomplete="off" spellcheck="false">
      </div>
      <div class="actions">
        <button class="button primary" type="submit">Apply filters</button>
        <a class="button ghost" href="{_dataset_href(filters)}">Reset everything</a>
      </div>
      <p class="note">The dashboard reads this warehouse in read-only mode. Filter values
        are not stored; uploaded datasets stay on this machine.</p>
    </form>
  </section>"""


def _active_filter_list(filters: Filters, options: FilterOptions) -> str:
    items: list[str] = []
    if filters.student_id:
        label = next(
            (
                student["profile_label"]
                for student in options.students
                if str(student["student_id"]) == filters.student_id
            ),
            filters.student_id,
        )
        items.append(f"Student: {label}")
    if filters.category:
        items.append(f"Category: {filters.category}")
    if filters.payment_method:
        items.append(f"Payment: {filters.payment_method}")
    if filters.search:
        items.append(f"Search: “{filters.search}”")
    if filters.anomalies_only:
        items.append("Flagged only")
    if filters.sort != "newest":
        items.append(f"Sort: {SORT_CHOICES[filters.sort][0]}")
    if filters.per_page != 25:
        items.append(f"{filters.per_page} rows per page")
    if not items:
        return ""
    chips = "".join(f"<li>{escape_attr(item)}</li>" for item in items)
    return (
        f'<ul class="active-filters" aria-label="Active filters">{chips}'
        f'<li><a class="clear" href="{_dataset_href(filters)}">Clear all</a></li></ul>'
    )


def _plural(count: object, singular: str, plural: str | None = None) -> str:
    return (
        f"{integer(count)} "
        f"{singular if int(count) == 1 else (plural or singular + 's')}"
    )


def _summary_sentence(kpis: dict) -> str:
    total = int(kpis["transaction_count"])
    if total == 0:
        return "No clean transactions match these filters."
    flagged = int(kpis["flagged_count"])
    if flagged:
        flag_text = (
            f"{_plural(flagged, 'transaction')} "
            f"{'is' if flagged == 1 else 'are'} flagged for review."
        )
    else:
        flag_text = "No transactions are flagged for review."
    days = int(kpis["days_covered"])
    verb = "totals" if total == 1 else "total"
    return (
        f"{_plural(total, 'transaction')} from "
        f"{_plural(kpis['student_count'], 'student')} {verb} "
        f"KES {money(kpis['total_kes'])}. The average transaction is "
        f"KES {money(kpis['avg_transaction_kes'])}, and the slice covers "
        f"{_plural(days, 'day')} at KES {money(kpis['avg_daily_kes'])} "
        f"per day. {flag_text}"
    )


def _summary_panel(
    filters: Filters,
    options: FilterOptions,
    data: DashboardData,
) -> str:
    kpis = data.kpis
    total = int(kpis["transaction_count"])
    active = _active_filter_list(filters, options)
    range_text = f"{filters.date_from} to {filters.date_to}"
    if total == 0:
        return f"""
  <section class="panel" id="summary" aria-labelledby="summary-title">
    <p class="eyebrow"><span class="section-no">01</span> Results</p>
    <h2 id="summary-title">Nothing matches yet</h2>
    <p class="lead">{escape_attr(_summary_sentence(kpis))}</p>
    <p class="empty"><strong>Try a wider view.</strong> Extend the date range, choose all
      categories, or clear the search text. The warehouse stays unchanged.</p>
    <p><a class="button primary" href="{_dataset_href(filters)}">Reset the filters</a></p>
    {active}
  </section>"""

    flag_link = ""
    if int(kpis["flagged_count"]) and not filters.anomalies_only:
        flag_query = replace(filters, flag="anomalies", page=1)
        flag_link = (
            '<p class="flag-note">'
            f'<a class="button ghost small" href="{_href(flag_query)}">'
            f'Show only the {integer(kpis["flagged_count"])} flagged</a></p>'
        )
    return f"""
  <section class="panel" id="summary" aria-labelledby="summary-title">
    <p class="eyebrow"><span class="section-no">01</span> Results</p>
    <h2 id="summary-title">What matches</h2>
    <p class="lead">{escape_attr(_summary_sentence(kpis))}</p>
    {_kpi_cards(kpis)}
    <div class="resultbar">
      <p><strong>{escape_attr(range_text)}</strong> · showing
        {integer(data.first_row)}–{integer(data.last_row)} of
        {integer(total)} matching transactions</p>
      <a class="button primary small" href="{_export_href(filters)}" download>
        Download these rows as CSV</a>
    </div>
    {flag_link}
    {active}
  </section>"""


def _pagination(filters: Filters, data: DashboardData) -> str:
    if data.page_count <= 1:
        return ""
    previous = (
        f'<a class="button ghost small" href="{_href(filters, page=data.page - 1)}" '
        'rel="prev">&larr; Previous</a>'
        if data.page > 1
        else '<span class="button ghost small disabled" aria-disabled="true">&larr; Previous</span>'
    )
    following = (
        f'<a class="button ghost small" href="{_href(filters, page=data.page + 1)}" '
        'rel="next">Next &rarr;</a>'
        if data.page < data.page_count
        else '<span class="button ghost small disabled" aria-disabled="true">Next &rarr;</span>'
    )
    return (
        f'<nav class="pager" aria-label="Transaction pages">{previous}'
        f'<span class="page-label">Page {integer(data.page)} of '
        f'{integer(data.page_count)}</span>{following}</nav>'
    )


def _transaction_rows(rows: list[dict]) -> tuple[list[list[str]], list[str]]:
    body: list[list[str]] = []
    classes: list[str] = []
    for row in rows:
        flagged = bool(row["is_anomaly"])
        if flagged:
            reason = escape_attr(row["anomaly_reason"] or "Flagged for review")
            review = f'<span class="pill pill-review" title="{reason}">FLAGGED</span>'
        else:
            review = '<span class="muted">&mdash;</span>'
        body.append(
            [
                escape_attr(row["transaction_date"]),
                escape_attr(row["profile_label"]),
                escape_attr(row["category"]),
                '<span class="cell-merchant">'
                f'<strong>{escape_attr(row["merchant"])}</strong>'
                f'<span class="sub">{escape_attr(row["description"])}</span></span>',
                escape_attr(row["payment_method"]),
                money(row["amount_kes"]),
                review,
            ]
        )
        classes.append("alert" if flagged else "")
    return body, classes


def _transactions_panel(filters: Filters, data: DashboardData) -> str:
    body, classes = _transaction_rows(data.transactions)
    rows = table(
        [("Date", False), ("Student", False), ("Category", False),
         ("Merchant and description", False), ("Payment", False),
         ("Amount KES", True), ("Review", False)],
        body,
        row_classes=classes,
        empty_message="No transactions match these filters.",
    )
    return f"""
  <section class="panel" id="transactions" aria-labelledby="transactions-title">
    <p class="eyebrow"><span class="section-no">02</span> Transactions</p>
    <h2 id="transactions-title">Every matching row</h2>
    <p class="lead">Clean, accepted transactions only. Flagged rows are valid; they are
      unusually large for that student and category, so they stay in the table.</p>
    <div class="table-meta">
      <span>Showing {integer(data.first_row)}–{integer(data.last_row)} of
        {integer(data.kpis['transaction_count'])} rows</span>
      <span>Page {integer(data.page)} of {integer(data.page_count)}</span>
    </div>
    {rows}
    {_pagination(filters, data)}
  </section>"""


def _trend_panel(data: DashboardData) -> str:
    if not data.months:
        return ""
    chart = bar_chart(
        data.months,
        "transaction_month",
        "total_kes",
        title="Monthly spending for the current filters",
        gradient_id="dashboard-monthly",
    )
    rows = [
        [escape_attr(month["transaction_month"]), integer(month["active_students"]),
         integer(month["transaction_count"]), money(month["total_kes"])]
        for month in data.months
    ]
    return f"""
  <section class="panel" id="trend" aria-labelledby="trend-title">
    <p class="eyebrow"><span class="section-no">03</span> Trend</p>
    <h2 id="trend-title">How the filtered spend moved</h2>
    <p class="lead">One bar per month that has rows inside your current filters. The
      table repeats the exact SQL totals.</p>
    {chart}
    {table([("Month", False), ("Students", True), ("Transactions", True),
            ("Total KES", True)], rows)}
  </section>"""


def _breakdown_panel(data: DashboardData) -> str:
    if not data.categories:
        return ""
    category_rows = [
        [escape_attr(category["category"]), integer(category["transaction_count"]),
         money(category["total_kes"]), share_cell(category["share_pct"])]
        for category in data.categories
    ]
    merchant_rows = [
        [escape_attr(merchant["merchant"]), integer(merchant["transaction_count"]),
         money(merchant["total_kes"])]
        for merchant in data.merchants
    ]
    payment_rows = [
        [escape_attr(payment["payment_method"]), integer(payment["transaction_count"]),
         money(payment["total_kes"])]
        for payment in data.payments
    ]
    return f"""
  <section class="panel" id="breakdown" aria-labelledby="breakdown-title">
    <p class="eyebrow"><span class="section-no">04</span> Breakdown</p>
    <h2 id="breakdown-title">Where the filtered money went</h2>
    <p class="lead">Category shares are percentages of the filtered total, so they always
      add up to 100% for the rows you are looking at.</p>
    {table([("Category", False), ("Transactions", True), ("Total KES", True),
            ("Share", True)], category_rows)}
    <div class="split">
      <div>
        <h3>Top merchants</h3>
        <p class="section-note">The {len(merchant_rows)} largest merchants in this slice.</p>
        {table([("Merchant", False), ("Transactions", True), ("Total KES", True)],
               merchant_rows)}
      </div>
      <div>
        <h3>Payment methods</h3>
        <p class="section-note">How these transactions were paid.</p>
        {table([("Method", False), ("Transactions", True), ("Total KES", True)],
               payment_rows)}
      </div>
    </div>
  </section>"""


def _nav(has_results: bool) -> str:
    links = [("filters", "Filters"), ("summary", "Summary")]
    if has_results:
        links.extend(
            [
                ("transactions", "Transactions"),
                ("trend", "Trend"),
                ("breakdown", "Breakdown"),
            ]
        )
    anchors = "".join(
        f'<a href="#{anchor}">{escape_attr(label)}</a>' for anchor, label in links
    )
    return f'<nav class="toc" aria-label="Dashboard sections">{anchors}</nav>'


def _hero(
    run: dict,
    options: FilterOptions,
    transactions: int,
    report_available: bool,
    analysis: AnalysisWorkspace | None,
) -> str:
    status = str(run.get("status", "unknown"))
    dot_class = "status-dot" if status == "success" else "status-dot bad"
    report_link = (
        f'<a class="button ghost" href="/report{_analysis_suffix(analysis)}">'
        "Open the full report</a>"
        if report_available
        else ""
    )
    analysis_chip = (
        f'<li><span class="chip-key">Analysis</span>{escape_attr(analysis.title)}</li>'
        if analysis
        else ""
    )
    scope = "this analysis" if analysis else "the warehouse"
    return f"""
  <header class="hero dash-hero" id="top">
    <p class="eyebrow">Synthetic data &middot; analysis workspace</p>
    <h1>Spending <span>Explorer</span></h1>
    <p class="lede">Filter every clean transaction in {scope} and see the summary,
      monthly trend and breakdown update together. Every figure is a SQL result.</p>
    <div class="hero-actions">
      <a class="button primary" href="/plan">Plan my money</a>
      <a class="button ghost" href="#filters">Start filtering</a>
      {report_link}
      <a class="button ghost" href="/upload">Analyze new data</a>
    </div>
    <ul class="chips">
      {analysis_chip}
      <li><span class="chip-key">Data through</span>{escape_attr(options.last_date or "n/a")}</li>
      <li><span class="chip-key">Warehouse</span>{integer(transactions)} clean
        {("row" if int(transactions) == 1 else "rows")}</li>
      <li><span class="chip-key">Run</span><code>{escape_attr(run.get("run_id", "not run yet"))}</code></li>
      <li><span class="chip-key">Status</span><span class="{dot_class}"></span>
        {escape_attr(status)}</li>
    </ul>
    <p class="disclaimer"><strong>Synthetic data.</strong> Every record was generated for
      a learning exercise. Nothing describes real students, accounts, cards or payments.</p>
  </header>"""


def _analysis_notice(analysis: AnalysisWorkspace | None, report_available: bool) -> str:
    if analysis is None or not analysis.quality_failures:
        return ""
    report_link = (
        f' <a href="/report{_analysis_suffix(analysis)}">Open the full report</a>.'
        if report_available
        else "."
    )
    checks = _plural(analysis.quality_failures, "automated quality check")
    return (
        '<div class="banner bad" role="status"><strong>Quality alert.</strong> '
        f"{checks} failed while building this analysis. The rows are still visible;"
        f" review the evidence before relying on the totals{report_link}</div>"
    )


def _footer(
    run: dict,
    report_available: bool,
    analysis: AnalysisWorkspace | None,
) -> str:
    report_note = (
        f'<a class="totop" href="/report{_analysis_suffix(analysis)}">'
        "Open the full static report</a>"
        if report_available
        else '<span class="section-note">Run <code>student-spending</code> to generate '
             "the full static report.</span>"
    )
    dataset_note = (
        f"This dashboard is showing the uploaded analysis "
        f"<strong>{escape_attr(analysis.title)}</strong> "
        f"(<code>{escape_attr(analysis.analysis_id)}</code>)."
        if analysis
        else "This dashboard is showing the committed synthetic warehouse."
    )
    return f"""
  <footer class="panel footer">
    <p><strong>Read-only by design.</strong> Filters are validated, every value reaches
      SQLite as a bound parameter, and the warehouse is opened with <code>mode=ro</code>.
      Filter values are not written or stored.</p>
    <p class="section-note">{dataset_note}</p>
    <p class="meta-line">Student Spending Analytics &middot; latest run
      <code>{escape_attr(run.get("run_id", "none"))}</code> &middot; finished
      <code>{escape_attr(run.get("finished_at") or "not finished")}</code></p>
    <div class="footer-links">{report_note}
      <a class="totop" href="/plan">Plan your own money</a>
      <a class="totop" href="/upload">Analyze another dataset</a>
      <a class="totop" href="#top">Back to top</a></div>
  </footer>"""


def render_dashboard(
    connection: sqlite3.Connection,
    query: dict[str, list[str]],
    *,
    report_available: bool,
    analysis: AnalysisWorkspace | None = None,
) -> str:
    options = load_options(connection)
    filters, errors = parse_filters(query, options)
    if analysis is not None:
        filters = replace(filters, analysis=analysis.analysis_id)
    data = load_dashboard(connection, filters)
    run = load_run(connection)
    total_warehouse = connection.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]
    has_results = int(data.kpis["transaction_count"]) > 0
    body = f"""
<main class="shell">
  {_hero(run, options, int(total_warehouse), report_available, analysis)}
  {_analysis_notice(analysis, report_available)}
  {_nav(has_results)}
  {_filter_panel(filters, options, errors)}
  {_summary_panel(filters, options, data)}
  {_transactions_panel(filters, data) if has_results else ""}
  {_trend_panel(data) if has_results else ""}
  {_breakdown_panel(data) if has_results else ""}
  {_footer(run, report_available, analysis)}
</main>
"""
    page_title = (
        f"{analysis.title} · Spending Explorer" if analysis else "Spending Explorer"
    )
    return _document(f"{page_title} · Student Spending Analytics", body)


def _csv_safe(value: object) -> str:
    text = "" if value is None else str(value)
    if text[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + text
    return text


def render_csv(connection: sqlite3.Connection, filters: Filters) -> str:
    where, params = build_where(filters)
    rows = connection.execute(
        f"""
        SELECT transaction_id, transaction_date, student_id, profile_label,
               category, merchant, description, payment_method, amount_kes,
               is_anomaly, anomaly_reason
        FROM v_transactions
        WHERE {where}
        ORDER BY {SORT_CHOICES[filters.sort][1]}
        """,
        params,
    )
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(
        ["transaction_id", "transaction_date", "student_id", "profile_label",
         "category", "merchant", "description", "payment_method", "amount_kes",
         "is_anomaly", "anomaly_reason"]
    )
    for row in rows:
        writer.writerow(
            [
                _csv_safe(row["transaction_id"]),
                _csv_safe(row["transaction_date"]),
                _csv_safe(row["student_id"]),
                _csv_safe(row["profile_label"]),
                _csv_safe(row["category"]),
                _csv_safe(row["merchant"]),
                _csv_safe(row["description"]),
                _csv_safe(row["payment_method"]),
                f"{float(row['amount_kes']):.2f}",
                "yes" if row["is_anomaly"] else "no",
                _csv_safe(row["anomaly_reason"]),
            ]
        )
    return buffer.getvalue()


def _upload_errors(errors: list[str]) -> str:
    if not errors:
        return ""
    items = " ".join(f"<span>{escape_attr(error)}</span>" for error in errors)
    return f'<div class="banner bad" role="alert"><strong>Check the upload.</strong>{items}</div>'


def _file_field(field: str, *, full: bool = False) -> str:
    label, columns, _ = FILE_FIELDS[field]
    required = ", ".join(columns)
    return f"""
      <div class="field{' field-full' if full else ''}">
        <label for="{escape_attr(field)}">{escape_attr(label)} <span class="section-note">required</span></label>
        <input id="{escape_attr(field)}" name="{escape_attr(field)}" type="file"
          accept=".csv,text/csv" required>
        <p class="columns">Required columns: {escape_attr(required)}</p>
      </div>"""


def _format_created(created_at: str) -> str:
    text = created_at.strip()
    if len(text) >= 16 and text[10] == "T":
        return text[:16].replace("T", " ") + " UTC"
    return text or "unknown time"


def _recent_analyses(analyses: list[AnalysisWorkspace]) -> str:
    if not analyses:
        return (
            '<p class="recent-empty">No uploaded analyses yet. The committed sample '
            "warehouse is still available from the dashboard.</p>"
        )
    items = []
    for analysis in analyses:
        if analysis.status == "quality_failed":
            status = '<span class="pill fail">quality alert</span>'
        else:
            status = '<span class="pill pass">success</span>'
        report_link = (
            f'<a class="button ghost small" href="/report{_analysis_suffix(analysis)}">'
            "Report</a>"
            if analysis.report_path.is_file()
            else ""
        )
        source = analysis.inputs.get("transactions", {})
        source_name = source.get("filename") if isinstance(source, dict) else ""
        source_rows = source.get("rows") if isinstance(source, dict) else ""
        source_note = ""
        if source_name:
            source_note = (
                f'<span class="section-note">{escape_attr(source_name)}'
                f' · {integer(source_rows)} rows</span>'
            )
        items.append(
            f"""
      <li>
        <div class="recent-main"><strong>{escape_attr(analysis.title)}</strong>{status}</div>
        <p class="recent-meta"><code>{escape_attr(analysis.analysis_id)}</code>
          · {escape_attr(_format_created(analysis.created_at))}
          · {integer(analysis.rows_accepted)} accepted rows</p>
        <div class="recent-actions">
          <a class="button primary small" href="/{_analysis_suffix(analysis)}">Open analysis</a>
          {report_link}{source_note}
        </div>
      </li>"""
        )
    return f'<ul class="recent-list">{"".join(items)}</ul>'


def render_upload_page(
    *,
    analyses: list[AnalysisWorkspace],
    errors: list[str] | None = None,
    title: str = "",
    current_analysis: AnalysisWorkspace | None = None,
) -> str:
    back_link = (
        f'<a class="button ghost" href="/{_analysis_suffix(current_analysis)}">'
        "Open current analysis</a>"
        if current_analysis
        else '<a class="button ghost" href="/">Open the sample dashboard</a>'
    )
    file_bytes = MAX_FILE_BYTES // (1024 * 1024)
    body = f"""
<main class="shell">
  <header class="hero dash-hero" id="top">
    <p class="eyebrow">Synthetic data &middot; build an analysis</p>
    <h1>Analyze <span>your data</span></h1>
    <p class="lede">Upload one transactions CSV and the pipeline validates every row,
      derives the student list, loads an isolated warehouse and opens the same
      filterable dashboard. Nothing is uploaded to a remote service.</p>
    <div class="hero-actions">
      <a class="button primary" href="#upload-form">Upload a CSV</a>
      <a class="button ghost" href="/plan">Plan my own money</a>
      {back_link}
    </div>
    <p class="disclaimer"><strong>Synthetic data only.</strong> Do not upload real
      student, account, card or payment information. Every analysis is built for a
      learning exercise.</p>
  </header>

  <nav class="toc" aria-label="Analysis workspace sections">
    <a href="#upload-form">Upload</a><a href="#recent">Recent analyses</a>
  </nav>

  <div class="upload-grid">
    <section class="panel" id="upload-form" aria-labelledby="upload-title">
      <p class="eyebrow">New analysis</p>
      <h2 id="upload-title">One CSV, one analysed warehouse</h2>
      <p class="lead">The transactions file is the only input. Student labels come from
        <code>student_id</code>, so there is no separate profile file, and budget
        variance is skipped. Download the sample below for a known-good starting point.</p>
      {_upload_errors(errors or [])}
      <form class="upload-form" method="post" action="/upload" enctype="multipart/form-data">
        <div class="field field-full">
          <label for="analysis-title">Analysis name <span class="section-note">optional</span></label>
          <input id="analysis-title" name="title" type="text" maxlength="{MAX_TITLE_LENGTH}"
            value="{escape_attr(title)}" placeholder="e.g. October spending"
            autocomplete="off">
        </div>
        {_file_field("transactions", full=True)}
        <div class="field-full sample-links">
          <span>Sample input:</span>
          <a href="/samples/student_expenses.csv" download>transactions</a>
        </div>
        <label class="check-field">
          <input type="checkbox" name="synthetic" value="yes" required>
          <span><strong>I confirm this file is synthetic.</strong> It contains no real
            student, account, card or payment details.</span>
        </label>
        <div class="actions">
          <button class="button primary" type="submit">Run analysis</button>
          <span class="section-note">The pipeline runs immediately; this may take a moment.</span>
        </div>
        <p class="upload-note">Limits: one .csv file, {file_bytes} MB and
          {MAX_CSV_ROWS:,} data rows. Files are saved locally under
          <code>data/uploads/</code>; each analysis gets its own database and report.
          No profiles or budgets file is required.</p>
      </form>
    </section>

    <aside class="panel" id="recent" aria-labelledby="recent-title">
      <p class="eyebrow">History</p>
      <h2 id="recent-title">Recent analyses</h2>
      <p class="lead">Only analyses that completed loading appear here. Each one keeps
        its inputs, SQLite warehouse and report on this machine.</p>
      {_recent_analyses(analyses)}
      <ol class="upload-steps">
        <li><strong>Check</strong> the headers, encoding, row count and size.</li>
        <li><strong>Build</strong> the warehouse with the normal pipeline.</li>
        <li><strong>Explore</strong> the dashboard, CSV export and quality report.</li>
      </ol>
    </aside>
  </div>

  <footer class="panel footer">
    <p><strong>Local and read-only after loading.</strong> The upload and money-plan
      endpoints are the only write paths; analysis pages open SQLite with
      <code>mode=ro</code>. There is no login, so keep the server on loopback.</p>
    <p class="meta-line">Student Spending Analytics &middot; synthetic data only</p>
    <div class="footer-links">
      <a class="totop" href="/">Open the sample dashboard</a>
      <a class="totop" href="/plan">Plan your own money</a>
      <a class="totop" href="#top">Back to top</a>
    </div>
  </footer>
</main>
"""
    return _document("Analyze data · Student Spending Analytics", body, skip_href=None)


def _plan_error_banner(errors: list[str]) -> str:
    if not errors:
        return ""
    items = "".join(f"<li>{escape_attr(error)}</li>" for error in errors)
    return (
        '<div class="banner bad" role="alert"><strong>Check these details.</strong>'
        f'<ul class="error-list">{items}</ul></div>'
    )


def _category_row(number: int, row: object) -> str:
    essential = bool(getattr(row, "essential", False))
    return f"""
      <div class="plan-row cat-cols">
        <span class="row-no" aria-hidden="true">{number:02d}</span>
        <input name="category_name_{number}" type="text" maxlength="{MAX_CATEGORY_NAME_LENGTH}"
          value="{escape_attr(getattr(row, 'name', ''))}" placeholder="e.g. Food"
          aria-label="Category {number} name" autocomplete="off">
        <input name="category_amount_{number}" type="text" inputmode="decimal"
          value="{escape_attr(getattr(row, 'planned', ''))}" placeholder="0.00"
          aria-label="Category {number} planned amount in KES">
        <select name="category_essential_{number}" aria-label="Category {number} type">
          <option value="essential"{" selected" if essential else ""}>Essential</option>
          <option value="flexible"{" selected" if not essential else ""}>Flexible</option>
        </select>
      </div>"""


def _spending_row(number: int, row: object) -> str:
    return f"""
      <div class="plan-row spend-cols">
        <span class="row-no" aria-hidden="true">{number:02d}</span>
        <input name="spending_date_{number}" type="date"
          value="{escape_attr(getattr(row, 'spent_on', ''))}"
          aria-label="Spending row {number} date">
        <input name="spending_category_{number}" type="text"
          maxlength="{MAX_CATEGORY_NAME_LENGTH}"
          value="{escape_attr(getattr(row, 'category', ''))}" placeholder="Your category"
          aria-label="Spending row {number} category" autocomplete="off">
        <input name="spending_amount_{number}" type="text" inputmode="decimal"
          value="{escape_attr(getattr(row, 'amount', ''))}" placeholder="0.00"
          aria-label="Spending row {number} amount in KES">
        <input name="spending_note_{number}" type="text"
          maxlength="{MAX_ENTRY_NOTE_LENGTH}"
          value="{escape_attr(getattr(row, 'note', ''))}" placeholder="Optional note"
          aria-label="Spending row {number} note" autocomplete="off">
      </div>"""


def _add_row_control(
    *,
    section: str,
    action: str,
    noun: str,
    rows: int,
    maximum: int,
    label: str,
) -> str:
    if rows >= maximum:
        return (
            f'<span class="section-note">{maximum} {noun} rows is the maximum.</span>'
        )
    return (
        '<div class="plan-add">'
        f'<span class="section-note">{rows} of {maximum} {noun} rows</span>'
        '<button class="button ghost plan-add-button" type="submit" '
        f'name="action" value="{action}" formaction="/plan#{section}" formnovalidate '
        f'aria-label="{label}" title="{label}">'
        '<span aria-hidden="true">+</span></button>'
        "</div>"
    )


def render_plan_page(
    *,
    draft: PlanDraft | None = None,
    errors: list[str] | None = None,
    source: SavedPlan | None = None,
    category_rows: int = CATEGORY_ROWS,
    spending_rows: int = SPENDING_ROWS,
) -> str:
    draft = draft or PlanDraft()
    errors = errors or []
    category_rows = min(
        max(CATEGORY_ROWS, len(draft.categories), category_rows), MAX_CATEGORIES
    )
    spending_rows = min(
        max(SPENDING_ROWS, len(draft.spendings), spending_rows), MAX_SPENDINGS
    )
    categories_html = "".join(
        _category_row(number, draft.category(number))
        for number in range(1, category_rows + 1)
    )
    spendings_html = "".join(
        _spending_row(number, draft.spending(number))
        for number in range(1, spending_rows + 1)
    )
    source_note = ""
    if source is not None:
        source_note = (
            '<div class="banner note" role="status"><strong>Editing a copy.</strong> '
            f"This form is filled from plan <code>{escape_attr(source.plan_id)}</code>. "
            "Submitting saves a new link; the original plan stays unchanged.</div>"
        )
    back_link = (
        f'<a class="button ghost" href="/plan?plan={escape_attr(source.plan_id)}">'
        "Back to the saved result</a>"
        if source is not None
        else '<a class="button ghost" href="/">Explore the sample dataset</a>'
    )
    add_category = _add_row_control(
        section="categories",
        action="add_category",
        noun="category",
        rows=category_rows,
        maximum=MAX_CATEGORIES,
        label="Add another category",
    )
    add_spending = _add_row_control(
        section="spending",
        action="add_spending",
        noun="spending",
        rows=spending_rows,
        maximum=MAX_SPENDINGS,
        label="Add another spending row",
    )
    body = f"""
<main class="shell">
  <header class="hero dash-hero" id="top">
    <p class="eyebrow">One student &middot; local money plan</p>
    <h1>Plan your <span>money</span></h1>
    <p class="lede">Enter the money you have, name your own categories, and record what
      you actually spent. The analysis compares your plan with your entries and charts
      where the money went.</p>
    <div class="hero-actions">
      <a class="button primary" href="#money">Start with the money</a>
      {back_link}
    </div>
    <p class="disclaimer"><strong>Made-up numbers only.</strong> This is a learning tool.
      Do not enter account numbers, card details or payment credentials. Nothing is sent
      to a bank or a remote service; saved plans stay on this machine.</p>
  </header>

  <nav class="toc" aria-label="Money plan sections">
    <a href="#money">Money</a><a href="#categories">Categories</a>
    <a href="#spending">Spending</a><a href="#review">Review</a>
  </nav>

  {source_note}

  <form class="plan-form" method="post" action="/plan" accept-charset="utf-8">
    <input type="hidden" name="category_rows" value="{category_rows}">
    <input type="hidden" name="spending_rows" value="{spending_rows}">
    <section class="panel" id="money" aria-labelledby="money-title">
      <p class="eyebrow"><span class="section-no">01</span> Money</p>
      <h2 id="money-title">What you have and how you plan</h2>
      <p class="lead">Start with a display name and the money available for the period
        you are planning. The budgeting method is a label for your approach; the
        category amounts are what the comparison uses.</p>
      {_plan_error_banner(errors)}
      <div class="plan-grid">
        <div class="field">
          <label for="student_name">Display name</label>
          <input id="student_name" name="student_name" type="text"
            maxlength="{MAX_NAME_LENGTH}" value="{escape_attr(draft.student_name)}"
            placeholder="A nickname is fine" autocomplete="off">
        </div>
        <div class="field">
          <label for="money_available">Money available (KES)</label>
          <input id="money_available" name="money_available" type="text"
            inputmode="decimal" value="{escape_attr(draft.money_available)}"
            placeholder="e.g. 18,000">
        </div>
        {_select_field("method", "Budgeting method", draft.method,
                       list(BUDGET_METHODS.items()))}
        <div class="field field-full">
          <label for="method_note">How you budget <span class="section-note">optional</span></label>
          <textarea id="method_note" name="method_note"
            maxlength="{MAX_METHOD_NOTE_LENGTH}"
            placeholder="e.g. I split my money into weekly envelopes and put rent aside first.">{escape_attr(draft.method_note)}</textarea>
        </div>
      </div>
      <p class="plan-section-note">Amounts are in KES. Commas and a decimal point are
        fine: 18,000 or 18,000.50. This is the money you are planning with, not a bank
        balance.</p>
    </section>

    <section class="panel" id="categories" aria-labelledby="categories-title">
      <p class="eyebrow"><span class="section-no">02</span> Categories</p>
      <div class="plan-title-row">
        <h2 id="categories-title">Name your own categories</h2>
        {add_category}
      </div>
      <p class="lead">There is no fixed category list: use the names you think in.
        Add a planned amount if you have one, and mark each category Essential or
        Flexible. Use + to add more rows. Blank rows are ignored; at least two
        categories are needed.</p>
      <div class="plan-rows">
        <div class="plan-row-head cat-cols">
          <span>#</span><span>Category name</span><span>Planned KES</span><span>Type</span>
        </div>
        {categories_html}
      </div>
      <p class="plan-section-note">Leaving Planned KES blank means zero for that
        category. Spending in a category with a zero plan is still included, and the
        analysis marks it as having no plan.</p>
    </section>

    <section class="panel" id="spending" aria-labelledby="spending-title">
      <p class="eyebrow"><span class="section-no">03</span> Spending</p>
      <div class="plan-title-row">
        <h2 id="spending-title">What you actually spent</h2>
        {add_spending}
      </div>
      <p class="lead">One row per purchase or payment. Use a category name from above;
        matching ignores capitalisation. Use + to add more rows. Leave any row blank
        if you do not need it.</p>
      <div class="plan-rows">
        <div class="plan-row-head spend-cols">
          <span>#</span><span>Date</span><span>Category</span>
          <span>Amount KES</span><span>Note</span>
        </div>
        {spendings_html}
      </div>
      <p class="plan-section-note">At least one complete spending row is needed.
        Dates use YYYY-MM-DD in the browser's date picker.</p>
    </section>

    <section class="panel" id="review" aria-labelledby="review-title">
      <p class="eyebrow"><span class="section-no">04</span> Review</p>
      <h2 id="review-title">Run the analysis</h2>
      <p class="lead">The analysis adds up only the values in this form. It will show
        your totals, every category against its plan, and graphs of where the money
        went.</p>
      <label class="check-field">
        <input type="checkbox" name="synthetic" value="yes"{" checked" if draft.synthetic else ""} required>
        <span><strong>These are made-up learning numbers.</strong> There are no real
          student, account, card or payment details in this form.</span>
      </label>
      <div class="plan-actions">
        <button class="button primary" type="submit">Run my analysis</button>
        <a class="button ghost" href="/plan">Clear the form</a>
        <span class="section-note">Saving creates a private result link on this machine.</span>
      </div>
      <p class="plan-section-note">Plans are stored as JSON under
        <code>data/plans/</code>. They are not listed, mailed or sent anywhere, and
        no login is involved. Keep the result link if you want to return.</p>
    </section>
  </form>

  <footer class="panel footer">
    <p><strong>Local by design.</strong> The form is validated on the server, amounts
      are stored as integer cents, and the result page only reads the saved plan. There
      is no bank connection and no credential field anywhere.</p>
    <p class="meta-line">Student Spending Analytics &middot; money plan &middot;
      made-up numbers only</p>
    <div class="footer-links">
      <a class="totop" href="/">Explore the sample dataset</a>
      <a class="totop" href="/upload">Analyze a transactions CSV</a>
      <a class="totop" href="#top">Back to top</a>
    </div>
  </footer>
</main>
"""
    return _document("Plan your money · Student Spending Analytics", body, skip_href=None)


def _plan_summary(plan: object, analysis: object) -> str:
    return (
        f"{plan.student_name} has KES {money(analysis.money_available_cents / 100)} "
        f"available, planned KES {money(analysis.planned_cents / 100)} across "
        f"{integer(len(plan.categories))} categories, and recorded "
        f"{integer(len(plan.spendings))} spending entries totalling "
        f"KES {money(analysis.spent_cents / 100)}."
    )


def _plan_cards(plan: object, analysis: object) -> str:
    if analysis.planned_cents:
        planned_hint = (
            f"{integer(len(plan.categories))} categories · "
            f"{percent(analysis.planned_share_pct)} of available"
        )
    else:
        planned_hint = f"{integer(len(plan.categories))} categories · no planned amounts"
    remaining = analysis.remaining_cents
    left_value = (
        f"KES {money(remaining / 100)}"
        if remaining >= 0
        else f"-KES {money(-remaining / 100)}"
    )
    cards = [
        ("Money available", f"KES {money(analysis.money_available_cents / 100)}",
         "the amount you entered"),
        ("Planned", f"KES {money(analysis.planned_cents / 100)}", planned_hint),
        ("Spent", f"KES {money(analysis.spent_cents / 100)}",
         f"{integer(len(plan.spendings))} entries · "
         f"{percent(analysis.spent_share_pct)} of available"),
        ("Left", left_value,
         "still unspent" if remaining >= 0 else "more than available"),
    ]
    cells = "".join(
        f'<div class="card"><div class="label">{escape_attr(label)}</div>'
        f'<div class="value">{escape_attr(value)}</div>'
        f'<div class="hint">{escape_attr(hint)}</div></div>'
        for label, value, hint in cards
    )
    return f'<div class="cards plan-cards">{cells}</div>'


def _plan_banners(plan: object, analysis: object) -> str:
    banners: list[tuple[str, str, str]] = []
    if analysis.remaining_cents > 0:
        banners.append(
            ("good", "Money available",
             f"KES {money(analysis.remaining_cents / 100)} of the money available is still unspent.")
        )
    elif analysis.remaining_cents == 0:
        banners.append(
            ("good", "Money available",
             "Recorded spending uses exactly the money available.")
        )
    else:
        banners.append(
            ("bad", "Money available",
             f"Recorded spending is KES {money(-analysis.remaining_cents / 100)} more than the money available.")
        )
    if analysis.planned_cents == 0:
        banners.append(
            ("note", "Plan",
             "No planned amounts were entered, so this analysis compares actual spending only.")
        )
    elif analysis.unallocated_cents < 0:
        banners.append(
            ("bad", "Plan",
             f"The plan allocates KES {money(-analysis.unallocated_cents / 100)} more than the money available.")
        )
    elif analysis.unallocated_cents == 0:
        banners.append(
            ("good", "Plan", "The plan allocates exactly the money available.")
        )
    else:
        banners.append(
            ("note", "Plan",
             f"The plan leaves KES {money(analysis.unallocated_cents / 100)} unallocated; it can be a buffer.")
        )
    return "".join(
        f'<div class="banner {kind}" role="status"><strong>{escape_attr(label)}.</strong> '
        f"{escape_attr(text)}</div>"
        for kind, label, text in banners
    )


def _names(items: list | tuple, limit: int = 4) -> str:
    names = [item.name for item in items]
    if len(names) > limit:
        return ", ".join(names[:limit]) + f" and {len(names) - limit} more"
    return ", ".join(names)


def _plan_insights(plan: object, analysis: object) -> str:
    items: list[str] = []
    biggest = analysis.ranked_categories[0]
    if biggest.spent_cents:
        items.append(
            f"{biggest.name} is the largest category: "
            f"KES {money(biggest.spent_cents / 100)} "
            f"({percent(biggest.share_pct)} of recorded spending)."
        )
    if analysis.over_plan:
        over_total = sum(
            item.spent_cents - item.planned_cents for item in analysis.over_plan
        )
        count = len(analysis.over_plan)
        verb = "category is" if count == 1 else "categories are"
        items.append(
            f"{count} {verb} over plan by "
            f"KES {money(over_total / 100)} in total: "
            f"{_names(analysis.over_plan)}."
        )
    elif analysis.planned_cents:
        items.append("Every category with a planned amount is at or under its plan.")
    if analysis.unplanned:
        unplanned_total = sum(item.spent_cents for item in analysis.unplanned)
        items.append(
            f"KES {money(unplanned_total / 100)} of spending has no planned amount: "
            f"{_names(analysis.unplanned)}."
        )
    if analysis.planned_cents:
        essential_plan_share = 100.0 * analysis.essential_planned_cents / analysis.planned_cents
        items.append(
            f"Essential categories are {percent(analysis.essential_share_pct)} of "
            f"spending (KES {money(analysis.essential_spent_cents / 100)}) and "
            f"{percent(essential_plan_share)} of the plan "
            f"(KES {money(analysis.essential_planned_cents / 100)})."
        )
    else:
        items.append(
            f"Essential categories are {percent(analysis.essential_share_pct)} of "
            f"spending (KES {money(analysis.essential_spent_cents / 100)})."
        )
    day_word = "day" if analysis.days_covered == 1 else "days"
    active_word = "day" if analysis.active_days == 1 else "days"
    items.append(
        f"Your entries cover {integer(analysis.days_covered)} {day_word} "
        f"({integer(analysis.active_days)} {active_word} with spending), averaging "
        f"KES {money(analysis.average_daily_cents / 100)} per day."
    )
    if analysis.planned_cents and analysis.unallocated_cents > 0:
        items.append(
            f"KES {money(analysis.unallocated_cents / 100)} of the money available is "
            "not assigned to a category plan yet."
        )
    list_html = "".join(f"<li>{escape_attr(item)}</li>" for item in items)
    return f'<ul class="insight-list">{list_html}</ul>'


def _plan_category_panel(plan: object, analysis: object) -> str:
    actual_items = [
        {"category": item.name, "spent_kes": item.spent_cents / 100}
        for item in analysis.ranked_categories
        if item.spent_cents
    ]
    compare_items = [
        {
            "category": item.name,
            "planned_kes": item.planned_cents / 100,
            "spent_kes": item.spent_cents / 100,
        }
        for item in analysis.ranked_categories
        if item.planned_cents or item.spent_cents
    ]
    actual_chart = bar_chart(
        actual_items,
        "category",
        "spent_kes",
        title="Spending by category",
        gradient_id="plan-actual",
    )
    compare_chart = grouped_bar_chart(
        compare_items,
        "category",
        [
            ("planned_kes", "Planned", "#c4b5fd", "#a78bfa"),
            ("spent_kes", "Spent", "#7c3aed", "#d946ef"),
        ],
        title="Planned and actual spending by category",
        gradient_prefix="plan-compare",
    )

    pill_classes = {
        "Under plan": "pass",
        "On plan": "pass",
        "Over plan": "fail",
        "No plan": "warn",
        "Not used": "neutral",
        "No activity": "neutral",
    }
    rows: list[list[str]] = []
    row_classes: list[str] = []
    for item in analysis.categories:
        if item.difference_cents < 0:
            difference = f"-{money(-item.difference_cents / 100)}"
        else:
            difference = money(item.difference_cents / 100)
        category = (
            f"{escape_attr(item.name)}"
            f'<span class="plan-tag">{"Essential" if item.essential else "Flexible"}</span>'
        )
        rows.append(
            [
                category,
                money(item.planned_cents / 100),
                money(item.spent_cents / 100),
                difference,
                share_cell(item.share_pct),
                f'<span class="pill {pill_classes[item.status]}">'
                f"{escape_attr(item.status)}</span>",
            ]
        )
        row_classes.append("over" if item.flagged else "")

    essential_rows = [
        ["Essential", money(analysis.essential_planned_cents / 100),
         money(analysis.essential_spent_cents / 100),
         share_cell(analysis.essential_share_pct)],
        ["Flexible", money(analysis.flexible_planned_cents / 100),
         money(analysis.flexible_spent_cents / 100),
         share_cell(100.0 - analysis.essential_share_pct)],
    ]
    return f"""
  <section class="panel" id="categories" aria-labelledby="categories-title">
    <p class="eyebrow"><span class="section-no">02</span> Categories</p>
    <h2 id="categories-title">Where the money went</h2>
    <p class="lead">The first graph ranks your own categories by actual spending. The
      second puts each category's plan next to its actual spend on the same scale.</p>
    <h3>Spending by category</h3>
    {actual_chart}
    <h3>Plan next to actual</h3>
    {compare_chart}
    <h3>The numbers by category</h3>
    {table([("Category", False), ("Planned KES", True), ("Spent KES", True),
            ("Planned minus spent", True), ("Share of spending", True),
            ("Status", False)], rows, row_classes=row_classes)}
    <div class="plan-split">
      <div>
        <h3>Essential and flexible</h3>
        <p class="section-note">The split you chose while entering the categories.</p>
        {table([("Bucket", False), ("Planned KES", True), ("Spent KES", True),
                ("Share of spending", True)], essential_rows)}
      </div>
      <div>
        <h3>How to read it</h3>
        <p class="section-note">Planned minus spent is positive when a category still
          has money and negative when it is over. "No plan" means spending was recorded
          against a category with a zero planned amount. "Not used" is a planned category
          with no entries. Every figure comes from the values in this saved plan.</p>
      </div>
    </div>
  </section>"""


def _plan_spending_panel(plan: object, analysis: object) -> str:
    entries = sorted(
        plan.spendings,
        key=lambda entry: (entry.spent_on, entry.category, entry.amount_cents),
        reverse=True,
    )
    rows = [
        [
            escape_attr(entry.spent_on.isoformat()),
            escape_attr(entry.category),
            escape_attr(entry.note or "—"),
            money(entry.amount_cents / 100),
        ]
        for entry in entries
    ]
    return f"""
  <section class="panel" id="spending" aria-labelledby="spending-title">
    <p class="eyebrow"><span class="section-no">03</span> Entries</p>
    <h2 id="spending-title">The spending behind the totals</h2>
    <p class="lead">Newest first. These rows are the source of every category total and
      graph above.</p>
    <div class="table-meta">
      <span>{integer(len(rows))} entries</span>
      <span>KES {money(analysis.spent_cents / 100)} total</span>
      <span>{escape_attr(analysis.first_date.isoformat())} to
        {escape_attr(analysis.last_date.isoformat())}</span>
    </div>
    {table([("Date", False), ("Category", False), ("Note", False),
            ("Amount KES", True)], rows)}
  </section>"""


def _plan_method_panel(saved: SavedPlan) -> str:
    method_label = BUDGET_METHODS[saved.plan.method]
    note = (
        f'<p class="method-note">{escape_attr(saved.plan.method_note)}</p>'
        if saved.plan.method_note
        else '<p class="section-note">No budgeting note was added.</p>'
    )
    return f"""
  <section class="panel" id="method" aria-labelledby="method-title">
    <p class="eyebrow"><span class="section-no">04</span> Method</p>
    <h2 id="method-title">How you planned</h2>
    <p class="plan-meta">
      <span>Method: <strong>{escape_attr(method_label)}</strong></span>
      <span>Saved: <strong>{escape_attr(_format_created(saved.created_at))}</strong></span>
      <span>Plan id: <code>{escape_attr(saved.plan_id)}</code></span>
    </p>
    {note}
    <p class="lead">The analysis does not score your budgeting method or recommend
      financial products. It only compares the categories and amounts you entered with
      the spending entries you recorded.</p>
    <div class="plan-actions">
      <a class="button primary" href="/plan?edit={escape_attr(saved.plan_id)}">Edit as a copy</a>
      <a class="button ghost" href="/plan">Start a new plan</a>
    </div>
    <p class="plan-section-note">Stored as <code>data/plans/{escape_attr(saved.plan_id)}.json</code>
      on this machine. Plans are not listed anywhere, so this result link is the only
      way back to it.</p>
  </section>"""


def render_plan_result(saved: SavedPlan) -> str:
    plan = saved.plan
    analysis = analyse(plan)
    method_label = BUDGET_METHODS[plan.method]
    summary = _plan_summary(plan, analysis)
    body = f"""
<main class="shell">
  <header class="hero dash-hero" id="top">
    <p class="eyebrow">Saved money plan &middot; local only</p>
    <h1>Money map for <span>{escape_attr(plan.student_name)}</span></h1>
    <p class="lede">{escape_attr(summary)}</p>
    <div class="hero-actions">
      <a class="button primary" href="#summary">See the analysis</a>
      <a class="button ghost" href="/plan?edit={escape_attr(saved.plan_id)}">Edit as a copy</a>
      <a class="button ghost" href="/plan">Start a new plan</a>
    </div>
    <ul class="chips">
      <li><span class="chip-key">Method</span>{escape_attr(method_label)}</li>
      <li><span class="chip-key">Categories</span>{integer(len(plan.categories))}</li>
      <li><span class="chip-key">Entries</span>{integer(len(plan.spendings))}</li>
      <li><span class="chip-key">Saved</span>{escape_attr(_format_created(saved.created_at))}</li>
      <li><span class="chip-key">Plan link</span><code>{escape_attr(saved.plan_id)}</code></li>
    </ul>
    <p class="disclaimer"><strong>Made-up numbers only.</strong> This page compares
      values typed into the form. It never connects to a bank, card or payment account
      and stores nothing outside this machine.</p>
  </header>

  <nav class="toc" aria-label="Money plan result sections">
    <a href="#summary">Summary</a><a href="#categories">Categories</a>
    <a href="#spending">Entries</a><a href="#method">Method</a>
  </nav>

  <section class="panel" id="summary" aria-labelledby="summary-title">
    <p class="eyebrow"><span class="section-no">01</span> Analysis</p>
    <h2 id="summary-title">What the numbers say</h2>
    <p class="lead">{escape_attr(summary)}</p>
    {_plan_cards(plan, analysis)}
    {_plan_banners(plan, analysis)}
    <h3>What stands out</h3>
    {_plan_insights(plan, analysis)}
  </section>

  {_plan_category_panel(plan, analysis)}
  {_plan_spending_panel(plan, analysis)}
  {_plan_method_panel(saved)}

  <footer class="panel footer">
    <p><strong>Local and private by default.</strong> This plan is a JSON file on this
      machine. There is no account, no bank connection and no place to enter a card or
      payment credential.</p>
    <p class="section-note">The link for this plan is
      <code>/plan?plan={escape_attr(saved.plan_id)}</code>. Plans are not listed, so keep
      the link if you want to return. Delete <code>data/plans/</code> to clear saved
      plans.</p>
    <p class="meta-line">Student Spending Analytics &middot; money plan &middot;
      saved {escape_attr(_format_created(saved.created_at))}</p>
    <div class="footer-links">
      <a class="totop" href="/plan?edit={escape_attr(saved.plan_id)}">Edit as a copy</a>
      <a class="totop" href="/">Explore the sample dashboard</a>
      <a class="totop" href="#top">Back to top</a>
    </div>
  </footer>
</main>
"""
    return _document(
        f"{plan.student_name} · Money plan · Student Spending Analytics", body
    )


def connect_readonly(db_path: Path) -> sqlite3.Connection:
    """Open the warehouse so a bug in a handler cannot modify it."""
    uri = db_path.resolve().as_uri() + "?mode=ro"
    connection = sqlite3.connect(uri, uri=True)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only = ON")
    return connection


class DashboardServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address: tuple[str, int], *, db_path: Path, report_path: Path):
        super().__init__(address, DashboardHandler)
        self.db_path = db_path
        self.report_path = report_path


class DashboardHandler(BaseHTTPRequestHandler):
    server: DashboardServer
    server_version = "StudentSpendingDashboard/1.4.4"
    sys_version = ""
    timeout = 30

    def log_message(self, format: str, *args: object) -> None:
        logger.debug("%s - %s", self.address_string(), format % args)

    def do_GET(self) -> None:  # noqa: N802 - required by http.server
        self._dispatch(head_only=False)

    def do_HEAD(self) -> None:  # noqa: N802 - required by http.server
        self._dispatch(head_only=True)

    def do_POST(self) -> None:  # noqa: N802 - required by http.server
        path = urllib.parse.urlsplit(self.path).path
        try:
            if path == "/upload":
                self._create_analysis()
            elif path == "/plan":
                self._create_plan()
            else:
                self._method_not_allowed()
        except Exception:  # noqa: BLE001 - one bad request must not stop the server
            logger.exception("unexpected POST failure for %s", path)
            action = "/plan" if path == "/plan" else "/upload"
            self._safe_send(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                _error_document(
                    "The request could not be completed",
                    "An unexpected error interrupted this request. Check the server "
                    "log, then try again.",
                    action_href=action,
                    action_label="Back to the form",
                ),
                head_only=False,
            )

    do_PUT = do_POST
    do_PATCH = do_POST
    do_DELETE = do_POST

    def _method_not_allowed(self) -> None:
        body = _error_document(
            "Read-only dashboard",
            "This address only answers GET requests. Use the filter form on the "
            "dashboard, or submit the money-plan form from /plan.",
        )
        self._send(HTTPStatus.METHOD_NOT_ALLOWED, body,
                   headers=[("Allow", "GET, HEAD")])

    def _no_content(self) -> None:
        self.send_response(HTTPStatus.NO_CONTENT)
        self.send_header("Cache-Control", "no-store")
        self.end_headers()

    def _send(self, status: int, body: str, *, headers: list[tuple[str, str]] | None = None,
              content_type: str = "text/html; charset=utf-8",
              head_only: bool = False) -> None:
        payload = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "same-origin")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'none'; style-src 'unsafe-inline'; img-src data:; "
            "form-action 'self'; base-uri 'none'; frame-ancestors 'none'",
        )
        for name, value in headers or ():
            self.send_header(name, value)
        self.end_headers()
        if not head_only:
            self.wfile.write(payload)

    def _upload_page(self, query: dict[str, list[str]], *, head_only: bool) -> None:
        current = workspace_for(_first(query, "analysis"))
        body = render_upload_page(
            analyses=list_analyses(),
            current_analysis=current,
        )
        self._send(HTTPStatus.OK, body, head_only=head_only)

    def _plan_page(self, query: dict[str, list[str]], *, head_only: bool) -> None:
        plan_id = _first(query, "plan")
        edit_id = _first(query, "edit")
        if plan_id:
            saved = load_plan(plan_id)
            if saved is None:
                self._send(
                    HTTPStatus.NOT_FOUND,
                    _error_document(
                        "Plan not found",
                        "That saved plan is not available. It may have been removed, "
                        "or the link may be incomplete.",
                        action_href="/plan",
                        action_label="Start a new plan",
                        eyebrow="Money plan",
                    ),
                    head_only=head_only,
                )
                return
            body = render_plan_result(saved)
        elif edit_id:
            saved = load_plan(edit_id)
            if saved is None:
                self._send(
                    HTTPStatus.NOT_FOUND,
                    _error_document(
                        "Plan not found",
                        "That saved plan cannot be edited because it is not available.",
                        action_href="/plan",
                        action_label="Start a new plan",
                        eyebrow="Money plan",
                    ),
                    head_only=head_only,
                )
                return
            body = render_plan_page(draft=plan_to_draft(saved.plan), source=saved)
        else:
            body = render_plan_page()
        self._send(HTTPStatus.OK, body, head_only=head_only)

    def _create_plan(self) -> None:
        if not self._same_origin():
            self._send(
                HTTPStatus.FORBIDDEN,
                _error_document(
                    "Request blocked",
                    "Money plans must be submitted from this dashboard's own form.",
                    action_href="/plan",
                    action_label="Back to the money plan",
                    eyebrow="Money plan",
                ),
            )
            return
        try:
            body = self._read_plan_body()
            form = parse_form(self.headers.get("Content-Type", ""), body)
        except PlanRequestError as error:
            logger.info("plan request rejected: %s", error)
            self._send(
                error.status,
                _error_document(
                    "Plan not accepted",
                    str(error),
                    action_href="/plan",
                    action_label="Back to the money plan",
                    eyebrow="Money plan",
                ),
            )
            return

        category_rows = _form_row_count(
            form, "category_rows", default=CATEGORY_ROWS, maximum=MAX_CATEGORIES
        )
        spending_rows = _form_row_count(
            form, "spending_rows", default=SPENDING_ROWS, maximum=MAX_SPENDINGS
        )
        action = _first(form, "action")
        if action == "add_category":
            category_rows = min(category_rows + 1, MAX_CATEGORIES)
        elif action == "add_spending":
            spending_rows = min(spending_rows + 1, MAX_SPENDINGS)
        if action in ("add_category", "add_spending"):
            draft = read_draft(
                form, category_rows=category_rows, spending_rows=spending_rows
            )
            self._send(
                HTTPStatus.OK,
                render_plan_page(
                    draft=draft,
                    category_rows=category_rows,
                    spending_rows=spending_rows,
                ),
            )
            return

        draft = read_draft(
            form, category_rows=category_rows, spending_rows=spending_rows
        )
        plan, errors = validate_draft(draft)
        if plan is None:
            self._send(
                HTTPStatus.UNPROCESSABLE_ENTITY,
                render_plan_page(
                    draft=draft,
                    errors=errors,
                    category_rows=category_rows,
                    spending_rows=spending_rows,
                ),
            )
            return

        saved = save_plan(plan)
        location = "/plan?" + urllib.parse.urlencode({"plan": saved.plan_id})
        self._send(HTTPStatus.SEE_OTHER, "", headers=[("Location", location)])

    def _read_plan_body(self) -> bytes:
        raw_length = self.headers.get("Content-Length")
        if raw_length is None:
            raise PlanRequestError(
                "The browser did not send a Content-Length header.", status=411
            )
        try:
            length = int(raw_length)
        except ValueError:
            raise PlanRequestError("The form length is not valid.") from None
        if length <= 0:
            raise PlanRequestError("The plan form was empty.")
        if length > MAX_PLAN_REQUEST_BYTES:
            raise PlanRequestError(
                "The plan form is larger than the allowed limit.", status=413
            )
        body = self.rfile.read(length)
        if len(body) != length:
            raise PlanRequestError("The form ended before all bytes arrived.")
        return body

    def _create_analysis(self) -> None:
        if not self._same_origin():
            self._send(
                HTTPStatus.FORBIDDEN,
                _error_document(
                    "Request blocked",
                    "Uploads must come from this dashboard's own page.",
                    action_href="/upload",
                ),
            )
            return
        title = ""
        try:
            body = self._read_upload_body()
            content_type = self.headers.get("Content-Type", "")
            bundle = parse_upload(content_type, body)
            title = bundle.title
            analysis = create_analysis(bundle)
        except PipelineFailure as error:
            logger.warning("analysis pipeline failed: %s", error)
            self._upload_error(422, [str(error)], title=title)
            return
        except UploadError as error:
            logger.info("upload rejected: %s", error)
            if error.status in (411, 413):
                self._send(
                    error.status,
                    _error_document(
                        "Upload not accepted",
                        str(error),
                        action_href="/upload",
                    ),
                )
            else:
                self._upload_error(error.status, [str(error)])
            return

        location = "/?" + urllib.parse.urlencode({"analysis": analysis.analysis_id})
        self._send(HTTPStatus.SEE_OTHER, "", headers=[("Location", location)])

    def _upload_error(
        self,
        status: int,
        errors: list[str],
        *,
        title: str = "",
    ) -> None:
        body = render_upload_page(
            analyses=list_analyses(),
            errors=errors,
            title=title,
        )
        self._send(status, body)

    def _read_upload_body(self) -> bytes:
        raw_length = self.headers.get("Content-Length")
        if raw_length is None:
            raise UploadError(
                "The browser did not send a Content-Length header.", status=411
            )
        try:
            length = int(raw_length)
        except ValueError:
            raise UploadError("The upload length is not valid.") from None
        if length <= 0:
            raise UploadError("The upload was empty.")
        if length > MAX_REQUEST_BYTES:
            raise UploadError(
                "The upload is larger than the allowed limit.", status=413
            )
        body = self.rfile.read(length)
        if len(body) != length:
            raise UploadError("The upload ended before all bytes arrived.")
        return body

    def _same_origin(self) -> bool:
        if self.headers.get("Sec-Fetch-Site") == "cross-site":
            return False
        origin = self.headers.get("Origin")
        if not origin:
            return True
        host = self.headers.get("Host", "")
        if not host:
            return False
        parsed = urllib.parse.urlsplit(origin)
        return (
            parsed.scheme in {"http", "https"}
            and parsed.netloc.lower() == host.lower()
        )

    def _requested_analysis(
        self, query: dict[str, list[str]]
    ) -> tuple[AnalysisWorkspace | None, str | None]:
        requested = _first(query, "analysis")
        if not requested:
            return None, None
        analysis = workspace_for(requested)
        if analysis is None:
            return None, (
                "That analysis is not available. It may have been removed or may not "
                "have finished loading."
            )
        return analysis, None

    def _sample(self, path: str, *, head_only: bool) -> None:
        name = path.removeprefix("/samples/")
        source = SAMPLE_FILES.get(name)
        if source is None or not source.is_file():
            body = _error_document(
                "Sample not found",
                "That sample file is not part of this project.",
                action_href="/upload",
            )
            self._send(HTTPStatus.NOT_FOUND, body, head_only=head_only)
            return
        text = source.read_text(encoding="utf-8")
        self._send(
            HTTPStatus.OK,
            text,
            headers=[("Content-Disposition", f'attachment; filename="{name}"')],
            content_type="text/csv; charset=utf-8",
            head_only=head_only,
        )

    def _dispatch(self, *, head_only: bool) -> None:
        parsed = urllib.parse.urlsplit(self.path)
        path = parsed.path
        query = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
        try:
            if path == "/":
                self._page(query, head_only=head_only)
            elif path == "/upload":
                self._upload_page(query, head_only=head_only)
            elif path == "/plan":
                self._plan_page(query, head_only=head_only)
            elif path == "/export.csv":
                self._export(query, head_only=head_only)
            elif path == "/report":
                self._report(query, head_only=head_only)
            elif path.startswith("/samples/"):
                self._sample(path, head_only=head_only)
            elif path == "/favicon.ico":
                self._no_content()
            else:
                body = _error_document(
                    "Page not found",
                    "That address is not part of the spending explorer. Use the dashboard "
                    "filters to choose a view.",
                )
                self._send(HTTPStatus.NOT_FOUND, body, head_only=head_only)
        except sqlite3.Error:
            logger.exception("warehouse query failed")
            body = _error_document(
                "The warehouse is unavailable",
                "The dashboard could not query the warehouse. Rerun "
                "'student-spending' to rebuild it, then reload this page.",
            )
            self._safe_send(HTTPStatus.SERVICE_UNAVAILABLE, body, head_only=head_only)
        except (BrokenPipeError, ConnectionResetError):
            logger.debug("client disconnected before the response finished")
        except Exception:  # noqa: BLE001 - one bad request must not stop the server
            logger.exception("unexpected dashboard failure")
            body = _error_document(
                "Something went wrong",
                "The dashboard hit an unexpected error. Check the server log, then try again.",
            )
            self._safe_send(HTTPStatus.INTERNAL_SERVER_ERROR, body, head_only=head_only)

    def _safe_send(self, status: int, body: str, *, head_only: bool) -> None:
        try:
            self._send(status, body, head_only=head_only)
        except (BrokenPipeError, ConnectionResetError):
            logger.debug("client disconnected before the error response finished")

    def _open(self, db_path: Path | None = None) -> sqlite3.Connection:
        return connect_readonly(db_path or self.server.db_path)

    def _page(self, query: dict[str, list[str]], *, head_only: bool) -> None:
        analysis, error = self._requested_analysis(query)
        if error:
            self._send(
                HTTPStatus.NOT_FOUND,
                _error_document("Analysis not found", error, action_href="/upload"),
                head_only=head_only,
            )
            return
        db_path = analysis.db_path if analysis else self.server.db_path
        report_path = analysis.report_path if analysis else self.server.report_path
        connection = self._open(db_path)
        try:
            body = render_dashboard(
                connection,
                query,
                report_available=report_path.is_file(),
                analysis=analysis,
            )
        finally:
            connection.close()
        self._send(HTTPStatus.OK, body, head_only=head_only)

    def _export(self, query: dict[str, list[str]], *, head_only: bool) -> None:
        analysis, error = self._requested_analysis(query)
        if error:
            self._send(
                HTTPStatus.NOT_FOUND,
                _error_document("Analysis not found", error, action_href="/upload"),
                head_only=head_only,
            )
            return
        db_path = analysis.db_path if analysis else self.server.db_path
        connection = self._open(db_path)
        try:
            filters, errors = parse_filters(query, load_options(connection))
            if errors:
                body = _error_document(
                    "Filters need attention",
                    " ".join(errors) + " Adjust the filters on the dashboard first.",
                    action_href="/" + _analysis_suffix(analysis),
                )
                self._send(HTTPStatus.BAD_REQUEST, body, head_only=head_only)
                return
            csv_text = render_csv(connection, filters)
        finally:
            connection.close()
        filename = (
            f"student-spending-{filters.date_from or 'all'}-to-{filters.date_to or 'all'}.csv"
        )
        self._send(
            HTTPStatus.OK,
            csv_text,
            headers=[("Content-Disposition", f'attachment; filename="{filename}"')],
            content_type="text/csv; charset=utf-8",
            head_only=head_only,
        )

    def _report(
        self, query: dict[str, list[str]], *, head_only: bool
    ) -> None:
        analysis, error = self._requested_analysis(query)
        if error:
            self._send(
                HTTPStatus.NOT_FOUND,
                _error_document("Analysis not found", error, action_href="/upload"),
                head_only=head_only,
            )
            return
        report_path = analysis.report_path if analysis else self.server.report_path
        if not report_path.is_file():
            body = _error_document(
                "No report yet",
                "Run 'student-spending' to build the static report, then reload this page.",
                action_href="/" + _analysis_suffix(analysis),
            )
            self._send(HTTPStatus.NOT_FOUND, body, head_only=head_only)
            return
        report_text = report_path.read_text(encoding="utf-8")
        self._send(HTTPStatus.OK, report_text, head_only=head_only)


def create_server(
    db_path: Path | str,
    *,
    host: str = "127.0.0.1",
    port: int = 0,
    report_path: Path | str | None = None,
) -> DashboardServer:
    db_path = Path(db_path)
    if not db_path.is_file():
        raise FileNotFoundError(f"warehouse not found: {db_path}")
    if report_path is None:
        report_path = config.REPORTS_DIR / "spending_report.html"
    return DashboardServer(
        (host, port),
        db_path=db_path,
        report_path=Path(report_path),
    )


def _display_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(config.PROJECT_ROOT))
    except ValueError:
        return str(path)


def serve(
    db_path: Path | str = config.DEFAULT_DB_PATH,
    *,
    host: str = "127.0.0.1",
    port: int = 8000,
    open_browser: bool = False,
) -> int:
    """Start the dashboard and block until Ctrl+C. Returns a process exit code."""
    db_path = Path(db_path)
    if not db_path.is_file():
        print(f"Warehouse not found: {db_path}")
        print("Build it first with: student-spending --full-refresh")
        return 2
    try:
        connection = connect_readonly(db_path)
        try:
            row_count = connection.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]
        finally:
            connection.close()
    except sqlite3.Error as error:
        print(f"Could not read the warehouse at {db_path}: {error}")
        print("Rebuild it with: student-spending --full-refresh")
        return 2
    if not row_count:
        print(f"The warehouse at {db_path} has no transactions.")
        print("Build it first with: student-spending --full-refresh")
        return 2

    try:
        server = create_server(db_path, host=host, port=port)
    except OSError as error:
        print(f"Could not start the dashboard on {host}:{port}: {error}")
        print("Try another port, for example: student-spending serve --port 8001")
        return 2

    bound_host, bound_port = server.server_address[:2]
    display_host = "127.0.0.1" if bound_host in ("0.0.0.0", "::") else str(bound_host)
    if ":" in display_host:
        display_host = f"[{display_host}]"
    url = f"http://{display_host}:{bound_port}/"
    print()
    print("Student Spending Explorer")
    print(f"  {url}")
    print(f"  warehouse: {_display_path(db_path)} (read-only)")
    print("  synthetic data only; press Ctrl+C to stop")
    if host not in ("127.0.0.1", "localhost", "::1"):
        print("  warning: bound beyond loopback; this dashboard has no authentication")
    print()

    if open_browser:
        threading.Timer(0.6, webbrowser.open, args=(url,)).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("Dashboard stopped.")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(serve())
