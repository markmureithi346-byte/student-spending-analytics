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
| 7. Quality and testing | done | 12 checks; the suite grew to 95 tests by phase 15 |
| 8. Logging and repeatability | done | console + file logging, run table, idempotent rerun |
| 9. Visualisation | done | dependency-free HTML report from SQL |
| 10. Documentation | done | README, data dictionary, quality policy, examples |
| 11. Packaging and release | done | `pyproject.toml`, console script, wheel build, CI matrix, MIT licence |
| 12. Report experience | done | animated purple theme, sticky nav, responsive stacked tables, refreshed screenshots |
| 13. Interactive dashboard | done | `web.py`, `student-spending serve`, 20 dashboard tests, browser-checked at 1280 px and 390 px |
| 14. Upload platform | done | `platform.py`, `/upload`, isolated workspaces, 11 upload tests, browser-checked upload and analysis |
| 15. Single-file upload | done | one transactions CSV, derived students, budget variance skipped, 95 tests |
| 16. Per-student money plan | done | `personal.py`, `/plan`, user-defined categories, add-row controls, analysis rendered in-page without saved plans |
| 17. Exact shares, receipt and dark theme | done | largest-remainder shares in the planner, dashboard and report, inline printable receipt placed directly under the analysis, drifting-spark dark-purple backdrop, 138 tests, browser-checked at 1440 px and 390 px |
| 18. Local demo accounts | done | `accounts.py`, `/signup`, `/login`, `/logout`, scrypt hashes, hashed session tokens, gated `/plan` and `/upload` with the sample dashboard still public, 157 tests, browser-checked at 1440 px, 1280 px and 390 px |
| 19. Sign-in loading screen and button motion | done | authenticated `/welcome` with an animated tick, rings and progress bar, `meta refresh` hand-off after 2.6 s, CSS-only button hover/press/sheen across the platform, reduced-motion and phone fallbacks, 158 tests, browser-checked at 1440 px and 390 px with the redirect confirmed |
| 20. Plan It brand on the loading screen | done | packaged `plan-it-logo.jpg` served from `/assets/`, `img-src 'self' data:`, wordmark and slogan on `/welcome`, 13-second linear countdown, animated logo tile and rings, 158 tests, browser-checked at 1440 px and 390 px with a measured 13.2-second redirect |
| 21. Bottom add-row controls | done | **+** bars under both planner lists, `#categories-end`/`#spending-end` anchors, `scroll-margin-top` landing the new row and control in view, `scroll-behavior: auto` on served pages so the landing is instant, a 0.26 s `row-pop` on only the new row, draft preserved through the no-save round-trip, 158 tests, 26 browser checks at 1280 px plus a 390 px phone pass and a reduced-motion pass, measured at about 250–650 ms per add |

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
- **One CSV is enough for an upload.** The transaction file already names every student,
  so requiring a second file duplicated information the uploader might not have. The
  derived dimension uses the id as its label and stores unknown descriptive fields as 0
  or `Not provided`; no budget rows means the report says variance is unavailable rather
  than presenting a misleading "0 of 0" result. The CLI keeps the full three-file model.
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
- **The planner belongs to one student, not the warehouse.** Its input is a worksheet,
  not a batch fact table. Analysing it inside the response keeps the pipeline's
  reconciliation identities and sample dataset untouched, and avoids a second store.
  The trade-off is no SQL analytics over plans and no cross-student history.
- **User-defined categories need a canonical key.** The student can write `Food`,
  `food` or `FOOD`; storing the first spelling and matching with `casefold()` keeps the
  display readable while treating the rows as one category. Duplicates are rejected
  rather than merged silently, so the student sees the clash.
- **Plan amounts are optional, and zero is not missing.** A category with no planned
  amount can still receive spending; it is labelled **No plan**, not treated as a
  budget of zero or as an error. When every planned amount is blank, the page reports
  actual spending and shares and says there is no plan to compare.
- **The analysis lives in the response, not in a store.** `POST /plan` validates the
  draft, analyses it and returns the same page with totals and SVG charts below the form
  (`#analysis`), status 200 and no `Location`. The student keeps every entered value and
  can adjust and resubmit immediately. Removing saved plan files, plan ids, the
  bookmarkable result route and edit-as-copy also removed the only reason the planner
  needed a filesystem. The trade-off is that a result cannot be revisited by URL; the
  browser page is the only copy unless the student prints or saves it.
