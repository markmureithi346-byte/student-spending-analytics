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
from .validate import RejectedRecord

logger = logging.getLogger(__name__)

_CSS = """
:root {
  color-scheme: light;
  --ink: #0f172a;
  --muted: #64748b;
  --line: #e2e8f0;
  --accent: #0f766e;
  --accent-soft: #ccfbf1;
  --danger: #b91c1c;
  --danger-soft: #fee2e2;
  --surface: #ffffff;
  --canvas: #f6f8fb;
}
* { box-sizing: border-box; }
body {
  margin: 0;
  padding: 32px 20px 64px;
  background: var(--canvas);
  color: var(--ink);
  font-family: "Segoe UI", system-ui, -apple-system, sans-serif;
  line-height: 1.5;
}
main { max-width: 980px; margin: 0 auto; }
h1 { font-size: 28px; margin: 0 0 4px; letter-spacing: -0.02em; }
h2 { font-size: 18px; margin: 40px 0 12px; }
.subtitle { color: var(--muted); margin: 0 0 8px; }
.disclaimer {
  background: #fffbeb; border: 1px solid #fde68a; color: #78350f;
  padding: 10px 14px; border-radius: 8px; font-size: 13px; margin: 16px 0 28px;
}
.meta { color: var(--muted); font-size: 13px; }
.cards {
  display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
  gap: 12px; margin-bottom: 8px;
}
.card {
  background: var(--surface); border: 1px solid var(--line);
  border-radius: 10px; padding: 14px 16px;
}
.card .label { font-size: 12px; text-transform: uppercase; letter-spacing: 0.06em; color: var(--muted); }
.card .value { font-size: 21px; font-weight: 600; margin-top: 4px; white-space: nowrap; }
.card .hint { font-size: 12px; color: var(--muted); }
table { width: 100%; border-collapse: collapse; background: var(--surface);
        border: 1px solid var(--line); border-radius: 10px; overflow: hidden; font-size: 14px; }
th, td { padding: 9px 12px; text-align: left; border-bottom: 1px solid var(--line); }
th { background: #f8fafc; font-size: 12px; text-transform: uppercase;
     letter-spacing: 0.05em; color: var(--muted); font-weight: 600; }
tbody tr:last-child td { border-bottom: none; }
td.num, th.num { text-align: right; font-variant-numeric: tabular-nums; }
tr.alert td { background: var(--danger-soft); color: #7f1d1d; }
.pill { display: inline-block; padding: 1px 8px; border-radius: 999px;
        font-size: 12px; font-weight: 600; }
.pass { background: var(--accent-soft); color: #115e59; }
.fail { background: var(--danger-soft); color: var(--danger); }
.chart { width: 100%; height: auto; background: var(--surface);
         border: 1px solid var(--line); border-radius: 10px; padding: 10px 14px; }
.chart text { font-family: inherit; font-size: 12px; fill: #334155; }
.chart .bar { fill: var(--accent); }
.chart .bar-alt { fill: #0ea5a4; }
.chart .bar-label { fill: #475569; }
.chart .bar-value { fill: var(--muted); font-variant-numeric: tabular-nums; }
.section-note { font-size: 13px; color: var(--muted); margin: 8px 0 12px; }
footer { margin-top: 48px; font-size: 12px; color: var(--muted); }
code { background: #eef2f6; padding: 1px 5px; border-radius: 4px; font-size: 13px; }
"""


def _money(value: object) -> str:
    try:
        return f"{float(value):,.2f}"
    except (TypeError, ValueError):
        return "0.00"


def _int(value: object) -> str:
    try:
        return f"{int(value):,}"
    except (TypeError, ValueError):
        return "0"


def _percent(value: object) -> str:
    try:
        return f"{float(value):.1f}%"
    except (TypeError, ValueError):
        return "0.0%"


def _table(
    headers: list[tuple[str, bool]],
    rows: list[list[str]],
    row_classes: list[str] | None = None,
    empty_message: str = "No rows produced by this query.",
) -> str:
    if not rows:
        return f'<p class="section-note">{html.escape(empty_message)}</p>'
    head = "".join(
        f'<th class="{"num" if numeric else ""}">{html.escape(title)}</th>'
        for title, numeric in headers
    )
    body = []
    for index, row in enumerate(rows):
        css = row_classes[index] if row_classes else ""
        cells = "".join(
            f'<td class="{"num" if headers[position][1] else ""}">{cell}</td>'
            for position, cell in enumerate(row)
        )
        body.append(f'<tr class="{css}">{cells}</tr>')
    return f"<table><thead><tr>{head}</tr></thead><tbody>{''.join(body)}</tbody></table>"


