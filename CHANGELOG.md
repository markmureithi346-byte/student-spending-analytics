# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[semantic versioning](https://semver.org/spec/v2.0.0.html).

## [2.6.2] - 2026-11-04

Gives the newly added planner row a visible entrance: it now pops in with a short
fade-and-lift while the page still lands instantly at the end of the list.

### Added

- `.plan-row-new` carries a 0.26 s `row-pop` keyframe (opacity 0 to 1, 4 px lift and
  3% scale) on the row rendered by an `add_category` or `add_spending` round-trip. Only
  the freshly added row animates; existing rows keep `animation: none`. The reduced-motion
  media query disables it like every other transition.

### Changed

- The animation never delays the landing: `scroll-behavior: auto` and
  `scroll-margin-top: 200px` still put the new row and the **+** bar in view on first
  paint, so the pop plays where the student is already looking.

Verified at 1280 px: one **+** press returns in under 700 ms, the new row sits 159 px
from the top with `animation-name: row-pop` at 0.26 s, row 1 stays `none`, the draft is
preserved, the row settles at opacity 1, and a reduced-motion context reports `none`.
The suite is still 158 tests.

## [2.6.1] - 2026-11-04

Removes the glitch when pressing **+** on the planner: the added row now appears
immediately, with no entrance animation and no smooth-scroll glide.

### Fixed

- Dropped the `row-in` slide animation (and its reduced-motion entry) from newly added
  category and spending rows; the row is rendered in place when the response arrives.
- Overrode the theme's `scroll-behavior: smooth` on the served pages with
  `html { scroll-behavior: auto; }`, so a form-submission landing on `#categories-end`
  or `#spending-end` jumps straight to the list end instead of painting at the top and
  then gliding for about a second. `scroll-margin-top` still keeps the new row and the
  **+** bar in view.

Measured live at 1280 px: a **+** press returns and shows the new row 155 px from the top
in about 250 ms, with `animation-name: none` and `scroll-behavior: auto`. The suite is
still 158 tests, and the rendered-page test now also pins the `scroll-behavior` override.

## [2.6.0] - 2026-11-04

Moves the add-row **+** controls under the Categories and Spending lists and makes adding
a row feel continuous, still with no JavaScript.

### Changed

- The **+** control and its row counter now sit in a dashed-top bar under each list
  instead of beside the section heading, so new rows appear where you are reading.
- Adding a row keeps the whole draft: the **+** button posts the form with
  `formnovalidate` to `/plan#categories-end` (or `#spending-end`), and the server
  re-renders the form with one more row without validating or saving anything.
- The newly added row gets a short `row-in` slide animation and an `autofocus` on its
  first field, and `scroll-margin-top` on the end anchors lands the page with the new row
  and the **+** bar both in view. Reduced-motion users get the same row with no animation.
- The form lead copies now point to the **+** under the list, and the initial form render
  carries neither the new-row animation nor an autofocus.

Release version is now `2.6.0`; the suite is still 158 tests, with the add-row tests now
covering the bottom placement, end anchors, preserved draft, new-row animation and
autofocus.

## [2.5.0] - 2026-10-30

Rebrands the loading screen as **Plan It**, drops in the supplied logo, and stretches the
staged wait to 13 seconds.

### Added

- `src/student_spending/assets/plan-it-logo.jpg` (21 KB), served publicly at
  `/assets/plan-it-logo.jpg` with `Cache-Control: public, max-age=86400` and packaged with
  the distribution through `tool.setuptools.package-data`.
- The welcome screen now carries the Plan It wordmark, the slogan *Let's save money by
  planning*, and the logo in a rounded tile with counter-rotating rings and a floating
  animation. The signed-in name and destination line sit underneath.
- The welcome test now also covers the logo route: `200`, `image/jpeg`, the cache header,
  and bytes matching the packaged file.

### Changed