- **Two rendering charts, one scale.** The ranked chart answers "where did the money
  go?"; the grouped chart puts each category's plan next to its actual spend on a shared
  axis. Both are inline SVG with tooltips, and both use the same shortened labels so a
  long user-defined name does not collide with the value.
- **Add-row is a draft round-trip, not a script.** The **+** buttons beside the Categories
  and Spending headings submit the current form to the server with `action=add_category`
  or `action=add_spending`, and the page is re-rendered with one more row and every draft
  value intact. They do not validate or save. This keeps the no-JavaScript and
  strict-CSP constraints, at the cost of a page reload per added row; hidden row counts
  make the added rows survive validation errors and final submission.
- **Two row maxima share one parser budget.** Each category row posts three fields and
  each spending row four, so a form with both lists at 100 needs room for roughly 700
  fields. `MAX_FORM_FIELDS` sits at 800, and a test renders an analysis with both lists
  at their maxima so the constant cannot drift below what the form can actually produce.
- **Start with one row, grow on demand.** Both lists open with a single row and use the
  **+** control to add the next one. Twelve empty rows made the form look like homework
  and buried the controls; one row matches how a student fills a notebook. The minimum
  stays two categories and one spending row, so the validation message still teaches the
  requirement instead of the layout hiding it.
- **Accounts gate the personal tools; they do not own the showcase.** The sample dashboard
  and report stay public because they are the project's portfolio, while `/plan` and
  `/upload` ask for a session because they represent one student's workspace. Gating
  everything would have hidden the demo behind a form; gating nothing would have made the
  new sign-in pages decorative.
- **Passwords are hashed, sessions are hashed, and neither is reversible.** `hashlib.scrypt`
  with a per-account random salt makes the stored value useless without the password, and
  `hmac.compare_digest` avoids a timing oracle. The cookie carries a random token while
  SQLite stores only its SHA-256 digest, so reading `data/accounts.db` does not hand out
  live sessions. There is no secret key to configure, which suits a zero-dependency demo.
- **Login errors are deliberately vague.** One message covers an unknown email, a wrong
  password and a missing account, and an unknown email is still verified against a cached
  dummy hash. The point is to avoid becoming an account-enumeration oracle, not to be
  unhelpful: the message still tells the student what to do next.
- **A `next` parameter is an open-redirect risk.** `_safe_next` accepts only `/`, `/plan`
  and `/upload` with a re-encoded query, and rejects absolute URLs, protocol-relative URLs
  and anything longer than 200 characters. A sign-in page that redirects anywhere is a
  phishing tool, even on loopback.
- **The password field never comes back in an error.** Validation errors re-render the
  display name and email so the student does not retype them, but password fields are
  always blank. Repopulating them would put the secret into the HTML and the browser's
  form history for no benefit.
- **Rate limiting is small and in memory.** Eight failures per address in five minutes
  returns `429` with `Retry-After`, and a successful login clears the counter. It is not a
  distributed defence, but it makes scripted guessing against one mailbox slow enough to
  notice; a production service would use a shared store and account-level throttling.
- **A loading screen is its own page, not an overlay.** The CSP forbids scripts, so a
  spinner drawn on the sign-in form could never start the navigation that follows it.
  Moving the confirmation to `/welcome`, reached by the normal `303`, lets the page use a
  `meta refresh` to hand off to the destination while staying authenticated, skippable
  with a real link, and testable with plain HTTP. The cost is one extra round-trip, which
  the 2.6-second staging screen turns into an intentional pause rather than latency.
- **Motion belongs to the control, not to a script.** Hover lift, press scale and the
  sheen sweep are declared on `.button` and on bare `button`, so a control added later
  inherits them without new markup, and reduced-motion collapses the whole set to
  nothing. Motion that needs JavaScript would be invisible in exactly the environment
  this project targets.
- **The logo is a served asset, not an inline data URI.** A 21 KB JPEG costs about 29 KB
  of base64 on every welcome response, cannot be cached separately from the HTML, and
  would end up duplicated in tests. Serving it from `/assets/` keeps the page small and
  lets the CSP widen by one narrow step (`img-src 'self'`), which is a smaller risk than
  putting binary data in the document.
- **A 13-second stage needs a linear bar and a skip.** The requested wait is much longer
  than a normal hand-off, so an aggressive ease-out would race the bar to 90% and then
  appear stuck. Linear progress plus **Continue now** keeps the screen honest and
  escapable.