def _bar_chart(
    items: list[dict],
    label_key: str,
    value_key: str,
    *,
    width: int = 720,
    label_width: int = 160,
    chart_width: int = 440,
    bar_height: int = 18,
    gap: int = 10,
) -> str:
    if not items:
        return '<p class="section-note">Nothing to chart.</p>'
    maximum = max(float(item[value_key]) for item in items) or 1.0
    height = len(items) * (bar_height + gap) + gap
    parts = [
        f'<svg class="chart" viewBox="0 0 {width} {height}" preserveAspectRatio="xMinYMin meet" role="img">'
    ]
    for index, item in enumerate(items):
        y = gap + index * (bar_height + gap)
        value = float(item[value_key])
        bar = chart_width * value / maximum if value > 0 else 0.0
        label = html.escape(str(item[label_key]))
        parts.append(f'<text x="0" y="{y + bar_height - 4}" class="bar-label">{label}</text>')
        parts.append(
            f'<rect class="bar" x="{label_width}" y="{y}" width="{bar:.1f}" '
            f'height="{bar_height}" rx="3"></rect>'
        )
        parts.append(
            f'<text x="{label_width + bar + 8:.1f}" y="{y + bar_height - 4}" '
            f'class="bar-value">{_money(value)}</text>'
        )
    parts.append("</svg>")
    return "".join(parts)


def _section(title: str, body: str, note: str = "") -> str:
    note_html = f'<p class="section-note">{note}</p>' if note else ""
    return f"<h2>{html.escape(title)}</h2>{note_html}{body}"


def _kpi_cards(kpis: dict) -> str:
    cards = [
        ("Total spend", f"KES {_money(kpis['total_kes'])}", f"{kpis['first_date']} to {kpis['last_date']}"),
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
         _money(category["total_kes"]), _percent(category["share_pct"])]
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

    body = f"""
<main>
  <h1>Student Spending Analytics</h1>
  <p class="subtitle">Pipeline report generated from the SQLite warehouse.</p>
  <p class="meta">
    Run <code>{html.escape(run_id)}</code> &middot; status <strong>{html.escape(run["status"])}</strong>
    &middot; started {html.escape(run["started_at"])} &middot; finished {html.escape(run["finished_at"] or "not finished")}
    &middot; source <code>{html.escape(Path(run["input_file"]).name)}</code>
  </p>
  <p class="disclaimer">
    All records in this report are synthetic and generated for a learning exercise.
    They do not describe real students, accounts, or payments.
  </p>

  {_kpi_cards(kpis)}

  {_section("Run reconciliation", _reconciliation_table(run),
            "Every row read from the CSV must end up accepted, rejected, or quarantined. "
            "Accepted rows must all reach the warehouse.")}

  {_section("Data quality checks", _quality_table(checks),
            f"{len(checks) - failures} of {len(checks)} checks passed.")}

  {_section("Monthly spending", _bar_chart(months, "transaction_month", "total_kes") +
            _table([("Month", False), ("Students", True), ("Transactions", True), ("Total KES", True)],
                   month_rows))}

  {_section("Spending by category",
            _bar_chart(categories, "category", "total_kes") +
            _table([("Category", False), ("Transactions", True), ("Total KES", True), ("Share", True)],
                   category_rows),
            "Share is each category's portion of total clean spending.")}

  {_section("Budget versus actual",
            _table([("Profile", False), ("Month", False), ("Category", False),
                    ("Budget KES", True), ("Actual KES", True), ("Over by KES", True)],
                   overrun_rows, row_classes=["alert"] * len(overrun_rows),
                   empty_message="No category exceeded its budget."),
            f"{_int(budget['over_budget_lines'])} of {_int(budget['budget_lines'])} budget lines are over. "
            f"Planned KES {_money(budget['total_budget_kes'])} versus actual KES {_money(budget['total_actual_kes'])}.")}

  {_section("Spending by day of week",
            _table([("Day", False), ("Transactions", True), ("Total KES", True), ("Average KES", True)],
                   weekday_rows))}

  {_section("Student summary",
            _table([("Profile", False), ("Student", False), ("Transactions", True),
                    ("Total KES", True), ("Average KES", True)],
                   student_rows))}

  {_section("Transactions flagged for investigation",
            _table([("Date", False), ("Profile", False), ("Category", False), ("Amount KES", True),
                    ("Merchant", False), ("Why flagged", False)],
                   flagged_rows,
                   row_classes=["alert"] * len(flagged_rows),
                   empty_message="No transactions exceeded the anomaly threshold."),
            "Flagged rows are kept in the warehouse; the threshold is documented in README.")}

  {_section("Where the money went",
            _table([("Merchant", False), ("Transactions", True), ("Total KES", True)], merchant_rows))}

  {_section("Payment methods",
            _table([("Method", False), ("Transactions", True), ("Total KES", True)], payment_rows))}

  <footer>
    Generated by the Student Spending Analytics pipeline. Figures are reproducible:
    rerun <code>python run_pipeline.py</code> against the same raw files to obtain the same totals.
  </footer>
</main>
"""
    document = (
        "<!DOCTYPE html>\n<html lang=\"en\">\n<head>\n<meta charset=\"utf-8\">\n"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n"
        "<title>Student Spending Analytics Report</title>\n"
        f"<style>{_CSS}</style>\n</head>\n<body>{body}</body>\n</html>\n"
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
