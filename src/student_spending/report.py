"""Render the analytical report and the rejection audit trail.

Nothing here computes a number. Every figure comes from a view or a query in
``analytics``; this module only formats and escapes what the database returns.
"""

from __future__ import annotations

import csv
import html
import logging
import sqlite3
from pathlib import Path

from . import analytics
from .components import (
    bar_chart as _bar_chart,
    integer as _int,
    money as _money,
    percent as _percent,
    share_cell as _share_cell,
    table as _table,
)
from .theme import BASE_CSS
from .validate import RejectedRecord

logger = logging.getLogger(__name__)

_CSS = BASE_CSS


_NAV = [
    ("overview", "Overview"),
    ("quality", "Quality"),
    ("trends", "Trends"),
    ("categories", "Categories"),
    ("budgets", "Budgets"),
    ("students", "Students"),
    ("review", "Review"),
    ("merchants", "Merchants"),
]


def _nav() -> str:
    links = "".join(
        f'<a href="#{anchor}">{html.escape(label)}</a>' for anchor, label in _NAV
    )
    return f'<nav class="toc" aria-label="Report sections">{links}</nav>'


def _hero(run_id: str, run: dict, kpis: dict) -> str:
    status = str(run["status"])
    dot_class = "status-dot" if status == "success" else "status-dot bad"
    source = Path(run["input_file"]).name
    return f"""
  <header class="hero" id="top">
    <p class="eyebrow">Synthetic data &middot; learning project</p>
    <h1>Student Spending <span>Analytics</span></h1>
    <p class="lede">A reproducible view of where {_int(kpis["student_count"])} synthetic
      students spent their money, built from raw CSV through validation, a SQLite
      warehouse and SQL-defined analytics.</p>
    <ul class="chips">
      <li><span class="chip-key">Run</span><code>{html.escape(run_id)}</code></li>
      <li><span class="chip-key">Status</span><span class="{dot_class}"></span>
        {html.escape(status)}</li>
      <li><span class="chip-key">Period</span>
        {html.escape(str(kpis["first_date"]))} &rarr; {html.escape(str(kpis["last_date"]))}</li>
      <li><span class="chip-key">Source</span><code>{html.escape(source)}</code></li>
    </ul>
    <p class="disclaimer"><strong>Synthetic data.</strong> Every record here was generated
      for a learning exercise. Nothing describes real students, accounts, cards or
      payments.</p>
  </header>"""


def _section(
    number: str,
    eyebrow: str,
    title: str,
    body: str,
    *,
    lead: str = "",
    anchor: str,
) -> str:
    lead_html = f'<p class="lead">{lead}</p>' if lead else ""
    return (
        f'<section class="panel" id="{anchor}">'
        f'<p class="eyebrow"><span class="section-no">{number}</span> {html.escape(eyebrow)}</p>'
        f"<h2>{html.escape(title)}</h2>{lead_html}{body}</section>"
    )


def _subsection(title: str, body: str, note: str = "") -> str:
    note_html = f'<p class="section-note">{html.escape(note)}</p>' if note else ""
    return f"<h3>{html.escape(title)}</h3>{note_html}{body}"


def _quality_banner(total: int, failures: int) -> str:
    if failures:
        return (
            f'<div class="banner bad"><strong>{failures} check(s) need attention.</strong>'
            " Review the failing rows before trusting the affected totals.</div>"
        )
    return (
        f'<div class="banner good"><strong>All {total} checks passed.</strong>'
        " Reconciliation identities and row-level rules held on this run.</div>"
    )


def _headline(kpis: dict, categories: list[dict], budget: dict) -> str:
    sentences = [
        f"{_int(kpis['student_count'])} synthetic students spent "
        f"<strong>KES {_money(kpis['total_kes'])}</strong> across "
        f"{_int(kpis['transaction_count'])} clean transactions."
    ]
    if categories:
        top = categories[0]
        sentences.append(
            f"<strong>{html.escape(str(top['category']))}</strong> takes the largest share"
            f" at {_percent(top['share_pct'])}."
        )
    if budget["budget_lines"]:
        sentences.append(
            f"{_int(budget['over_budget_lines'])} of {_int(budget['budget_lines'])} "
            f"budget lines are over plan."
        )
    else:
        sentences.append(
            "No budget plan was provided, so this report covers actual spending only."
        )
    return " ".join(sentences)