- **The add-row control belongs at the end of the list it grows.** With the **+** beside
  the heading, the new row appeared off-screen; the control and its counter now sit in a
  dashed bar under the rows, so the button is where the eye already is when the list
  ends.
- **"Seamless" without script means the draft round-trip, not a client-side insert.**
  The **+** submits the whole form with `formnovalidate`; the server re-renders with one
  more row and the same typed values. The `formaction` fragment names an end-of-list
  anchor, so the browser's own fragment scroll does the rest. No validation runs and
  nothing is stored on this path.
- **The landing is instant; only the new row moves.** The row is rendered at its final
  position with `html { scroll-behavior: auto; }` overriding the theme and
  `scroll-margin-top: 200px` placing the new row and the **+** bar in view the moment the
  response paints. In that already-final layout the fresh row alone plays a 0.26 s
  `row-pop` (fade plus a 4 px lift and 3% scale), so the motion happens where the student
  is already looking instead of dragging the whole page. Existing rows stay still and the
  reduced-motion query disables the pop. Smooth scrolling stays on the static report,
  where it is only ever used for in-page links.

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

17. **Plain amounts were rejected as invalid.** The parser required a `KES` prefix, so a
    browser test that typed `6000` failed validation even though the form copy said
    `18,000` was fine.
    *Cause:* the regex used `(?:kes|ksh)\s*` instead of an optional prefix.
    *Fix:* make the prefix optional and keep the anchored number/commas/decimal pattern.
    *Lesson:* test the exact examples printed in the UI help text.

18. **The over-plan insight read "1 categories are".** The plural wording was hard-coded
    and the first real plan had exactly one over-plan category.
    *Fix:* choose "category is" or "categories are" from the count and assert the
    sentence in the web test.
    *Lesson:* counts of zero, one and many all need their own wording.

19. **The 405 page title broke the read-only contract.** A generic "does not accept that
    request" title replaced "Read-only dashboard" and failed an existing test.
    *Fix:* keep the established title and put the explanation in the body.
    *Lesson:* error-page copy is part of the public contract; update tests deliberately,
    not incidentally.

20. **The maximum row state still invited another row.** At 24 categories the button was
    correctly replaced by a limit note, but the help text above still said to use it.
    *Fix:* remove the inline instruction and let the control (or the limit note) carry the
    message; assert both states in the web test.
    *Lesson:* every limited control needs copy for the available and exhausted states.

21. **The category shares appeared to add up to 100.1%.** Seven equal categories each
    showed 14.3%, so the visible column totalled 100.1% even though every underlying
    fraction was correct.
    *Cause:* each share was rounded independently for display, so the rounding drift was
    never redistributed.
    *Fix:* add `display_share_pcts` in `components.py`. It uses the largest-remainder
    method at the displayed precision, sends the spare tenths to the largest remainders,
    and feeds the planner category table, bucket table and receipt, plus the dashboard
    breakdown and report category table. The copy now names each denominator, and tests
    pin the seven-equal-parts case and a 100.0% total in the dashboard and report.
    *Lesson:* rounding is a presentation decision. A column that claims to be parts of one
    whole must add up to that whole.

22. **The dark theme could have made print output invisible.** Panels and text moved to a
    dark palette, but the print block still assumed dark text on white surfaces.
    *Fix:* rewrite the print rules to set panel, table and receipt surfaces to white and
    all inherited text to near-black, then verify with Playwright's print media emulation.
    *Lesson:* a theme is not finished until the reduced-motion and print variants are
    checked, not just the default screen.

23. **The session-expiry test invalidated every other test in the class.** The first draft
    expired all sessions to prove the check worked, which also expired the shared cookie
    that the already-signed-in planner and upload tests relied on.
    *Fix:* create a separate account for the expiry case and expire only that account's
    sessions; the shared cookie stays valid.
    *Lesson:* a test that mutates shared setup state must either isolate the state or run
    last by design, not by luck.

24. **The new auth feature contradicted the page copy.** The planner still said "no login
    is involved", the upload page still said "There is no login, so keep the server on
    loopback", and the footer claimed no credential field existed — all written before
    accounts existed. The tests passed because they asserted structure, not those sentences.
    *Fix:* update every copy block and recapture the screenshots; add the missing
    account description to the README limitations instead of leaving a false promise.
    *Lesson:* a feature is not shipped until the prose around it stops describing the old
    product. Grep for the old claim, not just for the new feature.