- The countdown is now 13 seconds: the meta refresh reads `13;url=…` and the progress bar
  runs `12.7s` on a linear curve, so it matches the actual wait instead of finishing early.
- The signed-in heading is smaller than the brand wordmark, and the eyebrow is centred, so
  the logo, brand, slogan and welcome name read as one stack.
- CSP now permits `img-src 'self' data:` so the same-origin logo can load; everything else
  remains locked down, and no script is introduced.

Release version is now `2.5.0`; the suite is still 158 tests.

## [2.4.0] - 2026-10-30

Adds a loading screen between signing in and the destination, and gives every button a
consistent hover, press and sheen animation — all CSS, no JavaScript.

### Added

- `/welcome` renders after a successful sign-in or sign-up and offers a small confirmation
  stage: an animated tick, two counter-rotating rings, a halo, a progress bar and a status
  line naming the destination. It redirects after 2.6 seconds with
  `<meta http-equiv="refresh">`, which the strict CSP allows, and a **Continue now**
  button skips the wait. Desktop and phone screenshots are in the README.
- The page is gated like the tools: an anonymous visit redirects to `/login` with the safe
  `next` path, and an unsafe `next` falls back to `/plan`.

### Changed

- Sign-in and sign-up now redirect to `/welcome?next=…` instead of straight to the
  destination. The session cookie is still set on the original `303`.
- Every button animates: primary and ghost links lift, press, and sweep a light sheen on
  hover; the primary button also shifts its three-stop gradient; sign-out, add-row **+**
  (which rotates a quarter turn) and the file picker join in. Global `button` rules cover
  controls added later.
- The whole block collapses under `prefers-reduced-motion: reduce`: no transitions or
  keyframes, the sheen hidden, the progress bar complete and the tick drawn.

### Fixed

- Nothing user-facing; the hover checks that looked wrong after navigation turned out to be
  a browser hover-timing artifact, and the rules were confirmed present in the cascade.

### Security

- The welcome screen is behind the same session check as `/plan` and `/upload`, stores
  nothing, and the refresh target comes from the existing safe-path allow-list.

Release version is now `2.4.0`; the suite is 158 tests.

## [2.3.0] - 2026-10-29

Adds local demo accounts, so the money planner and the CSV upload sit behind a sign-in
without any external identity service or real credentials.

### Added

- `/signup` creates a local demo account from a display name, a made-up email and a
  password, then signs the visitor in and returns them to the page they asked for.
- `/login` and `/logout`. Sessions last eight hours, are stored in `data/accounts.db`
  beside the warehouse, and are deleted on sign-out.
- An account bar on every page: **Demo mode · sample dashboard** with **Sign in** and
  **Create account** links when signed out, the display name and a **Sign out** button
  when signed in.
- `accounts.py`: scrypt password hashing (N=16384, r=8, p=1, random 16-byte salt),
  constant-time verification, SHA-256 session-token digests, expiry cleanup, and
  case-insensitive unique emails.
- Sign-in throttling: eight failures from one address within five minutes return `429`
  with `Retry-After: 300`; a successful sign-in clears the counter.
- Sign-in and sign-up screenshots at desktop and phone width, plus a README section
  describing the account model.

### Changed

- `/plan` and `/upload` now require a session. Anonymous GETs redirect to the sign-in
  page with a safe `next` path; anonymous form posts are refused. The sample dashboard,
  report, CSV export and sample files remain public.
- Same-origin checks now also cover the three account POST routes, and auth forms are
  size-limited to 16 KB.
- Sign-up errors preserve the display name and email but never re-render a password.
- `serve` prints the accounts database path and warns when it is bound beyond loopback,
  because demo accounts are not internet-grade.
- Planner, upload and footer copy no longer claims there is no login; the planner says
  the account only unlocks the form and that the plan itself is still not saved.

### Security

- Passwords are never stored or logged in plaintext, and login failures deliberately do
  not reveal whether the email or the password was wrong. Unknown emails are checked
  against a cached dummy hash so they do not answer faster than a wrong password.
