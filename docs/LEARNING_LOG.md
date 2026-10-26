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
| 7. Quality and testing | done | 12 checks; the suite grew to 92 tests by phase 14 |
| 8. Logging and repeatability | done | console + file logging, run table, idempotent rerun |
| 9. Visualisation | done | dependency-free HTML report from SQL |
| 10. Documentation | done | README, data dictionary, quality policy, examples |
| 11. Packaging and release | done | `pyproject.toml`, console script, wheel build, CI matrix, MIT licence |
| 12. Report experience | done | animated purple theme, sticky nav, responsive stacked tables, refreshed screenshots |
| 13. Interactive dashboard | done | `web.py`, `student-spending serve`, 20 dashboard tests, browser-checked at 1280 px and 390 px |
| 14. Upload platform | done | `platform.py`, `/upload`, isolated workspaces, 11 upload tests (92 total), browser-checked upload and analysis |

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
- **Editable install, not a self-contained wheel.** The tool reads `data/`, `sql/` and
  writes `warehouse/` relative to the project, so the supported installation is
  `pip install -e .` from the checkout. A wheel install falls back to resolving paths
  from the current directory, which is verified, but shipping the schema and sample data
  inside a wheel would be a different product decision.
- **The report is a product surface, not a dump.** Every figure still comes from SQL,
  but the page now has a sticky section index, a one-sentence summary, KPI cards and
  charts. Below 640 px each table row becomes a labelled card: horizontal scrolling hid
  columns entirely on a phone. Animation is CSS-only and switches off for
  `prefers-reduced-motion`; the print stylesheet drops the backdrop and chrome.
- **The dashboard is a viewer, not a second pipeline.** It imports the same formatting
  helpers, opens the same warehouse read-only and queries the same views. Nothing is
  computed in Python except display strings and booleans. Separating it from the batch
  job keeps one source of truth and means a dashboard bug cannot corrupt data.
- **GET forms instead of a JavaScript app.** The whole state lives in the URL, so a
  filtered view can be bookmarked, reloaded, tested with plain HTTP and downloaded as
  CSV without duplicating logic. The trade-off is a full page load per Apply, which is
  acceptable for a local single-user tool and keeps the no-dependency constraint.
- **Untrusted input never becomes SQL text.** Dates are parsed, students/categories/
  payment methods come from allow-lists, ordering comes from a fixed dictionary and the
  search term is a bound `LIKE` pattern with `ESCAPE '\'`. Values that fail validation
  reset to the safe default and the field explains why.
- **Two independent read-only layers.** The SQLite URI includes `mode=ro` and every
  connection also runs `PRAGMA query_only = ON`. Tests attempt writes through the same
  connection factory; both layers would have to fail for a handler to modify data.
- **An upload is a workspace, not an edit.** Every bundle gets a generated id, its own
  input directory, SQLite file and report. The committed warehouse is never in the write
  path, so a bad upload cannot damage the sample analysis and two datasets can stay
  open in different tabs. The cost is disk usage and no delete/retention UI yet.
- **One pipeline, called from two places.** The upload route imports `PipelineOptions`
  and `run_pipeline` from the CLI instead of reimplementing loading. Capturing stdout
  keeps the HTTP response clean, and a process-wide lock serialises runs.
- **A failed quality check is not a failed upload.** Exit code `1` still leaves a usable
  warehouse and report, so the analysis opens with a banner. Only exit codes `2`/`3` or
  zero accepted rows are treated as upload failures, and those remove partial files.
- **The multipart form is parsed, not trusted.** `email.parser` reads the parts, fixed
  canonical filenames replace client names, the analysis id has a strict pattern, and
  validation happens before the pipeline is called. The form also requires an explicit
  synthetic-data confirmation.
- **Browser security headers have behaviour side effects.** `Referrer-Policy:
  no-referrer` made Chromium send `Origin: null` on the form POST, so the origin guard
  rejected every real upload even though HTTP tests passed. Switching to `same-origin`
  keeps cross-site referrers private while allowing the browser to prove its origin.
- **Analysis state belongs in the URL.** The `analysis` id is threaded through filters,
  pagination, export and report links. No session store is needed, and an uploaded view
  survives reloads and sharing just like the sample dashboard.
- **Browser verification is part of "done".** The dashboard was checked in headless
  Chrome at 1280 px and 390 px: no horizontal overflow, full-width mobile controls,
  correct stacked labels, sticky navigation, reduced-motion behaviour and an empty
  console. Rendering bugs (grammar, clipped headers, dead grid space) only appeared in
  the screenshots, not in the unit tests.

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

5. **Python 3.13 virtual environments do not ship setuptools.** `pip install -e .`
   against a setuptools backend failed until the build dependency was resolved; the
   wheel build then reported `ModuleNotFoundError: No module named 'setuptools'` inside
   the venv.
   *Cause:* newer CPython venvs bootstrap pip only, and build isolation normally fetches
   the backend.
   *Fix:* declared `setuptools>=77` in `[build-system]` and installed it in the venv for
   local, no-isolation checks.
   *Lesson:* "no runtime dependencies" is not "no build dependencies".

6. **`python -m student_spending --version` printed `__main__.py 1.0.0`.** argparse
   derives the program name from `sys.argv[0]`, which is the module file when run with
   `-m`.
   *Fix:* set `prog="student-spending"` explicitly so every entry point presents the same
   name.

7. **The report's `.num` helper class tinted every number magenta.** The same class styled
   the section eyebrow and right-aligned table cells, so the new `.panel .num` colour
   applied to counts and totals as well.
   *Cause:* a generic utility class reused for two unrelated elements.
   *Fix:* renamed the eyebrow class to `.section-no`.
   *Lesson:* utility class names are global; scope them to a component.