def _kpi_cards(kpis: dict) -> str:
    cards = [
        ("Total spend", f"KES {_money(kpis['total_kes'])}",
         f"{str(kpis['first_date'])[:7]} to {str(kpis['last_date'])[:7]}"),
        ("Transactions", _int(kpis["transaction_count"]), "clean rows in the fact table"),
        ("Students", _int(kpis["student_count"]), "anonymized synthetic profiles"),
        ("Average daily spend", f"KES {_money(kpis['avg_daily_kes'])}", f"across {kpis['days_covered']} days"),
        ("Average transaction", f"KES {_money(kpis['avg_transaction_kes'])}", "mean amount per transaction"),
        ("Flagged for review", _int(kpis["flagged_count"]), "unusual but valid transactions"),
    ]
    cells = "".join(
        f'<div class="card"><div class="label">{html.escape(label)}</div>'
        f'<div class="value">{html.escape(value)}</div>'
        f'<div class="hint">{html.escape(hint)}</div></div>'
        for label, value, hint in cards
    )
    return f'<div class="cards">{cells}</div>'


def _reconciliation_table(run: dict) -> str:
    headers = [("Stage", False), ("Count", True)]
    rows = [
        ["Rows read from file", _int(run["rows_read"])],
        ["Accepted (validated)", _int(run["rows_accepted"])],
        ["Rejected (duplicates)", _int(run["rows_rejected"])],
        ["Quarantined (held for review)", _int(run["rows_quarantined"])],
        ["Inserted into warehouse", _int(run["rows_inserted"])],
        ["Updated (changed content)", _int(run["rows_updated"])],
        ["Unchanged (identical rerun)", _int(run["rows_unchanged"])],
    ]
    return _table(headers, rows)


def _quality_table(checks: list[dict]) -> str:
    headers = [("Check", False), ("Result", False), ("Observed", False), ("Expected", False)]
    rows = []
    for check in checks:
        status = (
            '<span class="pill pass">PASS</span>'
            if check["passed"]
            else '<span class="pill fail">FAIL</span>'
        )
        rows.append(
            [
                f'<code>{html.escape(check["check_name"])}</code>',
                status,
                html.escape(check["observed"]),
                html.escape(check["expected"]),
            ]
        )
    return _table(headers, rows)