- Session cookies are `HttpOnly` and `SameSite=Strict`; `next` redirects are restricted to
  `/`, `/plan` and `/upload` to avoid an open redirect.

Release version is now `2.3.0`; the suite is 157 tests.

## [2.2.0] - 2026-10-26

Brings the receipt forward as the first summary after the analysis and makes the
backdrop visibly alive.

### Changed

- The receipt now follows the analysis summary directly, is section 06, and is reachable
  through an **Open the receipt** button in the analysis and the **Receipt** section-nav
  link. Categories, entries and method move to 07–09.
- The backdrop now carries twelve drifting sparks, faster-moving orbs, a 38-second star
  drift and a 55-second rotating glow. All motion is still CSS-only and stops under
  `prefers-reduced-motion`.

Release version is now `2.2.0`; the suite is 138 tests.

## [2.1.0] - 2026-10-26

Adds a printable receipt summary, makes displayed shares add up exactly, and gives the
whole platform a living dark-purple surface.

### Added

- A **Receipt** section (`#analysis-receipt`) inside the analysis, itemising every
  category with recorded spending, each share, the planned total, the money available and
  the balance. The receipt is generated locally from the same analysis values, carries a
  stamp and decorative barcode, and prints or saves as PDF through the browser. Nothing is
  stored and there is no extra route or result link.
- A totals row in the category table, so the planned, spent, difference and 100.0% share
  columns can be checked at a glance.
- Component tests for the rounding helper and web tests for the receipt and percentage
  copy.

### Changed

- Displayed one-decimal shares in the planner, dashboard breakdown and report now use
  the largest-remainder method, so seven equal categories show six 14.3% shares and one
  14.2% instead of seven 14.3% shares totalling 100.1%. The bar widths use the same
  rounded values.
- Percentage copy now names its denominator: shares are of **recorded spending**, cards
  are of the **money available**, and the essential insight is of the **planned total**.
- Panels, cards, tables, forms, inputs, charts and banners are now dark-purple surfaces
  with light text; the page background gains a slow gradient drift, star field, rotating
  glow and an extra orb. The receipt has a glossy sheen.
- Reduced-motion and print behaviour were extended to the new effects: motion stops under
  `prefers-reduced-motion`, and print turns panels and the receipt white with dark text.

### Fixed

- The apparent percentage inaccuracy where rounded category shares could total more than
  100.0%.
- Stale README references to saved JSON plans and `data/plans/` that survived the 2.0.0
  persistence removal.

Release version is now `2.1.0`; the suite is 138 tests.

## [2.0.0] - 2026-10-26

Renders the money-plan analysis, totals and graphs directly below the form, so there is no
saved plan, no result link and no separate file to open.

### Changed

- **Run my analysis** now returns the planner page itself (HTTP 200) with the totals,
  category comparison, spending chart and method summary inserted beneath the form at
  `#analysis`. All charts are inline SVG generated on this machine.
- The submitted values stay in the form, so a student can adjust them and run the analysis
  again without re-entering anything. There is no redirect and no `Location` header.
- Removed saved-plan storage (`data/plans/`, plan IDs, `/plan?plan=…`, `/plan?edit=…`) and
  the separate result page. Old plan links now render a fresh, empty form.
- The analysis copy states plainly that it is generated in the page and is not saved as a
  separate link or file.
- Release version is now `2.0.0`; the suite is 128 tests.

## [1.4.4] - 2026-10-26

Starts both lists in the money plan with a single row, so the form stays short and grows
only as the student adds rows.

### Changed

- Categories and Spending now open with one row each instead of 12. The **+** buttons
  remain the gradual path up to 100 rows, and still preserve the whole draft without
  saving.
- Row counters now start at "1 of 100 category rows" and "1 of 100 spending rows"; the
  first click adds row 2, and later clicks keep appending one row at a time.