25. **The auth pages floated at the top of tall screens.** Content was correct but a tall
    desktop viewport left a large empty band below the card, which made the page look
    broken. *Fix:* make `.auth-shell` a flex column with `min-height: calc(100vh - 102px)`
    and `justify-content: center`, then verify at 1440 px and 390 px. *Lesson:* vertical
    composition needs a viewport rule, not just sensible margins.

26. **The welcome screenshot hung for 30 seconds.** Playwright waited for the page to
    settle while the 2.6-second `meta refresh` navigated away mid-capture and the
    background animations never stopped. *Fix:* read the heading, refresh content and
    script count first, screenshot with `animations: 'disabled'` and a short timeout, and
    verify the redirect in a separate run that simply waits for `/plan`. *Lesson:* a page
    that navigates itself needs a capture strategy that expects the departure.

27. **Removing the refresh tag after load did not cancel it.** `page.evaluate` stripped
    the `<meta>` element, yet the browser still navigated, so a later `goto('/plan')` was
    interrupted by "another navigation". *Fix:* stop trying to suppress the redirect and
    instead sequence the reads before the screenshot, then confirm the landing URL with
    `waitForURL`. *Lesson:* undoing markup does not undo a timer the browser already
    scheduled.

28. **Hover checks looked broken right after navigation.** `getComputedStyle` reported an
    identity transform on sign-out and add-row buttons until a mouse move was forced,
    even though the CSSOM listed `button:not(.button):hover`. Injecting the same selector
    made the transform appear, proving the rule was fine. *Fix:* verify the rule in the
    cascade and the primary button's `matrix(1,0,0,1,0,-2)`, and treat the first
    post-navigation sample as stale. *Lesson:* hover state is input-driven; an automated
    cursor can be in the right place before the browser has recalculated for it.

29. **The logo route answered 500 on the first request.** The cache variable and the
    loader function were both named `_logo_bytes`, so `def _logo_bytes()` rebound the
    global to the function; the `is None` guard never fired and the handler passed a
    function to `len()`. *Fix:* rename the cache to `_LOGO_CACHE`, keeping the function
    name. *Lesson:* in Python, a module-level function definition is an assignment to the
    name — it can silently overwrite state declared just above it.

30. **The first Plan It screenshot showed empty rings.** The capture used
    `animations: 'disabled'`, which fast-forwards finite CSS animations; the logo tile's
    `welcome-pop` entrance is opacity-zero at its first keyframe and carries
    `fill-mode: both`, so the frozen frame omitted the image even though it was loaded.
    *Fix:* wait 4.5 seconds and capture the live page, then verify the tile is 132 × 132
    with opacity 1. *Lesson:* animation-disabled screenshots can display a state a user
    never sees; when the content is inside an entrance animation, capture after it, not
    by freezing it.

31. **The 13-second bar looked finished after 5 seconds.** The fill reused the 2.2-second
    cubic-bezier from the previous screen, so it reached roughly 75% almost immediately
    and then sat still. *Fix:* switch the fill to `linear` for the full 12.7 seconds.
    *Lesson:* easing designed for a short transition is misleading when stretched across
    a countdown.

32. **A negative "test" of the new-row class failed on the stylesheet.** The initial-render
    test asserted `assertNotIn("plan-row-new", page)`, but the page's inline `<style>`
    contains the `.plan-row-new` selector, so the CSS string tripped the check while the
    markup was correct. *Fix:* assert against the markup class attribute instead
    (`class="plan-row cat-cols plan-row-new"`). *Lesson:* a rendered page is HTML plus
    CSS plus text; negative assertions must name the surface they mean.

33. **The new row landed just above the viewport.** The `#categories-end` anchor sat right
    after the rows and aligned the anchor top to the viewport top, pushing the fresh row
    off-screen by a few pixels. A guess at a negative `scroll-margin-top` then overshot on
    a short page and clamped at the maximum scroll, hiding the row entirely. A positive
    120 px margin then worked on desktop but put the taller, stacked phone row 46 px above
    the fold. *Fix:* `scroll-margin-top: 200px`, measured live to leave the new row at
    about 155 px with the **+** bar just below on desktop, and the row at about 34 px on a
    390 px phone. *Lesson:* scroll offsets respond to page length, content below the
    target and row height at each breakpoint; verify the landing position at more than one
    width, not just that scrolling happened.

