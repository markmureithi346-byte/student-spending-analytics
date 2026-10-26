"""Formatting and HTML components shared by the report and the dashboard.

These helpers never compute an analytical result: they only format values that
came back from SQL and escape text before it reaches the page.
"""

from __future__ import annotations

import html
import math


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


def display_share_pcts(values: list[float], decimals: int = 1) -> list[float]:
    """Round parts of a whole so the displayed percentages add up to 100.0%.

    Ordinary rounding can make a column show 100.1% (seven equal categories each
    round to 14.3%). The largest-remainder method keeps total drift at zero by
    giving the spare tenths to the items that lost the most to rounding.
    """
    if not values:
        return []
    parts = [max(0.0, float(value)) for value in values]
    total = sum(parts)
    if total <= 0:
        return [0.0 for _ in parts]
    factor = 10 ** decimals
    scaled = [part * 100.0 * factor / total for part in parts]
    floors = [math.floor(value) for value in scaled]
    spare = 100 * factor - sum(floors)
    ranked = sorted(
        range(len(parts)),
        key=lambda index: (scaled[index] - floors[index], -index),
        reverse=True,
    )
    for index in ranked[:spare]:
        floors[index] += 1
    return [value / factor for value in floors]


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


def _short_label(value: object, limit: int = 26) -> str:
    text = str(value)
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


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
        label = html.escape(_short_label(item[label_key]))
        parts.append(f'<text x="0" y="{y + bar_height - 5}" class="bar-label">{label}</text>')
        parts.append(
            f'<rect x="{label_width}" y="{y}" width="{bar:.1f}" '
            f'height="{bar_height}" rx="6" fill="url(#{html.escape(gradient_id)})">'
            f"<title>{label}: KES {money(value)}</title></rect>"
        )
        parts.append(
            f'<text x="{label_width + bar + 8:.1f}" y="{y + bar_height - 5}" '
            f'class="bar-value">{money(value)}</text>'
        )
    parts.append("</svg></div>")
    parts.append('<p class="chart-hint">Swipe the chart sideways to see every value.</p>')
    return "".join(parts)


def grouped_bar_chart(
    items: list[dict],
    label_key: str,
    series: list[tuple[str, str, str, str]],
    *,
    title: str,
    gradient_prefix: str,
    width: int = 760,
    label_width: int = 170,
    chart_width: int = 450,
    bar_height: int = 13,
    bar_gap: int = 3,
    group_gap: int = 16,
) -> str:
    """Draw two or more values per labelled item as grouped horizontal bars.

    ``series`` entries are ``(key, label, start_colour, end_colour)``. Values are
    scaled against one shared maximum so planned and actual bars are comparable.
    """
    if not items or not series:
        return '<p class="section-note">Nothing to chart.</p>'
    maximum = (
        max(
            float(item.get(key, 0) or 0)
            for item in items
            for key, _, _, _ in series
        )
        or 1.0
    )
    group_height = len(series) * bar_height + (len(series) - 1) * bar_gap
    height = len(items) * (group_height + group_gap) + group_gap
    gradient_ids = [f"{gradient_prefix}-{index}" for index in range(len(series))]

    legend = "".join(
        f'<span><i style="background:linear-gradient(90deg,'
        f'{html.escape(start, quote=True)},{html.escape(end, quote=True)})"></i>'
        f"{html.escape(label)}</span>"
        for _, label, start, end in series
    )
    parts = [
        f'<div class="chart-legend">{legend}</div>',
        f'<div class="chart-wrap"><svg class="chart" viewBox="0 0 {width} {height}" '
        'preserveAspectRatio="xMinYMin meet" role="img" '
        f'aria-label="{html.escape(title)}">',
        f"<title>{html.escape(title)}</title>",
        "<defs>",
    ]
    for gradient_id, (_, _, start, end) in zip(gradient_ids, series):
        parts.append(
            f'<linearGradient id="{html.escape(gradient_id)}" x1="0" y1="0" x2="1" y2="0">'
            f'<stop offset="0" stop-color="{html.escape(start, quote=True)}"></stop>'
            f'<stop offset="1" stop-color="{html.escape(end, quote=True)}"></stop>'
            "</linearGradient>"
        )
    parts.append("</defs>")
    for fraction in (0.5, 1.0):
        x = label_width + chart_width * fraction
        parts.append(
            f'<line class="guide" x1="{x:.1f}" y1="4" x2="{x:.1f}" '
            f'y2="{height - 4}"></line>'
        )
    for index, item in enumerate(items):
        top = group_gap + index * (group_height + group_gap)
        label = html.escape(_short_label(item[label_key]))
        parts.append(
            f'<text x="0" y="{top + group_height / 2 + 4:.1f}" '
            f'class="bar-label">{label}</text>'
        )
        for series_index, (key, series_label, _, _) in enumerate(series):
            value = float(item.get(key, 0) or 0)
            bar = chart_width * value / maximum if value > 0 else 0.0
            y = top + series_index * (bar_height + bar_gap)
            parts.append(
                f'<rect x="{label_width}" y="{y}" width="{bar:.1f}" '
                f'height="{bar_height}" rx="4" '
                f'fill="url(#{html.escape(gradient_ids[series_index])})">'
                f"<title>{label} · {html.escape(series_label)}: "
                f"KES {money(value)}</title></rect>"
            )
            value_x = label_width + bar + 6 if bar else label_width + 4
            parts.append(
                f'<text x="{value_x:.1f}" y="{y + bar_height - 3}" '
                f'class="bar-value small">{money(value)}</text>'
            )
    parts.append("</svg></div>")
    parts.append('<p class="chart-hint">Swipe the chart sideways to see every value.</p>')
    return "".join(parts)
