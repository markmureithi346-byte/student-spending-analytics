# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[semantic versioning](https://semver.org/spec/v2.0.0.html).

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

### Fixed

- Rerun classification could read an earlier pipeline run when two runs shared
  the same start timestamp; the integration test now orders by insertion order.
- `v_flagged_transactions` exposes `amount_kes` only, which broke an example
  query ordering by `amount_cents`; the query now uses the published column.
- `v_week_over_week` lacked the profile label, forcing an unnecessary join in
  the analytics layer and in example queries.
- KPI cards wrapped awkwardly in narrow layouts; the report grid now has a
  minimum card width and non-wrapping values.