- Validation is unchanged: at least two named categories and one complete spending row
  are still required, so a student adds their second category with the same **+**.
- Release version is now `1.4.4`; the suite stays at 133 tests.

## [1.4.3] - 2026-10-26

Adds the same **+** control to Spending, so both lists in the money plan start compact and
grow on demand.

### Changed

- A **+** button beside the Spending heading adds one row per click, from 12 rows up to
  100. Like the category control, it re-renders the draft through the server, keeps every
  typed value and saves nothing until **Run my analysis**.
- Spending now starts with 12 rows instead of 24, matching Categories. Both limits are
  100, the row counters read "12 of 100 … rows", and each button becomes a maximum note
  at the limit.
- The form field cap rises from 600 to 800 so a plan with 100 categories and 100 spending
  rows parses, and the release version is now `1.4.3`. Two new tests bring the suite to
  133.

## [1.4.2] - 2026-10-26

Turns the add-row control into a compact **+** button beside the Categories heading and
raises the category limit from 24 to 100, so a student can build the category list their
budget actually needs.

### Changed

- The **+** button sits next to the Categories heading, with an accessible label and a
  tooltip. It adds one row per click, keeps every typed value, and still saves nothing
  until **Run my analysis** is selected.
- Category rows can grow from 12 to 100 (previously 24). The row counter now reads
  "12 of 100 category rows"; at the limit the button is replaced by a maximum note.
- The form field cap rises from 250 to 600 so a 100-category plan parses, and the release
  version is now `1.4.2`. One new test brings the suite to 131.

## [1.4.1] - 2026-10-26

Adds an **+ Add another category** control to the money-plan form. It works without
JavaScript, keeps every value already typed, and does not save a plan until **Run my
analysis** is selected.

### Added

- A server-backed add-row button beneath the category rows. Submitting it re-renders the
  form with one more row, preserving names, amounts, spending entries and the synthetic
  confirmation.
- Hidden row-count fields so added rows survive validation errors and normal submission.
- The category limit rises from 12 to 24 rows; the form still starts with 12 and shows
  how many of the 24 rows are visible. At the limit the button is replaced by a note.

### Changed

- Release version is now `1.4.1`; three new web tests bring the suite to 130.

### Fixed

- The category help text no longer promises an add control when the maximum row count
  has already been reached.

## [1.4.0] - 2026-10-26

Adds a per-student money planner. A student enters the money they have, names their own
categories, records planned and actual amounts, and receives a saved analysis with
planned-versus-actual charts and category shares. The planner is local, uses no
JavaScript and never asks for bank, card or payment credentials.

### Added

- `GET /plan` and `POST /plan`: a four-section form for a display name, money available,
  budgeting method and note, up to 12 user-named categories with optional planned
  amounts and an essential/flexible flag, and up to 24 spending rows with date,
  category, amount and note.
- `personal.py`: typed draft/plan/analysis models, amount parsing (commas, spaces, KES
  prefix and decimals), field-level validation, integer-cent analysis, and strict JSON
  storage under `data/plans/`.
- A bookmarkable result page at `/plan?plan=p-…` with summary cards, unallocated and
  overspending banners, plain-language insights, a ranked spending chart, a grouped
  planned-versus-actual chart, a category table with plan status, an essential/flexible
  split, the spending entries and the chosen method.
- **Edit as a copy** prefills the form from a saved plan and saves a new plan instead of
  overwriting the original.
- `grouped_bar_chart` in `components.py`, shared chart tooltips and shortened chart
  labels for long user-defined category names.
- 32 money-plan tests (127 total): amount parsing, validation, analysis arithmetic,
  JSON round-trips and tamper rejection, the web flow, edit-as-copy, request guards and
  HTML escaping.
- Desktop form, desktop result and phone-width screenshots in `docs/images/`.

### Changed

