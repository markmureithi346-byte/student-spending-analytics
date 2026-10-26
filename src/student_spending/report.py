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
  --ink: #241536;
  --muted: #6d6284;
  --line: #ece6f7;
  --accent: #6d28d9;
  --accent-2: #c026d3;
  --danger: #b42318;
  --danger-soft: #fff1f0;
  --success: #047857;
  --success-soft: #ecfdf5;
  --panel: rgba(255, 255, 255, 0.97);
}
* { box-sizing: border-box; }
html { scroll-behavior: smooth; }
body {
  margin: 0; min-height: 100vh; padding: 30px 20px 72px;
  background: #140624; color: #f7f3ff;
  font-family: "Segoe UI Variable Text", "Segoe UI", system-ui, -apple-system, sans-serif;
  line-height: 1.55; -webkit-font-smoothing: antialiased;
}
.scene { position: fixed; inset: 0; z-index: -1; overflow: hidden;
         background: linear-gradient(155deg, #0f041d 0%, #250a47 48%, #150626 100%); }
.orb { position: absolute; border-radius: 50%; filter: blur(85px); opacity: .55;
       animation: drift 26s ease-in-out infinite alternate; }
.orb-a { width: 46vw; height: 46vw; top: -14vh; left: -10vw; background: #7c3aed; }
.orb-b { width: 38vw; height: 38vw; top: 6vh; right: -10vw; background: #d946ef;
         opacity: .38; animation-duration: 31s; animation-delay: -8s; }
.orb-c { width: 44vw; height: 44vw; bottom: -20vh; left: 26vw; background: #4f46e5;
         opacity: .45; animation-duration: 36s; animation-delay: -16s; }
@keyframes drift {
  0% { transform: translate3d(0, 0, 0) scale(1); }
  50% { transform: translate3d(3vw, 4vh, 0) scale(1.07); }
  100% { transform: translate3d(-4vw, -3vh, 0) scale(.95); }
}
.skip { position: absolute; left: -999px; top: 8px; background: #fff; color: var(--accent);
        padding: 8px 14px; border-radius: 8px; z-index: 100; }
.skip:focus { left: 16px; }
.shell { width: 100%; max-width: 1060px; margin: 0 auto; }
.hero { padding: 10px 6px 4px; }
.eyebrow { display: flex; align-items: center; gap: 8px; margin: 0 0 10px;
           font-size: 12px; letter-spacing: .14em; text-transform: uppercase;
           color: #d8c4f7; font-weight: 600; }
.hero h1 { margin: 0 0 12px; font-size: clamp(34px, 5vw, 54px); line-height: 1.05;
           letter-spacing: -.035em; font-weight: 700; color: #fff; }
.hero h1 span { background: linear-gradient(100deg, #e9d5ff, #f0abfc 48%, #c4b5fd);
                -webkit-background-clip: text; background-clip: text; color: transparent; }
.lede { max-width: 720px; margin: 0 0 20px; font-size: 17px; color: #ded1f5; }
.chips { display: flex; flex-wrap: wrap; gap: 8px; margin: 0 0 18px; padding: 0; list-style: none; }
.chips li { display: inline-flex; align-items: center; gap: 8px; padding: 6px 12px;
            border: 1px solid rgba(255,255,255,.18); border-radius: 999px;
            background: rgba(255,255,255,.08); color: #f3e8ff; font-size: 12.5px;
            backdrop-filter: blur(8px); }
.chip-key { color: #c4b0e6; text-transform: uppercase; letter-spacing: .08em;
            font-size: 10.5px; font-weight: 700; }
.chips code { background: rgba(255,255,255,.14); color: #fff;
              padding: 1px 6px; border-radius: 5px; }
.status-dot { width: 8px; height: 8px; border-radius: 50%; background: #34d399;
              display: inline-block; box-shadow: 0 0 0 3px rgba(52,211,153,.2); }
.status-dot.bad { background: #fb7185; box-shadow: 0 0 0 3px rgba(251,113,133,.2); }
.disclaimer { max-width: 820px; margin: 0 0 26px; padding: 12px 16px; border-radius: 12px;
              background: rgba(255, 251, 235, .94); border: 1px solid rgba(253, 230, 138, .85);
              color: #5b3a06; font-size: 13px; }
.disclaimer strong { color: #7c2d12; }
.toc { position: sticky; top: 12px; z-index: 30; display: flex; flex-wrap: wrap; gap: 4px;
       margin: 0 0 20px; padding: 7px; border-radius: 22px;
       background: rgba(19, 7, 36, .74); border: 1px solid rgba(255,255,255,.15);
       backdrop-filter: blur(18px); box-shadow: 0 18px 40px -22px rgba(0,0,0,.9); }
.toc a { flex: 0 0 auto; padding: 7px 13px; border-radius: 999px; color: #e7daf9;
         text-decoration: none; font-size: 13px; font-weight: 600;
         transition: background-color .15s ease, color .15s ease; }
.toc a:hover, .toc a:focus-visible { background: rgba(168, 85, 247, .3); color: #fff; outline: none; }
.panel { background: var(--panel); color: var(--ink); border-radius: 22px;
         padding: 26px 28px 28px; margin: 0 0 22px;
         border: 1px solid rgba(255,255,255,.75);
         box-shadow: 0 34px 70px -34px rgba(6, 1, 16, .85); scroll-margin-top: 86px; }
.panel .eyebrow { color: var(--accent); }
.panel .section-no { color: var(--accent-2); font-variant-numeric: tabular-nums; }
.panel h2 { margin: 0 0 6px; font-size: 24px; letter-spacing: -.02em; }
.panel h3 { margin: 26px 0 4px; font-size: 16px; letter-spacing: -.01em; }
.lead { margin: 0 0 18px; color: var(--muted); font-size: 14.5px; max-width: 78ch; }
.section-note { margin: 4px 0 12px; color: var(--muted); font-size: 13px; }
.cards { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr));
         gap: 12px; margin: 18px 0 6px; }
.card { position: relative; padding: 15px 17px 16px; border-radius: 16px; overflow: hidden;
        background: linear-gradient(155deg, #fbf7ff, #f2e8ff 70%, #ece0ff);
        border: 1px solid #e6d6fb;
        transition: transform .18s ease, box-shadow .18s ease; }
.card::before { content: ""; position: absolute; inset: 0 0 auto; height: 3px;
                background: linear-gradient(90deg, #7c3aed, #d946ef); opacity: .85; }
.card:hover { transform: translateY(-2px);
              box-shadow: 0 12px 24px -14px rgba(109, 40, 217, .5); }
.card .label { font-size: 11px; font-weight: 700; text-transform: uppercase;
               letter-spacing: .07em; color: #7c3aed; }
.card .value { margin-top: 5px; font-size: clamp(19px, 2vw, 23px); font-weight: 700;
               color: #2e1065; white-space: nowrap; font-variant-numeric: tabular-nums;
               letter-spacing: -.02em; }
.card .hint { margin-top: 2px; font-size: 12px; color: #6d6284; }
.headline { margin: 16px 0 4px; font-size: 15px; color: #3f2b5c; }
.headline strong { color: var(--accent); }
.banner { display: flex; flex-wrap: wrap; gap: 6px; align-items: baseline;
          margin: 6px 0 16px; padding: 12px 15px; border-radius: 12px; font-size: 13.5px; }
.banner strong { font-weight: 700; }
.banner.good { background: var(--success-soft); border: 1px solid #a7f3d0; color: #065f46; }
.banner.bad { background: var(--danger-soft); border: 1px solid #fecaca; color: #912018; }
.table-wrap { overflow-x: auto; border: 1px solid var(--line); border-radius: 14px;
              background: #fff; -webkit-overflow-scrolling: touch; }
table { width: 100%; border-collapse: collapse; font-size: 14px; min-width: 520px; }
th, td { padding: 10px 13px; text-align: left; border-bottom: 1px solid var(--line);
         vertical-align: top; }
thead th { background: #f7f2ff; color: #5b4a7a; font-size: 11.5px; text-transform: uppercase;
           letter-spacing: .06em; font-weight: 700; white-space: nowrap; }
tbody tr:nth-child(even) { background: #fcfaff; }
tbody tr:hover { background: #f6edff; }
tbody tr:last-child td { border-bottom: none; }
td.num, th.num { text-align: right; font-variant-numeric: tabular-nums; white-space: nowrap; }
tr.alert td { background: var(--danger-soft); color: #7a271a; }
tr.alert:hover td { background: #ffe4e0; }
tr.over td { background: #fff8f6; color: #5f2a22; }
tr.over:hover td { background: #ffefeb; }
tr.over td:last-child { color: var(--danger); font-weight: 700; }
.pill { display: inline-block; padding: 2px 9px; border-radius: 999px;
        font-size: 11.5px; font-weight: 700; letter-spacing: .03em; }
.pass { background: var(--success-soft); color: var(--success); }
.fail { background: var(--danger-soft); color: var(--danger); }
.panel code { background: #f3edfb; color: #5b21b6; padding: 2px 7px;
              border-radius: 5px; font-size: 12.5px; }
.panel table code { white-space: nowrap; }
.share { display: inline-flex; align-items: center; gap: 8px; justify-content: flex-end; }
.share-track { width: 64px; height: 6px; border-radius: 999px;
               background: #eee5fa; overflow: hidden; }
.share-fill { display: block; height: 100%; border-radius: inherit;
              background: linear-gradient(90deg, #7c3aed, #d946ef); }
.share-value { min-width: 42px; text-align: right; font-variant-numeric: tabular-nums; }
.chart-wrap { overflow-x: auto; margin-bottom: 14px; border-radius: 14px; }
.chart-hint { display: none; }
.chart { display: block; width: 100%; height: auto; background: #fff;
         border: 1px solid var(--line); border-radius: 14px; padding: 12px 14px; }
.chart text { font-family: inherit; font-size: 12px; fill: #4c3a66; }
.chart .bar-label { fill: #4c3a66; }
.chart .bar-value { fill: #7c6a9a; font-variant-numeric: tabular-nums; }
.chart .guide { stroke: #ece6f7; stroke-width: 1; }
footer.footer { margin: 4px 0 0; }
.footer p { margin: 0 0 8px; color: var(--muted); font-size: 13px; }
.footer strong { color: var(--ink); }
.footer .meta-line { font-size: 12px; }
.totop { display: inline-flex; margin-top: 6px; color: var(--accent);
         font-weight: 600; font-size: 13px; text-decoration: none; }
.totop:hover { text-decoration: underline; }
.panel:target { outline: 3px solid rgba(168, 85, 247, .45); outline-offset: 3px; }
@media (max-width: 900px) {
  .cards { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}
@media (max-width: 640px) {
  body { padding: 18px 12px 48px; }
  .hero { padding: 6px 4px 0; }
  .lede { font-size: 15.5px; }
  .panel { padding: 20px 16px 22px; border-radius: 18px; scroll-margin-top: 118px; }
  .panel h2 { font-size: 21px; }
  .card .value { font-size: 19px; }
  .chart { min-width: 540px; }
  .chart-hint { display: block; margin: -4px 0 8px; color: var(--muted); font-size: 11.5px; }
  .toc { top: 8px; border-radius: 18px; gap: 2px; padding: 6px; }
  .toc a { padding: 6px 9px; font-size: 12px; }
  .table-wrap { border: 0; background: transparent; overflow: visible; }
  table { display: block; min-width: 0; font-size: 13.5px; }
  thead { display: none; }
  tbody { display: block; }
  tbody tr { display: block; margin: 0 0 10px; overflow: hidden;
             border: 1px solid var(--line); border-radius: 12px; background: #fff; }
  tbody tr:nth-child(even) { background: #fcfaff; }
  tbody tr:hover { background: inherit; }
  td { display: flex; align-items: baseline; justify-content: space-between; gap: 12px;
       padding: 7px 12px; border-bottom: 1px solid #f3eefb; text-align: right;
       white-space: normal; }
  td:last-child { border-bottom: 0; }
  td::before { content: attr(data-label); flex: 0 0 40%; text-align: left;
               font-size: 10.5px; font-weight: 700; text-transform: uppercase;
               letter-spacing: .06em; color: var(--muted); }
  td.num { white-space: normal; }
  td:has(code) { display: block; text-align: left; }
  td:has(code)::before { display: block; margin-bottom: 3px; }
  .panel table code { white-space: nowrap; font-size: 11px; }
  tr.alert td, tr.over td { background: transparent; }
  tr.alert { background: var(--danger-soft); }
  tr.over { background: #fff8f6; }
  tr.over td:last-child { font-weight: 700; }
  tr.alert:hover td, tr.over:hover td { background: transparent; }
  .share { justify-content: flex-end; }
}
@media (max-width: 380px) {
  .cards { grid-template-columns: 1fr; }
}
@media (prefers-reduced-motion: reduce) {
  html { scroll-behavior: auto; }
  .orb { animation: none; }
  .card { transition: none; }
}
@media print {
  body { background: #fff; color: #000; padding: 0; }
  .scene, .toc, .skip, .totop { display: none !important; }
  .hero h1, .hero h1 span { color: #2e1065; -webkit-text-fill-color: #2e1065;
                            background: none; }
  .lede, .eyebrow, .chips li { color: #333; }
  .chips li { background: #f5f5f5; border-color: #ddd; }
  .chips code { color: #000; }
  .disclaimer { background: #fff; border-color: #ccc; color: #000; }
  .panel { box-shadow: none; border: 1px solid #ddd; break-inside: avoid; }
  .panel, .card, .table-wrap, .chart { background: #fff; }
  .card .value, .card .label, .card .hint, .headline, .headline strong { color: #000; }
  .banner.good, .banner.bad { background: #fff; color: #000; border-color: #ccc; }
  tr.alert td { background: #fff; }
  a { color: #000; text-decoration: none; }
}
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
        f'<th scope="col" class="{"num" if numeric else ""}">{html.escape(title)}</th>'
        for title, numeric in headers
    )
    body = []
    for index, row in enumerate(rows):
        css = row_classes[index] if row_classes else ""
        cells = "".join(
            f'<td class="{"num" if headers[position][1] else ""}" '
            f'data-label="{html.escape(headers[position][0], quote=True)}">{cell}</td>'
            for position, cell in enumerate(row)
        )
        body.append(f'<tr class="{css}">{cells}</tr>')
    return (
        f'<div class="table-wrap"><table><thead><tr>{head}</tr></thead>'
        f"<tbody>{''.join(body)}</tbody></table></div>"
    )


def _share_cell(value: object) -> str:
    try:
        percent = max(0.0, min(float(value), 100.0))
    except (TypeError, ValueError):
        percent = 0.0
    return (
        '<span class="share">'
        f'<span class="share-track"><span class="share-fill" style="width:{percent:.1f}%">'
        "</span></span>"
        f'<span class="share-value">{percent:.1f}%</span>'
        "</span>"
    )


def _bar_chart(
    items: list[dict],
    label_key: str,
    value_key: str,
    *,
    title: str,
    gradient_id: str,
    width: int = 760,
    label_width: int = 170,
    chart_width: int = 450,
    bar_height: int = 20,
    gap: int = 12,
) -> str:
    if not items:
        return '<p class="section-note">Nothing to chart.</p>'
    maximum = max(float(item[value_key]) for item in items) or 1.0
    height = len(items) * (bar_height + gap) + gap
    parts = [
        f'<div class="chart-wrap"><svg class="chart" viewBox="0 0 {width} {height}" '
        'preserveAspectRatio="xMinYMin meet" role="img" '
        f'aria-label="{html.escape(title)}">',
        f"<title>{html.escape(title)}</title>",
        "<defs>",
        f'<linearGradient id="{html.escape(gradient_id)}" x1="0" y1="0" x2="1" y2="0">',
        '<stop offset="0" stop-color="#7c3aed"></stop>',
        '<stop offset="1" stop-color="#d946ef"></stop>',
        "</linearGradient>",
        "</defs>",
    ]
    for fraction in (0.5, 1.0):
        x = label_width + chart_width * fraction
        parts.append(
            f'<line class="guide" x1="{x:.1f}" y1="4" x2="{x:.1f}" y2="{height - 4}"></line>'
        )
    for index, item in enumerate(items):
        y = gap + index * (bar_height + gap)
        value = float(item[value_key])
        bar = chart_width * value / maximum if value > 0 else 0.0
        label = html.escape(str(item[label_key]))
        parts.append(f'<text x="0" y="{y + bar_height - 5}" class="bar-label">{label}</text>')
        parts.append(
            f'<rect x="{label_width}" y="{y}" width="{bar:.1f}" '
            f'height="{bar_height}" rx="6" fill="url(#{html.escape(gradient_id)})"></rect>'
        )
        parts.append(
            f'<text x="{label_width + bar + 8:.1f}" y="{y + bar_height - 5}" '
            f'class="bar-value">{_money(value)}</text>'
        )
    parts.append("</svg></div>")
    parts.append('<p class="chart-hint">Swipe the chart sideways to see every value.</p>')
    return "".join(parts)


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
    sentences.append(
        f"{_int(budget['over_budget_lines'])} of {_int(budget['budget_lines'])} "
        f"budget lines are over plan."
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
