# Data quality policy

The pipeline has one rule above all others: **every input row must be accounted for**.
Nothing is dropped silently. A row either loads, is rejected as a known duplicate, or is
quarantined with a reason that a human can act on.

## Row lifecycle

```
raw row
  ├── structurally broken (wrong field count)      → quarantined  MALFORMED_ROW
  ├── fails a required-field/format rule           → quarantined  (see table)
  ├── duplicate id, identical content              → rejected     DUPLICATE_IDENTICAL
  ├── duplicate id, conflicting content            → quarantined  DUPLICATE_CONFLICT
  └── passes every rule                            → accepted     → warehouse
```

## Ingestion rules

| Code | Trigger | Outcome | Why |
|---|---|---|---|
| `MALFORMED_ROW` | field count differs from the header | quarantined | unescaped commas or missing values; field boundaries are unreliable |
| `MISSING_REQUIRED_FIELD` | blank `transaction_id`, `student_id`, `transaction_date`, `amount_kes` or `category` | quarantined | the row cannot be trusted as a financial fact |
| `INVALID_TRANSACTION_ID` | id longer than 64 characters | quarantined | almost certainly a parsing artefact |
| `UNKNOWN_STUDENT` | `student_id` absent from the student dimension | quarantined | cannot attribute spending; likely a bad extract |
| `INVALID_DATE` | not a real `YYYY-MM-DD` date | quarantined | `05/08/2026` is ambiguous and `2026-02-30` does not exist |
| `DATE_OUT_OF_RANGE` | before 2020-01-01 | quarantined | outside the project's plausible window |
| `DATE_IN_FUTURE` | after the run date | quarantined | cannot be a completed transaction |
| `INVALID_AMOUNT` | not parseable as a number | quarantined | cannot be summed |
| `NON_POSITIVE_AMOUNT` | ≤ 0 | quarantined | zero-value rows carry no spending information; negatives need a refund model this project does not have |
| `AMOUNT_OUT_OF_RANGE` | > KES 100,000 | quarantined | sanity limit for student expenses; extreme values are more likely to be typos |
| `UNEXPECTED_CATEGORY` | not in the canonical list after normalisation | quarantined | silently inventing a category would corrupt every category share |
| `DUPLICATE_IDENTICAL` | same id, same cleaned content | rejected | keeps the first occurrence; the copy adds no information |
| `DUPLICATE_CONFLICT` | same id, different content | quarantined (all copies) | there is no evidence which version is correct; guessing would fabricate data |

## Normalisation (applied before rules above)

| Field | Transformation | Rationale |
|---|---|---|
| `category` | trim, lower-case, alias map (`food` → `Food`, `airtime & internet` → `Airtime and Internet`) | casing and spacing are not real differences |
| `payment_method` | trim, lower-case, alias map (`mpesa`, `M-Pesa`, `M_PESA` → `M-Pesa`) | same rail, different spelling |
| unknown payment method | `Other` + warning | the transaction is still valid, only the rail label is unknown |
| `description` / `merchant` | trim; blank → `Not provided` + warning | keeps NOT NULL guarantees without inventing facts |
| `is_recurring` | `true/yes/y/1` → 1, `false/no/n/0/blank` → 0, else 0 + warning | permissive input, explicit default |
| `amount_kes` | strip spaces and thousands separators, optional `KES` prefix, round half-up to 2 dp, convert to integer cents | money must be exact |

Duplicates are resolved **after** row validation, so an invalid row never "wins" a
duplicate comparison.

## Anomaly rule (flags, never rejects)

A transaction is flagged when all of the following hold:

1. the student has at least 3 transactions in that category,
2. the amount is more than **3× the student's own average** for that category,
3. the amount exceeds **KES 2,500**.

Flags are recomputed from scratch on every run (`is_anomaly` reset, then re-derived), so
they can never go stale. A flag means "look at this", not "this is wrong".

## Reconciliation

```
rows_read = rows_accepted + rows_rejected + rows_quarantined
rows_accepted = rows_inserted + rows_updated + rows_unchanged
```

Both are checked at the end of every run and stored in `data_quality_results`.
`rows_read` counts physical CSVs rows excluding blank lines; budget rows are validated
separately and are not part of this equation.

## Automated checks (12)

| Check | Fails when |
|---|---|
| `reconciliation_counts` | either identity above is broken |
| `no_duplicate_transaction_ids` | the fact table somehow holds a duplicate key |
| `no_orphan_transaction_references` | a transaction loses its student or category |
| `no_orphan_budget_references` | a budget row loses its student or category |
| `amounts_are_positive` | a non-positive amount reached the fact table |
| `required_text_not_blank` | description, merchant or payment method is empty |
| `no_future_dated_transactions` | a future date reached the fact table |
| `transaction_view_row_parity` | `v_transactions` row count or total differs from the base table |
| `monthly_aggregation_matches_base` | monthly view totals do not equal the base total |
| `anomaly_rate_within_threshold` | more than 5% of transactions are flagged |
| `transactions_present` | the warehouse has no transactions |
| `budgets_present` | budget analysis would be meaningless because no budgets exist |

A failing check makes `run_pipeline.py` exit with code `1` and marks the run `failed`,
but the report is still generated so the failure can be inspected.

## Reviewing quarantined rows

1. Open `data/quarantine/rejections_<run_id>.csv` (one row per rejected/quarantined
   record with its reason).
2. For a data-entry error, correct the source row in `data/raw/student_expenses.csv`.
3. Rerun the pipeline. Corrected rows are new inserts or updates; the old quarantine
   entries remain as history under their own `run_id`.
4. For `DUPLICATE_CONFLICT`, decide which version is authoritative, delete the other
   line from the source file, and rerun.

There is no "resolved" state in the warehouse yet — that is a documented limitation.

## What is out of scope

- Refunds and chargebacks (negative amounts) are quarantined, not modelled.
- Cross-file duplicate detection (the same purchase in two extracts) is not attempted;
  `transaction_id` is assumed to be the source's stable identifier.
- Statistical outlier detection (IQR/z-score) is deliberately not used: with ~350 rows
  and per-student-category buckets it would be unstable and hard to explain.

## Test coverage

| Area | Test module |
|---|---|
| Extraction failures, BOM, malformed rows, dimension files | `tests/test_extract.py` |
| Every validation code, normalisation, duplicate policy, accounting | `tests/test_validate.py` |
| Idempotent load, updates, constraints, rejection storage, run lifecycle | `tests/test_load.py` |
| Aggregations, shares, weekday mapping, budget variance, anomalies | `tests/test_analytics.py` |
| All 12 checks, failure detection, persistence | `tests/test_quality.py` |
| End-to-end run, reconciliation, rerun, full refresh, failure recording | `tests/test_pipeline.py` |
