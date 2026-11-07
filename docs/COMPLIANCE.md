# Compliance checklist (Kenya)

Status: **draft for legal review.** This document is an operator checklist, not legal
advice. A qualified Kenyan lawyer must review the privacy notice, terms and this
checklist before any public launch. Every value that depends on the operator is a
`[BRACKETED PLACEHOLDER]` in `src/student_spending/legal.py` and in this file.

## 1. Scope and data inventory

Plan It is a local learning tool. The shipped version runs on the operator's own computer
and does not send account or analysis data to a remote service.

| Data | Where it lives | Why it is held | Retention |
|---|---|---|---|
| Display name, email, password hash (scrypt), recovery-code hash | `data/accounts.db` | Create and secure the demo account | Until the account is deleted |
| Consent timestamp and policy version | `data/accounts.db` | Evidence of consent for the published policy version | Until the account is deleted |
| Session token digest, creation and expiry | `data/accounts.db` | Keep the signed-in session | Eight hours, or sign-out |
| Uploaded synthetic CSV, metadata, isolated SQLite warehouse, report | `data/uploads/`, `warehouse/uploads/`, `reports/uploads/` | Provide the analysis the user asked for | [RETENTION PERIOD, FOR EXAMPLE 30 DAYS], then `student-spending prune-uploads --days N --apply` |
| Pipeline and server logs | `logs/` | Diagnose errors and abuse | [LOG RETENTION PERIOD, FOR EXAMPLE 14 DAYS] |

Not collected and must never be entered: card numbers, bank account numbers,
mobile-money PINs, national ID numbers, payment credentials, real student financial
records or another person's personal data. There is no advertising, analytics or
third-party tracking script, and the only cookie is the session cookie.

The planner keeps no plan: its figures exist only in the response to the form, and the
optional CSV download is generated in that response. Plans therefore create no stored
record and no retention obligation.

## 2. Lawful basis and consent

- Account creation, planner use and uploads are performed because the user asked for the
  service and consented to the draft policy. The sign-up form has an **unticked** privacy
  checkbox; the timestamp and `POLICY_VERSION` are stored with the account.
- Security controls (rate limiting, same-origin checks, abuse investigation) rest on the
  operator's legitimate interest, balanced against the user's rights.
- The account page records consent for a new policy version and explains that withdrawing
  consent for account processing means deleting the account. Deletion removes every
  session and every analysis owned by the account; a JSON export is available first.
- The public sample dashboard and report need no account, so refusing consent does not
  block the whole product.

## 3. Data subject rights

| Right | How it is served |
|---|---|
| Access / portability | `/account` → **Export account data** returns JSON after password re-entry. It contains the account record, consent and upload metadata, and never a password or recovery hash. |
| Correction | Display name and email are fixed for the demo; the operator must correct them manually on request at [PRIVACY EMAIL]. |
| Erasure | `/account` → **Delete my account** after password re-entry removes the account, sessions and owned analyses. |
| Restriction / objection | Stop using the account; deletion is the available withdrawal path. |
| Complaint | Office of the Data Protection Commissioner: [ODPC CONTACT DETAILS]. |

The planner does not store plans, so there is no plan history to export or erase.

## 4. Security controls (verified by tests)

- scrypt password hashing with a random salt; passwords are 10–128 characters.
- Session tokens and recovery codes stored only as SHA-256 digests; cookies are
  `HttpOnly`, `SameSite=Strict`, eight-hour expiry, and `Secure` plus HSTS under
  `serve --secure-cookies` behind TLS.
- Eight failed attempts per address per five minutes return `429` with `Retry-After`.
- Generic sign-in, reset and account-action failures; a dummy hash equalises unknown
  emails.
- Same-origin `Origin` / `Sec-Fetch-Site` checks on every state-changing form, plus
  `SameSite=Strict`. There is no separate CSRF token; the two header checks and the
  cookie policy are the documented mitigation.
- Every analysis is scoped to the account that created it on the dashboard, report, CSV
  export, history and delete page.
- Read-only SQLite connections for analytics; parameterised SQL; escaped HTML.
- Security headers: CSP (`default-src 'none'`), `X-Content-Type-Options`,
  `Referrer-Policy`, `X-Frame-Options: DENY`, `Permissions-Policy`,
  `Cross-Origin-Opener-Policy` and `Cross-Origin-Resource-Policy`.
- No secrets in the repository; `.env.example` documents that no environment variable is
  required. `THIRD_PARTY_LICENSES.md` records the dependency audit.

