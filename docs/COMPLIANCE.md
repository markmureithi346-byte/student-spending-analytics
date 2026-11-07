# Compliance checklist (Kenya)

Status: **draft for legal review.** This document is an operator checklist, not legal
advice. A qualified Kenyan lawyer must review the privacy notice, terms and this
checklist before any public launch. Every value that depends on the operator is read at
startup from `PLANIT_*` environment variables and documented in `.env.example`; the legal
pages keep a visible Draft banner until `PLANIT_LEGAL_REVIEWED=1`.

## 1. Scope and data inventory

Plan It can run locally for learning, or as a single-host public service behind a TLS
proxy. In either case the committed sample warehouse is synthetic; a signed-in user may
upload their own transactions CSV, and that analysis is real personal data when it
describes a person.

| Data | Where it lives | Why it is held | Retention |
|---|---|---|---|
| Display name, email, password hash (scrypt), recovery-code hash | `PLANIT_ACCOUNTS_DB` (default `data/accounts.db`) | Create and secure the account | Until the account is deleted |
| Consent timestamp and policy version | `PLANIT_ACCOUNTS_DB` | Evidence of consent for the published policy version | Until the account is deleted |
| Session token digest, CSRF token, creation and expiry | `PLANIT_ACCOUNTS_DB` | Keep the signed-in session and bind forms to it | Eight hours, or sign-out |
| Uploaded CSV, metadata, isolated SQLite warehouse, report | `PLANIT_UPLOAD_DATA_DIR`, `PLANIT_UPLOAD_WAREHOUSE_DIR`, `PLANIT_UPLOAD_REPORT_DIR` | Provide the analysis the user asked for | [RETENTION PERIOD, FOR EXAMPLE 30 DAYS], then `student-spending prune-uploads --days N --apply` |
| Pipeline and server logs, proxy access logs | `PLANIT_LOG_DIR` and the proxy log path | Diagnose errors, abuse and security incidents | [LOG RETENTION PERIOD, FOR EXAMPLE 14 DAYS] |
| Backups of the above | Operator-chosen backup destination | Recover from loss or corruption | [BACKUP RETENTION PERIOD OR "NONE"] |

The committed sample dataset is synthetic. The operator must still assume that any upload
workspace may contain real data, because the service no longer asks users to confirm the
file is fake.

Not collected and must never be requested: card numbers, bank account numbers,
mobile-money PINs, national ID numbers, payment credentials or another person's personal
data without a lawful basis. There is no advertising, analytics or third-party tracking
script, and the only cookie is the session cookie.

The planner keeps no plan: its figures exist only in the response to the form, and the
optional CSV download is generated in that response. Plans therefore create no stored
record and no retention obligation.

## 2. Lawful basis and consent

- Account creation, planner use and uploads are performed because the user asked for the
  service and consented to the current policy. The sign-up form has an **unticked** privacy
  checkbox; the timestamp and `POLICY_VERSION` are stored with the account.
- Uploading a CSV requires a separate confirmation that the user has the right to process
  the file. The planner requires a confirmation that it is a planning tool, not financial
  advice. Neither confirmation is a lawful basis by itself; the operator must document
  one for the service and the user remains responsible for the data they upload.
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
| Correction | Display name and email are fixed for a local account; the operator must correct them manually on request at [PRIVACY EMAIL]. |
| Erasure | `/account` → **Delete my account** after password re-entry removes the account, sessions and owned analyses from the active store. Backups age out under the published backup retention period; storage-level residual copies follow the operator's media-sanitisation policy. |
| Restriction / objection | Stop using the account; deletion is the available withdrawal path. |
| Complaint | Office of the Data Protection Commissioner: [ODPC CONTACT DETAILS]. |

The planner does not store plans, so there is no plan history to export or erase.

## 4. Security controls (verified by tests)

- scrypt password hashing with a random salt; passwords are 10–128 characters.
- Session tokens and recovery codes stored only as SHA-256 digests; cookies are
  `HttpOnly`, `SameSite=Strict`, eight-hour expiry, and `Secure` plus HSTS in production.
  Production refuses to start with `PLANIT_SECURE_COOKIES=0`.
- Eight failed attempts per address per five minutes return `429` with `Retry-After`. When
  `PLANIT_TRUST_PROXY=1`, the proxy-forwarded client address is used, so each user is
  limited separately; the proxy must overwrite the header.
- Generic sign-in, reset and account-action failures; a dummy hash equalises unknown
  emails.
- Same-origin `Origin` / `Sec-Fetch-Site` checks on every state-changing form, plus a
  per-session CSRF token on every authenticated form and `SameSite=Strict`. Missing or
  wrong tokens return `403`.
- Every analysis is scoped to the account that created it on the dashboard, report, CSV
  export, history and delete page.
- Read-only SQLite connections for analytics; parameterised SQL; escaped HTML.
- Uploaded CSVs, metadata, upload warehouses and reports are written owner-only (`0600`
  files, `0700` directories) where the platform supports it. The systemd unit adds
  `UMask=0077`.
- Security headers: CSP (`default-src 'none'`), `X-Content-Type-Options`,
  `Referrer-Policy`, `X-Frame-Options: DENY`, `Permissions-Policy`,
  `Cross-Origin-Opener-Policy` and `Cross-Origin-Resource-Policy`.
- `/healthz` exposes only a healthy/degraded state, version and two booleans; it does not
  return personal data.
- The reverse-proxy examples cap request bodies, bind the app to loopback, set HSTS
  (nginx) and overwrite `X-Forwarded-For`.
- No secrets are in the repository; `THIRD_PARTY_LICENSES.md` records the dependency
  audit. The environment file contains operator details, not API keys, but must still be
  readable only by the service account and administrators.

