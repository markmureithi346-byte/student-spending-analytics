# Data dictionary

## Raw inputs (`data/raw/`)

All three files are synthetic. UTF-8 (BOM tolerated), comma-separated, first row is a
header, dates are ISO `YYYY-MM-DD`.

### `student_expenses.csv`

| Column | Type | Required | Rules |
|---|---|---|---|
| `transaction_id` | text | yes | unique per transaction after cleaning; ≤ 64 chars |
| `student_id` | text | yes | must exist in `student_profiles.csv` |
| `transaction_date` | date | yes | `YYYY-MM-DD`, 2020-01-01 ≤ date ≤ today |
| `amount_kes` | decimal | yes | > 0, ≤ 100,000.00; thousands separators and a `KES` prefix are tolerated |
| `category` | text | yes | matched case-insensitively against the canonical list |
| `description` | text | no | blank becomes `Not provided` (warning) |
| `payment_method` | text | no | aliases are normalised; unknown values become `Other` (warning) |
| `merchant` | text | no | blank becomes `Not provided` (warning) |
| `is_recurring` | boolean | no | `true/yes/y/1` or `false/no/n/0/blank`; anything else → `False` + warning |

### `student_profiles.csv`

| Column | Type | Rules |
|---|---|---|
| `student_id` | text | unique; primary key of the dimension |
| `profile_label` | text | anonymized label such as `Profile A` |
| `campus` | text | free text |
| `study_year` | integer | 1–6 |
| `monthly_income_kes` | decimal | ≥ 0, stored as `monthly_income_cents` |

### `student_budgets.csv`

| Column | Type | Rules |
|---|---|---|
| `student_id` | text | must exist in the student dimension |
| `budget_month` | text | `YYYY-MM` |
| `category` | text | must be a canonical category |
| `budget_kes` | decimal | ≥ 0, stored as `budget_cents` |

Budget rows with unknown students, unknown categories, malformed months or bad amounts
are skipped with a warning and counted in the run log. They are not facts about
transactions, so they do not enter the row reconciliation equation.

## Canonical categories

`Food`, `Transport`, `Rent`, `Utilities`, `Education`, `Airtime and Internet`,
`Entertainment`, `Personal Care`, `Other`.

`Entertainment`, `Personal Care` and `Other` are marked `is_discretionary = 1`.

## Canonical payment methods

`M-Pesa`, `Cash`, `Card`, `Bank Transfer`, `Other`.

## Warehouse tables

### `transactions` (fact, grain: one transaction)

| Column | Type | Notes |
|---|---|---|
| `transaction_id` | TEXT PK | natural key, prevents double loading |
| `student_id` | TEXT FK | → `students.student_id` |
| `transaction_date` | TEXT | ISO date, CHECKed with a GLOB pattern |
| `amount_cents` | INTEGER | > 0; money is never stored as a float |
| `category` | TEXT FK | → `categories.category` |
| `description`, `merchant`, `payment_method` | TEXT | never blank after cleaning |
| `is_recurring` | INTEGER | 0/1 |
| `record_hash` | TEXT | SHA-256 of the cleaned business fields; drives change detection |
| `is_anomaly`, `anomaly_reason` | INTEGER/TEXT | recomputed on every run |
| `first_loaded_at`, `last_updated_at` | TEXT | UTC ISO timestamps |

### `budgets` (fact, grain: student × month × category)

Composite primary key `(student_id, budget_month, category)`.

### Audit and metadata

| Table | Grain | Notes |
|---|---|---|
| `transactions_quarantine` | one row input row per run | invalid rows held for review |
| `rejected_transactions` | one row per run | duplicate copies discarded by policy |
| `pipeline_runs` | one row per execution | counts, status, message |
| `data_quality_results` | one row per check per run | observed vs expected evidence |

## Derived fields in `v_transactions`

| Field | Definition |
|---|---|
| `amount_kes` | `amount_cents / 100.0` |
| `transaction_month` | `substr(transaction_date, 1, 7)` |
| `transaction_year` | first four characters of the date |
| `week_of_year` | `strftime('%W', ...)` (weeks start Monday) |
| `year_week` | `strftime('%Y-W%W', ...)`, used for week-over-week comparisons |
| `weekday_name` | English day name derived from `%w` |
| `is_discretionary` | copied from the category dimension |

`week_of_year` is a calendar-week identifier, not an ISO-8601 week number. It is
consistent within this dataset because all months are in 2026 and no week straddles a
year boundary.