## 5. Breach response (72 hours)

1. **Contain**: stop the server, revoke exposed sessions by deleting `data/accounts.db`
   sessions or the whole demo account store, and move the server back to loopback.
2. **Assess**: identify which records and which people were affected, and whether the
   breach creates a risk to their rights. Preserve `logs/` and the analysis directories as
   evidence; do not edit them.
3. **Notify**: if a risk exists, notify the Office of the Data Protection Commissioner
   without undue delay and within **72 hours** of becoming aware, and notify affected
   people without undue delay. Use [ODPC CONTACT DETAILS] and [PRIVACY EMAIL].
4. **Record**: write down what happened, when it was discovered, the data and people
   affected, the containment steps and the notifications sent.
5. **Remediate**: patch the cause, rotate any exposed secret, re-run the test suite and
   update this checklist.

Because the demo stores no real financial records, the most likely incident is unauthorised
access to demo identities or synthetic uploads. Treat any exposure of a real value entered
by mistake as a personal-data breach.

## 6. ODPC registration and operator details

- Data controller: [FULL LEGAL NAME OF CONTROLLER], [POSTAL ADDRESS], Kenya.
- Privacy contact: [PRIVACY EMAIL].
- ODPC registration: [ODPC REGISTRATION NUMBER OR "NOT YET REGISTERED"].
- ODPC contact details: [ODPC CONTACT DETAILS].
- Hosting, if any: [HOSTING PROVIDER AND LOCATION]. International transfers:
  [INTERNATIONAL TRANSFER SAFEGUARDS OR "NONE"].
- Backups, if any: [BACKUP RETENTION PERIOD OR "NONE"].

Registration and annual fees depend on whether the operator is a data controller or
processor and on the volume of personal data. Confirm the current ODPC guidance and
whether registration is required before launch.

## 7. Data protection impact assessment (screening)

A full DPIA is not included. Screening questions the operator must answer:

1. Does the deployment process real financial data, or only synthetic data? (The shipped
   version is synthetic-only.)
2. Is the service reachable beyond loopback? If yes, TLS, authentication hardening,
   hosting terms and an international-transfer assessment are required first.
3. Are people under 18 expected? The notice says 18+, or use with a parent or guardian.
   [AGE-ASSURANCE APPROACH].
4. Is any data used for profiling or automated decisions with legal effect? No; the coach
   is rule-based, educational and produces no decision about a person.
5. Is sensitive data (health, biometrics, ethnicity, religion, political opinion) processed?
   No, and the terms forbid entering it.
6. Could a breach cause significant harm? Only if real data is entered by mistake; the
   controls above and the synthetic-data warning reduce that risk.

If any answer changes, complete a full DPIA before continuing.

## 8. Licensed financial services

Plan It is **not** licensed by the Central Bank of Kenya, the Capital Markets Authority or
any other financial regulator. It does not connect to a bank, card, mobile-money wallet or
payment account, and it does not execute, receive, hold or move money. It compares numbers
the user types or uploads. The exact disclaimer appears on the dashboard, planner, upload
page, legal pages and account page:

> Plan It is a tracking tool. It does not provide financial, investment, tax or legal
> advice and does not hold or move your money.

Do not add lending, payments, savings products, investment execution, credit scoring or
regulated advice without a separate legal and licensing review.

## 9. Trademarks and licensing

- M-Pesa is a registered trademark of Safaricom PLC. The name appears only as an optional
  payment-method label in synthetic sample data; the full non-affiliation notice is in
  `src/student_spending/legal.py` and on `/terms`.
- The source is MIT licensed (`LICENSE`). The Plan It name and logo are
  [TRADEMARK STATUS AND OWNER].
- Third-party components: `THIRD_PARTY_LICENSES.md`.

## 10. Pre-launch checklist

- [ ] Replace every `[BRACKETED PLACEHOLDER]` in `legal.py` and this file.
- [ ] Set the effective date and confirm the policy version string.
- [ ] Obtain Kenyan legal review of the privacy notice and terms.
- [ ] Decide whether ODPC registration is required; record the number.
- [ ] Publish retention periods and run `prune-uploads` on that schedule.
- [ ] If reachable beyond loopback, terminate TLS and run with `--secure-cookies`.
- [ ] Confirm no real financial data is present in `data/`, `warehouse/`, `reports/` or
      `logs/`.
- [ ] Re-run `python run_tests.py`, `python -m pip check` and `python -m compileall -q src`.
- [ ] Keep this checklist and the breach log with the operated deployment.
