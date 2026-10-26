# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[semantic versioning](https://semver.org/spec/v2.0.0.html).

## [1.1.0] - 2026-10-26

Adds an interactive, read-only dashboard over the existing warehouse. The report and
dashboard now share one visual theme and one set of HTML formatting helpers.

### Added

- `student-spending serve` starts a dependency-free dashboard on
  `http://127.0.0.1:8000`, with `--host`, `--port`, `--db` and `--open`.
- Filters for date window, student, category, payment method, flagged-only, merchant or
  description search, sort order and page size. Filters combine, are expressed as GET
  fields, and produce bookmarkable URLs.
- A filtered summary with total spend, transaction and student counts, average
  transaction and average daily spend, plus a transaction table with pagination,
  monthly trend chart, category/merchant/payment breakdown and a flagged-only shortcut.
- CSV export that respects the active filters, carries a date-scoped filename and
  neutralises spreadsheet-formula prefixes.
- Read-only warehouse access (`mode=ro` plus `PRAGMA query_only = ON`), short-lived
  per-request connections, loopback binding by default, a restrictive CSP and
  no-store/no-referrer/nosniff headers.
- Input validation with field-level messages and safe resets for invalid dates, unknown
  students/categories/payment methods, tampered sort values, oversized search terms and
  out-of-range pages.
- Shared `theme.py` and `components.py`, used by both the report and the dashboard.
- Twenty dashboard tests covering filter semantics against hand-written SQL, literal
  `%`/`_` search, injection attempts, pagination clamping, HTML escaping, CSV guards,
  routing, security headers, read-only enforcement and CLI dispatch.
- Dashboard screenshots at desktop and phone widths in `docs/images/`.

### Changed

- The CLI gained an optional `serve` subcommand; pipeline flags and exit codes are
  unchanged, and root options still work.
- Release version is now `1.1.0`.
- README, learning log and test counts document the dashboard, its security model and
  its limitations.

### Fixed

- Search treated user-supplied `%` and `_` as SQL wildcards; both are now escaped and
  matched literally.
- Summary wording read "1 transactions from 1 students total …"; singular and plural
  verbs now agree.
- The two breakdown tables clipped their headers at desktop width because the global
  table minimum width exceeded each grid column; the split layout now uses its own
  smaller minimum.
- The favicon response sent a `204` status with a `Content-Length` header, which is not
  a valid no-content response.
- Unexpected handler exceptions now return a styled `500` page and are logged instead
  of dropping the connection.

## [1.0.0] - 2026-10-26

First complete release: a packaged, tested pipeline that runs from raw CSV to a
validated warehouse, analytics, quality evidence and an HTML report.

### Added

- Staged pipeline: extraction, validation, loading, anomaly flagging, data
  quality checks and reporting, orchestrated by a single CLI.
- SQLite warehouse with eight tables and twelve analytical views, including
  dimension/fact keys, CHECK constraints and integer-cent money storage.
- Validation with thirteen reason codes, normalisation of categories, payment
  methods and amounts, and an explicit duplicate policy: identical copies are
  rejected, conflicting copies are quarantined in full.
- Upsert loading driven by SHA-256 record hashes, so reruns insert nothing and
  update nothing unless an upstream record actually changed.
- Audit trail for every non-accepted row in warehouse tables and a per-run
  CSV under `data/quarantine/`.
- Twelve automated data quality checks, including two reconciliation identities
  asserted on every run, with results stored in `data_quality_results`.
- Anomaly flagging (substantial spend relative to the student's own category
  average) that flags rows without removing them.
- Deterministic synthetic data generator: 380 transactions across six profiles
  and three months, including 32 rows that must be quarantined or rejected and
  15 injected normalisation issues that must be repaired without loss.
- Dependency-free HTML report with inline SVG charts, built only from SQL
  results.
- 61 unittest cases covering every stage plus end-to-end and rerun behaviour.
- Documentation: README, data dictionary, data quality policy, learning log and
  eleven example queries.
- Packaging: `pyproject.toml`, `student-spending` console script,
  `python -m student_spending`, and a `--version` flag.
- GitHub Actions CI running tests and two consecutive pipeline runs on Ubuntu
  and Windows with Python 3.12 and 3.13.
- MIT license and this changelog.

### Changed

- Redesigned the HTML report around a purple animated backdrop with sticky section
  navigation, an at-a-glance summary, KPI cards, gradient charts and share bars.
- Tables now stack into labelled cards on narrow screens instead of hiding columns
  behind horizontal scrolling; charts carry a swipe hint at the same widths.
- Added reduced-motion support, a skip link, chart descriptions, print styles and
  higher-contrast over-budget emphasis.

### Fixed

- Rerun classification could read an earlier pipeline run when two runs shared
  the same start timestamp; the integration test now orders by insertion order.
- `v_flagged_transactions` exposes `amount_kes` only, which broke an example
  query ordering by `amount_cents`; the query now uses the published column.
- `v_week_over_week` lacked the profile label, forcing an unnecessary join in
  the analytics layer and in example queries.
- KPI cards wrapped awkwardly in narrow layouts; the report grid now has a
  minimum card width and non-wrapping values.