def write_report(
    connection: sqlite3.Connection,
    run_id: str,
    output_dir: Path,
) -> Path:
    """Write ``spending_report.html`` from warehouse contents and return its path."""
    run = analytics.run_row(connection, run_id)
    kpis = analytics.kpis(connection)
    months = analytics.monthly_totals(connection)
    categories = analytics.category_totals(connection)
    students = analytics.student_totals(connection)
    weekdays = analytics.weekday_spending(connection)
    overruns = analytics.budget_overruns(connection, limit=10)
    budget = analytics.budget_summary(connection)
    flagged = analytics.flagged_transactions(connection, limit=15)
    merchants = analytics.top_merchants(connection, limit=5)
    payments = analytics.payment_mix(connection)
    checks = analytics.quality_results(connection, run_id)
    failures = sum(1 for check in checks if not check["passed"])

    month_rows = [
        [html.escape(month["transaction_month"]), _int(month["active_students"]),
         _int(month["transaction_count"]), _money(month["total_kes"])]
        for month in months
    ]
    category_rows = [
        [html.escape(category["category"]), _int(category["transaction_count"]),
         _money(category["total_kes"]), _share_cell(category["share_pct"])]
        for category in categories
    ]
    student_rows = [
        [html.escape(student["profile_label"]), html.escape(student["student_id"]),
         _int(student["transaction_count"]), _money(student["total_kes"]),
         _money(student["avg_transaction_kes"])]
        for student in students
    ]
    weekday_rows = [
        [html.escape(day["weekday_name"]), _int(day["transaction_count"]),
         _money(day["total_kes"]), _money(day["avg_transaction_kes"])]
        for day in weekdays
    ]
    overrun_rows = [
        [html.escape(row["profile_label"]), html.escape(row["budget_month"]),
         html.escape(row["category"]), _money(row["budget_kes"]),
         _money(row["actual_kes"]), _money(row["variance_kes"])]
        for row in overruns
    ]
    flagged_rows = [
        [html.escape(row["transaction_date"]), html.escape(row["profile_label"]),
         html.escape(row["category"]), _money(row["amount_kes"]),
         html.escape(row["merchant"]), html.escape(row["anomaly_reason"] or "")]
        for row in flagged
    ]
    merchant_rows = [
        [html.escape(row["merchant"]), _int(row["transaction_count"]), _money(row["total_kes"])]
        for row in merchants
    ]
    payment_rows = [
        [html.escape(row["payment_method"]), _int(row["transaction_count"]),
         _money(row["total_kes"])]
        for row in payments
    ]

    overview = _section(
        "01", "Overview", "This run at a glance",
        _kpi_cards(kpis)
        + _subsection(
            "Run reconciliation",
            _reconciliation_table(run),
            "Every row read from the CSV must end up accepted, rejected, or quarantined, "
            "and every accepted row must reach the warehouse.",
        ),
        lead=_headline(kpis, categories, budget),
        anchor="overview",
    )

    quality = _section(
        "02", "Quality", "Data quality checks",
        _quality_banner(len(checks), failures) + _quality_table(checks),
        lead="Automated checks cover reconciliation, duplicates, constraints and coverage. "
             "Each result is stored with the run so it can be audited later.",
        anchor="quality",
    )

    trends = _section(
        "03", "Trends", "How spending moved",
        _subsection(
            "Monthly totals",
            _bar_chart(months, "transaction_month", "total_kes",
                       title="Monthly total spending", gradient_id="chart-monthly")
            + _table(
                [("Month", False), ("Students", True), ("Transactions", True), ("Total KES", True)],
                month_rows,
            ),
            "Bars and table show total spend per month; all figures are in KES.",
        )
        + _subsection(
            "Spending by day of week",
            _bar_chart(weekdays, "weekday_name", "total_kes",
                       title="Spending by day of week", gradient_id="chart-weekday")
            + _table(
                [("Day", False), ("Transactions", True), ("Total KES", True), ("Average KES", True)],
                weekday_rows,
            ),
            "Totals across the whole reporting period.",
        ),
        lead="Two views of the same clean fact table: how spend changed month by month, "
             "and which weekdays carry the most activity.",
        anchor="trends",
    )

    category_panel = _section(
        "04", "Categories", "Where the money goes",
        _bar_chart(categories, "category", "total_kes",
                   title="Total spending by category", gradient_id="chart-category")
        + _table(
            [("Category", False), ("Transactions", True), ("Total KES", True), ("Share", True)],
            category_rows,
        ),
        lead="Ranked by total spend. The bar beside each share repeats the percentage "
             "so the mix is easy to scan.",
        anchor="categories",
    )

    if budget["budget_lines"]:
        budget_panel = _section(
            "05", "Budgets", "Budget versus actual",
            _table(
                [("Profile", False), ("Month", False), ("Category", False),
                 ("Budget KES", True), ("Actual KES", True), ("Over by KES", True)],
                overrun_rows,
                row_classes=["over"] * len(overrun_rows),
                empty_message="No category exceeded its budget.",
            ),
            lead=f"{_int(budget['over_budget_lines'])} of {_int(budget['budget_lines'])} "
                 f"budget lines are over plan. Planned KES {_money(budget['total_budget_kes'])} "
                 f"versus actual KES {_money(budget['total_actual_kes'])}. "
                 "The ten largest overruns are shown.",
            anchor="budgets",
        )
    else:
        budget_panel = _section(
            "05", "Budgets", "Budget versus actual",
            '<p class="section-note">No budget plan was provided for this analysis. '
            "Actual spending is complete; variance needs a budgets file.</p>",
            lead="Budget comparison is unavailable for a single-file upload.",
            anchor="budgets",
        )

    student_panel = _section(
        "06", "Students", "Student summary",
        _table(
            [("Profile", False), ("Student", False), ("Transactions", True),
             ("Total KES", True), ("Average KES", True)],
            student_rows,
        ),
        lead="Totals and averages per synthetic profile. Student identifiers are "
             "anonymised placeholders.",
        anchor="students",
    )

    review = _section(
        "07", "Review", "Transactions flagged for investigation",
        _table(
            [("Date", False), ("Profile", False), ("Category", False), ("Amount KES", True),
             ("Merchant", False), ("Why flagged", False)],
            flagged_rows,
            row_classes=["alert"] * len(flagged_rows),
            empty_message="No transactions exceeded the anomaly threshold.",
        ),
        lead="Valid transactions that are unusually large for that student and category. "
             "They stay in the warehouse: flagging is not deletion.",
        anchor="review",
    )

    merchant_panel = _section(
        "08", "Merchants", "Where the money went",
        _subsection(
            "Top merchants",
            _table(
                [("Merchant", False), ("Transactions", True), ("Total KES", True)],
                merchant_rows,
            ),
            "Five merchants ranked by total spend.",
        )
        + _subsection(
            "Payment methods",
            _table(
                [("Method", False), ("Transactions", True), ("Total KES", True)],
                payment_rows,
            ),
            "How the clean transactions were paid.",
        ),
        lead="The same totals sliced by counterparty and payment channel.",
        anchor="merchants",
    )

    body = f"""
<main class="shell">
  {_hero(run_id, run, kpis)}
  {_nav()}
  {overview}
  {quality}
  {trends}
  {category_panel}
  {budget_panel}
  {student_panel}
  {review}
  {merchant_panel}
  <footer class="panel footer">
    <p><strong>Reproducible by design.</strong> Every figure comes from a SQL view rather
      than a hard-coded value. Rerun <code>student-spending</code> against the same raw
      files to reproduce these totals exactly.</p>
    <p class="meta-line">Student Spending Analytics &middot; run
      <code>{html.escape(run_id)}</code> &middot; started
      <code>{html.escape(run["started_at"])}</code> &middot; finished
      <code>{html.escape(run["finished_at"] or "not finished")}</code> &middot; source
      <code>{html.escape(Path(run["input_file"]).name)}</code></p>
    <a class="totop" href="#top">Back to top</a>
  </footer>
</main>
"""
    document = (
        "<!DOCTYPE html>\n<html lang=\"en\">\n<head>\n<meta charset=\"utf-8\">\n"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n"
        "<title>Student Spending Analytics Report</title>\n"
        f"<style>{_CSS}</style>\n</head>\n<body>\n"
        '<a class="skip" href="#overview">Skip to content</a>\n'
        '<div class="scene" aria-hidden="true">'
        '<span class="orb orb-a"></span><span class="orb orb-b"></span>'
        '<span class="orb orb-c"></span></div>\n'
        f"{body}</body>\n</html>\n"
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / "spending_report.html"
    path.write_text(document, encoding="utf-8")
    logger.info("wrote report to %s", path)
    return path


def write_rejection_csv(
    rejections: list[RejectedRecord],
    directory: Path,
    run_id: str,
) -> Path:
    """Export rejected/quarantined rows so a human can actually inspect them."""
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"rejections_{run_id}.csv"
    fields = [
        "source_line", "outcome", "reason_code", "reason_detail",
        "transaction_id", "student_id", "transaction_date", "amount_kes",
        "category", "description", "payment_method", "merchant", "is_recurring",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for record in rejections:
            payload = record.raw_payload or {}
            writer.writerow(
                {
                    "source_line": record.source_line,
                    "outcome": record.outcome,
                    "reason_code": record.reason_code,
                    "reason_detail": record.reason_detail,
                    "transaction_id": record.transaction_id or "",
                    "student_id": record.student_id or "",
                    "transaction_date": payload.get("transaction_date", ""),
                    "amount_kes": payload.get("amount_kes", ""),
                    "category": payload.get("category", ""),
                    "description": payload.get("description", ""),
                    "payment_method": payload.get("payment_method", ""),
                    "merchant": payload.get("merchant", ""),
                    "is_recurring": payload.get("is_recurring", ""),
                }
            )
    logger.info("wrote %d rejection row(s) to %s", len(rejections), path)
    return path
