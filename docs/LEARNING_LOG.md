# Learning log

A record of what was built, why, what went wrong, and what to revisit. Written to be
useful to whoever maintains this project next — including future me.

## Phase status

| Phase | Status | Evidence |
|---|---|---|
| 0. Environment and setup | done | venv on Python 3.13.14, SQLite 3.50.4, git repo on `main` |
| 1. Understanding the data | done | three raw CSVs, 380 rows, documented defects |
| 2. Extraction | done | `extract.py`, file-level failures, per-row malformed detection |
| 3. Cleaning and validation | done | 13 reason codes, normalisation, duplicate policy |
| 4. Database design and loading | done | 8 tables, 12 views, PK/FK/CHECK, upsert loading |
| 5. SQL analytics | done | monthly, category, weekday, budget, week-over-week queries |
| 6. Analytical modelling | done | fact/dimension split, single grain per view |
| 7. Quality and testing | done | 12 checks, 61 tests |
| 8. Logging and repeatability | done | console + file logging, run table, idempotent rerun |
| 9. Visualisation | done | dependency-free HTML report from SQL |
| 10. Documentation | done | README, data dictionary, quality policy, examples |

## Decisions worth remembering

- **Money as integer cents.** Storing `REAL` looks simpler until `SUM()` returns
  `556862.2700000001`. Cents keep every total exact and make `amount_cents` comparisons
  safe in CHECK constraints.
- **Upsert plus hash, not truncate-and-reload.** A rerun must be safe and must not
  destroy `first_loaded_at` history. The content hash decides insert / update /
  unchanged without comparing timestamps.
- **Quarantine instead of delete.** A rejected financial row is evidence. Keeping it in
  an audit table plus a CSV makes the decision reviewable.
- **Conflict means quarantine both copies.** With two different amounts under one id,
  picking one would invent data. Refusing to choose is the honest action.
- **Views own the definitions.** `amount_kes`, month, weekday and budget variance are
  defined once in SQL; the report and the tests read the same objects, so they cannot
  disagree.
- **Flagging is not validation.** A KES 24,000 laptop repair is valid and interesting;
  mixing it with invalid data would either lose information or corrupt the warehouse.
- **Synthetic budgets need a deliberate design.** Random budget ranges did not reliably
  produce overruns, so a few student/month/category lines use a 0.55–0.70 scaling factor
  against actual spend. This is documented in the generator; it is a teaching device,
  not a claim about real students.

## Bugs hit during development

1. **Idempotency test read the wrong run.** Two pipeline runs within the same second
   produced identical `started_at` values, and the test ordered by
   `started_at DESC, run_id DESC`. `run_id` contains random hex, so it picked the first
   run and reported `inserted = 348` on a rerun.
   *Cause:* ordering without a strictly monotonic tie-breaker.
   *Fix:* order by `rowid DESC` in the test.
   *Lesson:* any "latest record" query needs a column that is guaranteed unique and
   ordered.

2. **Duplicate injection could sample invalid rows.** The generator originally sampled
   rows to duplicate from the full list, which already contained planted defects. A
   conflicting copy of an already-invalid row never reaches duplicate resolution, so the
   expected reason counts became unpredictable.
   *Fix:* sample duplicate sources only from valid base rows (`TXN-0…`).
   *Lesson:* test fixtures and generators need the same invariants as production code.

3. **Nested same-type quotes in f-strings require Python 3.12+.** The table renderer uses
   `f'<th class="{"num" if numeric else ""}">'`. This is PEP 701 syntax.
   *Fix:* documented Python 3.12+ and tested on 3.13.

4. **Report cards wrapped badly at six columns.** The KPI value `KES 556,862.27` broke
   onto two lines in a 150 px grid cell.
   *Fix:* raised the grid minimum to 200 px and prevented value wrapping.

## Concepts this project exercises

Extraction boundaries; per-row error isolation; normalisation vs validation; policy for
duplicates; surrogate vs natural keys; fact/dimension grain; composite primary keys;
foreign keys and CHECK constraints; transactions; upsert and change detection; hashing
for idempotency; CASE expressions; joins; CTEs; window functions (`LAG`, and window
aggregates via SQLite); reconciliation accounting; logging levels; test doubles; HTML
escaping; and the difference between "valid" and "unusual".

## Next exercises (for the learner, not the pipeline)

1. Add a query answering "what share of spending is discretionary?" and verify the result
   by hand against `v_category_totals`.
2. Add a rule rejecting a student-wide daily total above KES 20,000, with a test that
   proves it fires.
3. Add a `payment_method` dimension table and join it, without breaking existing tests.
4. Extend the report with a weekly chart built from `v_weekly_spending`.
5. Add a `source_file_hash` column to `pipeline_runs` so identical reruns can be
   recognised before any loading happens.

## Open questions

- Should quarantined rows have a resolution workflow (status + reviewer + note)?
- Should corrected records be linked to the run that superseded them?
- Is a calendar-week grain enough, or is a real date dimension needed for reporting?