8. **Responsive tables originally scrolled sideways.** At 390 px the quality table
   showed only CHECK and RESULT; OBSERVED and EXPECTED were off-screen and rows became
   very tall.
   *Fix:* below 640 px, hide the header row and render each row as labelled cards using
   `data-label` attributes, with the identifier rows laid out on their own line.
   *Lesson:* a mobile layout has to be tested at a real phone width; a min-width plus
   overflow rule is not a responsive design.

9. **Search turned `%` and `_` into wildcards.** A query for `50%` matched any merchant
   starting with `50`, and `_` matched any single character.
   *Cause:* the term was bound as a parameter, which prevents injection but not
   wildcard expansion inside `LIKE`.
   *Fix:* escape `\`, `%` and `_` in the term and add `ESCAPE '\'` to both columns.
   *Lesson:* parameterisation stops SQL injection; it does not make pattern syntax safe.

10. **The browser check filtered on a fixture-only merchant.** The script searched for
    a name that exists only in `tests/test_web.py`, so the live page returned the empty
    state, `.resultbar` was `null`, and the script crashed.
    *Fix:* inspect the committed warehouse and use a merchant that is actually there
    (`Tech Repairs Nairobi`), then assert the row and amount.
    *Lesson:* verification scripts run against real data, not the test fixture.

11. **Summary grammar broke at one row.** The filtered page said "1 transactions from
    1 students total …" and "1 transaction are flagged".
    *Fix:* a `_plural` helper and verb agreement chosen from the count; the browser check
    now asserts the sentence for a single result.
    *Lesson:* empty and single-row states are where template wording fails.

12. **Split tables clipped their headers.** A global `min-width: 520px` on tables was
    wider than each half of a two-column breakdown, so `TOTAL KES` was cut off and the
    tables looked misaligned.
    *Fix:* give `.split table` its own `min-width: 0` and tighter cell padding.
    *Lesson:* global layout rules need an escape hatch for nested components.

13. **The favicon response was an invalid 204.** It sent `204 No Content` together with
    `Content-Length`, which contradicts the status.
    *Fix:* send only the status and no-store header for the favicon; keep the body and
    length on real pages.
    *Lesson:* no-content responses must not describe a body.

14. **Apply/Reset left a dead column in the filter grid.** Search spanned two columns and
    the buttons sat in a separate row, producing a visible gap at desktop width.
    *Fix:* place the actions in the same grid row with `align-self: end`, then override
    the span below 900 px and 640 px.
    *Lesson:* grid spans have to be re-checked at every breakpoint, not just the widest.

15. **Every real browser upload was rejected with 403.** The unit and HTTP tests passed
    because they sent no `Origin` or a matching one. Chromium, following
    `Referrer-Policy: no-referrer`, sent `Origin: null` on the multipart form POST, and
    the same-origin guard rejected it. The page navigated to a network error page and
    the pipeline never ran.
    *Fix:* send `Referrer-Policy: same-origin` and keep rejecting `Origin: null`.
    *Lesson:* security headers change browser request behaviour; an upload flow must be
    exercised from a real form submission, not only from a hand-built HTTP request.

16. **The filter-link test pinned query-string order.** It expected the analysis id
    before the category, but `_export_href` emits the date window first. The product was
    correct; the assertion was brittle.
    *Fix:* parse the URL with `urlsplit` and `parse_qs`, then assert the parameter values.
    *Lesson:* test URL semantics, not the incidental order of encoded parameters.

## Concepts this project exercises

Extraction boundaries; per-row error isolation; normalisation vs validation; policy for
duplicates; surrogate vs natural keys; fact/dimension grain; composite primary keys;
foreign keys and CHECK constraints; transactions; upsert and change detection; hashing
for idempotency; CASE expressions; joins; CTEs; window functions (`LAG`, and window
aggregates via SQLite); reconciliation accounting; logging levels; test doubles; HTML
escaping; HTTP request/response handling; multipart/form-data parsing and POST/redirect
flows; origin and `Sec-Fetch-Site` checks; referrer-policy side effects; ephemeral
workspaces and path allow-lists; server-side rendering; GET form state; threaded request
handling; read-only database connections; `LIKE` escaping; content security policy; CSV
formula injection; and the difference between "valid" and "unusual".

## Next exercises (for the learner, not the pipeline)

1. Add a query answering "what share of spending is discretionary?" and verify the result
   by hand against `v_category_totals`.
2. Add a rule rejecting a student-wide daily total above KES 20,000, with a test that
   proves it fires.
3. Add a `payment_method` dimension table and join it, without breaking existing tests.
4. Extend the report with a weekly chart built from `v_weekly_spending`.
5. Add a `source_file_hash` column to `pipeline_runs` so identical reruns can be
   recognised before any loading happens.
6. Add a JSON endpoint that reuses `parse_filters` and `build_where`, then assert it
   returns the same totals as the HTML summary for the same URL.
7. Add a saved-view feature without putting user text into SQL: store only validated
   filter values and rebuild the query on load.

## Open questions

- Should quarantined rows have a resolution workflow (status + reviewer + note)?
- Should corrected records be linked to the run that superseded them?
- Is a calendar-week grain enough, or is a real date dimension needed for reporting?
- Should the dashboard remember a preferred date range, and if so, where — URL, cookie
  or warehouse table?
- If this ever held real data, what authentication and access logging would be required
  before any route left loopback?