## 5. Breach response (72 hours)

1. **Contain**: stop the service or remove it from the proxy, revoke exposed sessions by
   deleting the session rows or the whole account store, and block the affected path,
   account or address at the proxy.
2. **Assess**: identify which records and which people were affected, and whether the
   breach creates a risk to their rights. Preserve `PLANIT_LOG_DIR`, proxy logs and the
   analysis directories as evidence; do not edit them.
3. **Notify**: if a risk exists, notify the Office of the Data Protection Commissioner
   without undue delay and within **72 hours** of becoming aware, and notify affected
   people without undue delay. Use [ODPC CONTACT DETAILS] and [PRIVACY EMAIL].
4. **Record**: write down what happened, when it was discovered, the data and people
   affected, the containment steps and the notifications sent.
5. **Remediate**: patch the cause, rotate any exposed secret, invalidate sessions, re-run
   the test suite and update this checklist.

Because a hosted instance can hold real uploaded analyses, assume any exposure of an
upload workspace, account database or backup is a personal-data breach. A lost or stolen
host or backup should be treated the same way until proven otherwise.

## 6. ODPC registration and operator details

- Data controller: [FULL LEGAL NAME OF CONTROLLER], [POSTAL ADDRESS], Kenya
  (`PLANIT_OPERATOR_NAME`, `PLANIT_OPERATOR_ADDRESS`).
- Privacy contact: [PRIVACY EMAIL] (`PLANIT_PRIVACY_EMAIL`).
- ODPC registration: [ODPC REGISTRATION NUMBER OR "NOT YET REGISTERED"]
  (`PLANIT_ODPC_REGISTRATION`).
- ODPC contact details: [ODPC CONTACT DETAILS] (`PLANIT_ODPC_CONTACT`).
- Hosting, if any: [HOSTING PROVIDER AND LOCATION] (`PLANIT_HOSTING_PROVIDER`).
  International transfers: [INTERNATIONAL TRANSFER SAFEGUARDS OR "NONE"]
  (`PLANIT_INTERNATIONAL_TRANSFERS`).
- Backups, if any: [BACKUP RETENTION PERIOD OR "NONE"] (`PLANIT_BACKUP_RETENTION`).

`serve` refuses to start in production while the required values are empty or still look
like placeholders. That check helps prevent an accidental launch; it does not validate the
truth or legal sufficiency of what the operator entered.

Registration and annual fees depend on whether the operator is a data controller or
processor and on the volume of personal data. Confirm the current ODPC guidance and
whether registration is required before launch.

## 7. Data protection impact assessment (screening)

A full DPIA is not included. Screening questions the operator must answer:

1. Does the deployment process real financial data? A hosted instance can, because a
   signed-in user may upload their own transactions. Complete a full DPIA unless the
   operator can show the deployment is limited to synthetic sample data.
2. Is the service reachable beyond loopback? The intended public deployment is, through a
   TLS reverse proxy. Complete the TLS, hosting-terms and international-transfer review
   before exposing it.
3. Are people under 18 expected? The notice says 18+, or use with a parent or guardian.
   [AGE-ASSURANCE APPROACH] (`PLANIT_AGE_ASSURANCE`).
4. Is any data used for profiling or automated decisions with legal effect? No; the coach
   is rule-based, educational and produces no decision about a person.
5. Is sensitive data (health, biometrics, ethnicity, religion, political opinion) processed?
   It is not requested, and the terms forbid entering it, but an upload could contain it.
   The operator must define how such an upload is detected, removed and reported.
6. Could a breach cause significant harm? Yes, if account details or uploaded financial
   records are exposed. The controls above reduce but do not eliminate that risk.

Do not rely on the screening table as a substitute for a full DPIA. If any answer is
uncertain, complete the DPIA before launch.

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
  payment-method label in data; the full non-affiliation notice is in
  `src/student_spending/legal.py` and on `/terms`.
- The source is MIT licensed (`LICENSE`). The Plan It name and logo are
  [TRADEMARK STATUS AND OWNER] (`PLANIT_TRADEMARK`).
- Third-party components: `THIRD_PARTY_LICENSES.md`.

## 10. Pre-launch checklist

- [ ] Set every required `PLANIT_*` value in `/etc/plan-it/plan-it.env`; confirm that no
      bracketed placeholder remains on `/privacy` or `/terms`.
- [ ] Set the effective date and confirm the policy version string.
- [ ] Obtain Kenyan legal review of the privacy notice and terms, then set
      `PLANIT_LEGAL_REVIEWED=1`.
- [ ] Decide whether ODPC registration is required; record the number or the exact status.
- [ ] Complete a DPIA if the deployment can hold real uploaded financial records.
- [ ] Publish retention periods and enable `plan-it-prune.timer` on that schedule.
- [ ] Terminate TLS at Caddy or nginx; bind the app to loopback; confirm
      `PLANIT_SECURE_COOKIES=1` and `PLANIT_PUBLIC_URL` is HTTPS.
- [ ] Set `PLANIT_TRUST_PROXY=1` only if the proxy overwrites `X-Forwarded-For`.
- [ ] Encrypt the data disk and backups; set `PLANIT_BACKUP_RETENTION`; test a restore.
- [ ] Restrict `/var/lib/plan-it`, `/etc/plan-it` and backups to the service account and
      administrators.
- [ ] Confirm the committed sample dashboard still labels its data as synthetic.
- [ ] Re-run `python run_tests.py`, `python -m pip check` and `python -m compileall -q src`.
- [ ] Verify `https://<host>/healthz` returns `200` with both checks true.
- [ ] Keep this checklist, the breach log and the incident-response plan with the operated
      deployment. Review them after every material change.
