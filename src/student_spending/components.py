"""Formatting and HTML components shared by the report and the dashboard.

These helpers never compute an analytical result: they only format values that
came back from SQL and escape text before it reaches the page.
"""

from __future__ import annotations

import html


def money(value: object) -> str:
    try:
        return f"{float(value):,.2f}"
    except (TypeError, ValueError):
        return "0.00"


def integer(value: object) -> str:
    try:
        return f"{int(value):,}"
    except (TypeError, ValueError):
        return "0"


def percent(value: object) -> str:
    try:
        return f"{float(value):.1f}%"
    except (TypeError, ValueError):
        return "0.0%"


def share_cell(value: object) -> str:
    try:
        percent_value = max(0.0, min(float(value), 100.0))
    except (TypeError, ValueError):
        percent_value = 0.0
    return (
        '<span class="share">'
        f'<span class="share-track"><span class="share-fill" style="width:{percent_value:.1f}%">'
        "</span></span>"
        f'<span class="share-value">{percent_value:.1f}%</span>'
        "</span>"
    )


def table(
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


def bar_chart(
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
            f'class="bar-value">{money(value)}</text>'
        )
    parts.append("</svg></div>")
    parts.append('<p class="chart-hint">Swipe the chart sideways to see every value.</p>')
    return "".join(parts)