- The dashboard and upload pages link to the planner; the dashboard's primary call to
  action is now **Plan my money**.
- Saved plans are stored as unguessable `p-<16 char>` JSON files and are not listed or
  indexed; the result link is the only way back. `data/plans/` is git-ignored.
- The server now identifies itself as version 1.4. The footer states that `POST /upload`
  and `POST /plan` are the only write paths.
- Release version is now `1.4.0`.

### Fixed

- The amount parser required a `KES` prefix for plain numbers such as `6000` or
  `18,000`; the prefix is now optional.
- The over-plan insight now reads "1 category is over plan" instead of
  "1 categories are over plan".

## [1.3.0] - 2026-10-26

Simplifies the upload workspace to a single transactions CSV. Profiles and budgets are
no longer requested by the browser form.

### Added

- `extract.derive_profiles`, which builds the student dimension from the distinct
  `student_id` values in an upload.
- A report state for analyses without budget data, stating that no plan was provided
  instead of showing a zero-line comparison.
- Pipeline support for `profiles_csv=None` and `budgets_csv=None`; the CLI still accepts
  explicit files and keeps its 12 quality checks.

### Changed

- `/upload` now accepts one transactions CSV, one sample link and one synthetic-data
  confirmation. Profile and budget inputs and sample links are gone.
- Uploads run 11 quality checks; the budget-presence check is only recorded when budget
  rows exist.
- Derived profiles store `study_year = 0` and income `0` as "not supplied"; the schema
  accepts 0 for this case.
- Upload workspace metadata and files now contain only `transactions.csv`.
- Release version is now `1.3.0`.

## [1.2.0] - 2026-10-26

Turns the dashboard into an upload-and-analyze platform. A synthetic three-CSV bundle
can now be validated, loaded into its own warehouse and explored without touching the
committed sample warehouse.

### Added

- `POST /upload` and the `/upload` page: transactions, profiles and budgets CSVs, an
  optional 80-character analysis name, downloadable sample files and a mandatory
  synthetic-data confirmation.
- `platform.py`, which validates multipart input, writes canonical copies, runs the
  existing pipeline under a process-wide lock and publishes an isolated workspace with its
  own inputs, SQLite database, HTML report and metadata.
- A `303` redirect to `/?analysis=<analysis_id>`; the id is preserved by filters,
  pagination, reset links, CSV export and the report, so every uploaded view is
  bookmarkable.
- A recent-analyses list with status, accepted rows, report link and dataset name.
- A quality-alert banner for analyses whose pipeline exited with code `1`; partial
  workspaces are removed after unrecoverable pipeline errors and the upload page
  returns `422` with the reason.
- Upload limits: 2 MB per file, 6 MB total, 50,000 data rows per file, 12 form parts,
  UTF-8 `.csv` files with the exact required headers and at least one data row.
- Origin and `Sec-Fetch-Site` checks, fixed on-disk filenames, strict analysis-id
  validation and analysis-aware routing for the sample-file download endpoints.
- Eleven upload-platform tests (92 total) and desktop/phone screenshots of the upload
  page and an uploaded analysis.

### Changed

- `serve` now presents both the dashboard and the upload workspace; its CLI help text
  describes both. Pipeline options and exit codes are unchanged.
- The HTTP `Referrer-Policy` is now `same-origin` instead of `no-referrer`, so browsers
  send a verifiable `Origin` header on uploads without leaking URLs cross-origin.
- Release version is now `1.2.0`.
- README, learning log and test counts document the platform, its limits and its
  security model.

### Fixed

- Real browser uploads failed with `403`: under `Referrer-Policy: no-referrer`,
  Chromium sends `Origin: null`, which the same-origin guard correctly rejected. The
  policy change makes legitimate form posts pass while explicit null and cross-site
  origins remain blocked.
- Uploaded files and analysis workspaces are cleaned up when the pipeline cannot
  produce a usable warehouse, instead of leaving partial directories behind.

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