34. **Fragment scrolling appeared not to work, twice for the wrong reason.** The first
    probe sampled `window.scrollY` a few hundred milliseconds after load and saw zero,
    because `scroll-behavior: smooth` turns the fragment jump into an animation that
    starts late and takes about a second. The same probe also expected `autofocus` to
    focus the new field, but Chromium does not process `autofocus` on a navigation caused
    by a form submission. *Fix:* wait for the scroll to settle before measuring, assert the
    rendered `autofocus` attribute rather than active focus, and document the browser
    behaviour. *Lesson:* a timing artifact can look exactly like a missing feature; also,
    `autofocus` is a best-effort hint across navigation types.

35. **The user called the add-row reload a glitch.** Pressing **+** repainted at the top
    of the page, glided down for about a second under the theme's global
    `scroll-behavior: smooth`, and then played a 0.5-second `row-in` slide on the new row:
    three separate motions for what should be one instant result. *Fix:* delete the
    `row-in` animation entirely and override the theme with
    `html { scroll-behavior: auto; }` in the served-page CSS, keeping only
    `scroll-margin-top` to control where the instant jump lands. The live measurement is
    now about 250 ms from click to a visible row at 155 px, with `animation-name: none`.
    *Lesson:* a reload is read as "the app jumped and then did something"; every extra
    transition layered on top of it reads as malfunction, however smooth it looks on its
    own. Verify perceived timing end to end, not each effect in isolation.

36. **The replacement pop appeared not to run in headless Chromium.** With `row-pop`
    restored on the new row, the computed style reported `animation-name: row-pop`,
    `playState: running`, but `startTime: null` and `currentTime: 0` for up to two
    seconds, while the row held the from-frame because of `fill-mode: both`. Probing
    showed animations on elements that are laid out but offscreen at parse time stay
    pending until their first paint; visible elements, empty elements and clipped
    elements start immediately. *Fix:* treat pending as not-yet-started and poll the
    computed style until opacity is 1 and the transform is the identity matrix, rather
    than asserting an exact start time or the string `none` (a settled transform computes
    as `matrix(1, 0, 0, 1, 0, 0)`). *Lesson:* a headless browser can legitimately defer
    an animation the user would see at once; assert the end state and the declared
    animation, and never infer "no animation" from a single early sample.

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
formula injection; user-defined taxonomies and case-insensitive canonical keys; POST/
redirect/GET; unguessable resource ids as capability links; JSON persistence with a
strict reload path; grouped SVG charts; no-JavaScript draft round-trips for dynamic form
rows; largest-remainder rounding for displayed shares; CSS-only background and receipt
animation with reduced-motion and print fallbacks; password hashing with scrypt and
random salts; constant-time comparison; hashed session tokens; HttpOnly and SameSite
cookies; session expiry and logout; same-origin checks on writes; safe redirect
allow-lists against open redirects; generic authentication errors; timing equalisation
with a dummy hash; in-memory rate limiting with `Retry-After`; `meta refresh` as a
no-script redirect; SVG stroke-dash drawing and CSS keyframe staging behind a
`prefers-reduced-motion` branch; pseudo-element sheen and gradient-position transitions
on buttons; same-origin static assets with a narrow `img-src` allowance; package data for
shipped media; linear progress pacing over a long staged wait; `formaction` fragments and
`formnovalidate` draft round-trips for add-row controls; `scroll-margin-top` tuning for
fragment landings under smooth scrolling; entrance keyframes for a server-rendered row;
and the difference between "valid" and "unusual".

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
8. Let the planner import one student's transactions from the warehouse, map them to the
   student's own category names, and compare the imported actuals with the plan.
9. Add a month field to the worksheet and compare two analyses for the same student
   without storing either one.
10. Add an optional download of the current analysis as a standalone HTML file, generated
    on demand rather than persisted.

## Open questions

- Should quarantined rows have a resolution workflow (status + reviewer + note)?
- Should corrected records be linked to the run that superseded them?
- Is a calendar-week grain enough, or is a real date dimension needed for reporting?
- Should the dashboard remember a preferred date range, and if so, where — URL, cookie
  or warehouse table?
- If this ever held real data, what authentication and access logging would be required
  before any route left loopback?
- Should the planner offer an explicit "download this analysis" action, or is the browser
  print/save flow enough for a worksheet that deliberately stores nothing?
- Should the planner support more than one currency, or is KES-only the honest scope for
  this dataset?
