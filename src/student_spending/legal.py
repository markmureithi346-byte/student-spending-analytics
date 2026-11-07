"""Privacy notice and terms for the hosted Plan It service.

The copy describes the app honestly: it tracks numbers, does not hold or move
money, and does not provide financial advice. Operator-specific details come
from environment configuration. Anything still unset stays visible as a
bracketed placeholder, and production mode refuses to start until the required
values are supplied and a qualified Kenyan lawyer has reviewed the pages.
"""

from __future__ import annotations

from . import config

POLICY_VERSION = config.POLICY_VERSION
DRAFT_NOTICE = (
    "" if config.LEGAL_REVIEWED else
    "Draft - to be reviewed by a qualified Kenyan lawyer before launch."
)
DISCLAIMER = (
    "Plan It is a tracking tool. It does not provide financial, investment, tax "
    "or legal advice and does not hold or move your money."
)
MPESA_NOTICE = (
    "M-Pesa is a registered trademark of Safaricom PLC. Plan It is not "
    "affiliated with, endorsed by, sponsored by or approved by Safaricom. The "
    "M-Pesa name appears only as an optional payment-method label in data."
)

_DRAFT_BANNER = (
    f'<p class="banner note" role="status"><strong>Draft.</strong> '
    f"{DRAFT_NOTICE}</p>"
    if DRAFT_NOTICE
    else ""
)

_HEAD = f"""
<main class="shell legal-shell">
  {_DRAFT_BANNER}
  <p class="legal-nav"><a href="/">Dashboard</a> <a href="/plan">Money planner</a>
    <a href="/privacy">Privacy notice</a> <a href="/terms">Terms of use</a></p>
"""

_PRIVACY_BODY = _HEAD + f"""
  <article class="panel legal-body">
    <p class="eyebrow">Plan It &middot; privacy</p>
    <h1>Privacy notice</h1>
    <p class="legal-version">Policy version {POLICY_VERSION}. Effective
      [EFFECTIVE DATE].</p>
    <p class="banner bad" role="note"><strong>Financial disclaimer.</strong>
      {DISCLAIMER}</p>

    <h2>1. Who is responsible</h2>
    <p>The data controller is [FULL LEGAL NAME OF CONTROLLER], of
      [POSTAL ADDRESS], Kenya. Privacy contact:
      <a href="mailto:[PRIVACY EMAIL]">[PRIVACY EMAIL]</a>. ODPC registration:
      [ODPC REGISTRATION NUMBER OR "NOT YET REGISTERED"].</p>
    <p>Plan It is a budgeting and spending-analysis service operated by
      [FULL LEGAL NAME OF CONTROLLER] and hosted by
      [HOSTING PROVIDER AND LOCATION]. It does not connect to a bank, card,
      mobile-money wallet or payment account.</p>

    <h2>2. What we collect</h2>
    <ul>
      <li><strong>Account details:</strong> display name, email address, a
        salted scrypt password hash (never the password itself), a recovery-code
        hash, account creation time, consent time and the privacy-policy version
        you accepted.</li>
      <li><strong>Session details:</strong> a SHA-256 digest of the session
        token, its CSRF token, creation time and expiry. The session cookie is
        HttpOnly and SameSite=Strict.</li>
      <li><strong>Uploaded analysis:</strong> the transactions CSV you choose,
        its filename and row count, the isolated SQLite warehouse, the report
        and quality results built from it. A CSV may contain personal data; you
        are responsible for having a lawful basis to upload it.</li>
      <li><strong>Planner entries:</strong> the figures you type into the money
        planner are processed to render the response. The planner does not save
        the plan after the response is rendered.</li>
      <li><strong>Operational logs:</strong> server and pipeline logs used to
        diagnose errors and abuse. They are stored under the operator's log
        directory and are not sold or used for advertising.</li>
    </ul>
    <p>Never enter card numbers, bank account numbers, mobile-money PINs,
      national ID numbers or payment credentials. Do not upload another person's
      personal data unless you have the right to do so.</p>

    <h2>3. Why we use it and the lawful basis</h2>
    <ul>
      <li>To create and secure your account, sign you in and let you recover it:
        performance of the service you asked for and your consent.</li>
      <li>To validate and analyse a CSV you upload, and to show the planner and
        dashboard: performance of the service and, where the data is personal,
        your consent or another lawful basis you are responsible for.</li>
      <li>To prevent abuse, rate-limit sign-in attempts and investigate errors:
        our legitimate interest in keeping the service secure, balanced against
        your rights.</li>
      <li>To meet legal obligations that apply to the operator: compliance with
        law.</li>
    </ul>
    <p>Providing the account details is required to use the planner and uploads.
      You can use the public sample dashboard and report without an account.</p>

    <h2>4. How long we keep it</h2>
    <ul>
      <li>Account and session records: until you delete the account, then
        removed.</li>
      <li>Uploaded analyses: [RETENTION PERIOD, FOR EXAMPLE 30 DAYS] after
        creation, unless you delete them sooner. The operator runs the
        documented pruning command on that schedule.</li>
      <li>Server and pipeline logs: [LOG RETENTION PERIOD, FOR EXAMPLE 14
        DAYS].</li>
      <li>Backups: [BACKUP RETENTION PERIOD OR "NONE"].</li>
    </ul>

    <h2>5. Who we share it with</h2>
    <p>We do not sell personal data. The application contains no advertising,
      analytics or third-party tracking scripts. The service is hosted by
      [HOSTING PROVIDER AND LOCATION]. International transfers:
      [INTERNATIONAL TRANSFER SAFEGUARDS OR "NONE"].</p>

    <h2>6. How we protect it</h2>
    <p>Passwords use scrypt with a random salt; session tokens are stored only as
      SHA-256 digests and each session carries a random CSRF token; cookies are
      HttpOnly, SameSite=Strict and Secure on the public service; sign-in attempts are
      rate-limited; state-changing requests need a same-origin browser context
      and a per-session CSRF token; uploaded analyses are scoped to the account
      that created them; and warehouse connections are read-only. The operator
      is responsible for TLS, encrypted disks and backups, access control,
      patching and security monitoring. No method is perfectly secure.</p>

    <h2>7. Your rights</h2>
    <p>Under the Kenya Data Protection Act 2019 you may ask for access,
      correction, deletion, restriction or portability of your data, object to
      processing, and withdraw consent. The <a href="/account">account page</a>
      provides a JSON export and account deletion after password re-entry.
      Withdrawing consent for account processing means deleting the account.
      Deletion removes the active account rows, sessions and analyses. Copies may
      remain in backups until the published backup retention period ends, and the
      operator handles storage-level residual copies under its erasure policy.
      You may also complain to the Office of the Data Protection Commissioner:
      [ODPC CONTACT DETAILS].</p>

    <h2>8. Cookies</h2>
    <p>The only cookie is the session cookie. It is not used for advertising or
      analytics and is removed when it expires or you sign out.</p>

    <h2>9. Children</h2>
    <p>The service is intended for people aged 18 or over. [AGE-ASSURANCE
      APPROACH].</p>

    <h2>10. Breach response</h2>
    <p>If a personal-data breach creates a risk to your rights, the operator will
      notify the ODPC and affected people without undue delay and within 72 hours
      where the law requires it. Contact [PRIVACY EMAIL] with questions.</p>

    <h2>11. Changes</h2>
    <p>We will publish a new policy version and ask you to review it before it
      applies.</p>

    <p class="legal-foot">Policy version {POLICY_VERSION}.
      {DRAFT_NOTICE}</p>
  </article>
</main>
"""

_TERMS_BODY = _HEAD + f"""
  <article class="panel legal-body">
    <p class="eyebrow">Plan It &middot; terms</p>
    <h1>Terms of use</h1>
    <p class="legal-version">Policy version {POLICY_VERSION}. Effective
      [EFFECTIVE DATE].</p>
    <p class="banner bad" role="note"><strong>Financial disclaimer.</strong>
      {DISCLAIMER}</p>

    <h2>1. What Plan It is</h2>
    <p>Plan It is a budgeting and spending-analysis service. It compares numbers
      you type or upload with each other. It does not connect to a bank, card,
      mobile-money wallet or payment account, and it does not execute, receive,
      hold or move money.</p>

    <h2>2. Not financial services or advice</h2>
    <p>{DISCLAIMER} The rule-based coach is educational and does not create an
      adviser-client relationship. Plan It is not licensed by the Central Bank of
      Kenya, the Capital Markets Authority or any other financial regulator, and
      it does not provide licensed financial services.</p>

    <h2>3. Who may use it</h2>
    <p>You must be at least 18, or use it with the involvement of a parent or
      guardian. You must be able to enter into a binding agreement under Kenyan
      law.</p>

    <h2>4. Your account</h2>
    <ul>
      <li>Use your own email address and a unique password. Never reuse a
        password from another service.</li>
      <li>Never enter card numbers, bank account numbers, mobile-money PINs or
        payment credentials.</li>
      <li>Keep your recovery code private; it is shown once.</li>
      <li>You are responsible for activity under your account. Tell the operator
        at [PRIVACY EMAIL] if you suspect unauthorised access.</li>
      <li>You may delete your account at any time from the account page.</li>
    </ul>

    <h2>5. Your data</h2>
    <p>You keep ownership of the data you enter or upload. You grant the operator
      permission to process it to provide the service, including storing it on
      the operator's servers for the retention period in the privacy notice. Only
      upload data you have the right to process. The operator may remove data
      that appears to breach these terms or the law.</p>

    <h2>6. Acceptable use</h2>
    <p>Do not attempt to break the service, access another account's analyses,
      upload malware, scrape other people's data, or use the service unlawfully.
      Security controls may block suspicious requests.</p>

    <h2>7. Availability and changes</h2>
    <p>The service is provided without a service-level commitment. Features may
      change or stop. The operator may suspend an account that abuses the service
      or creates a security risk.</p>

    <h2>8. Liability</h2>
    <p>To the extent permitted by Kenyan law, the service is provided "as is"
      without warranties. The operator is not liable for indirect or
      consequential loss, or for decisions you make using the figures. Nothing
      in these terms limits liability that cannot lawfully be limited.
      [LIABILITY CAP AND ANY REQUIRED CONSUMER-RIGHTS WORDING]</p>

    <h2>9. Intellectual property</h2>
    <p>The source code is released under the MIT licence in the repository.
      The Plan It name and logo are [TRADEMARK STATUS AND OWNER]. Third-party
      components are listed in <code>THIRD_PARTY_LICENSES.md</code>.</p>

    <h2>10. M-Pesa</h2>
    <p>{MPESA_NOTICE}</p>

    <h2>11. Ending the agreement</h2>
    <p>You may stop using the service and delete your account at any time. The
      operator may end access for a material breach of these terms or where
      required by law.</p>

    <h2>12. Governing law</h2>
    <p>These terms are governed by the laws of Kenya. The courts of
      [COUNTY] have jurisdiction, subject to any mandatory consumer protection
      rules.</p>

    <h2>13. Contact</h2>
    <p>[FULL LEGAL NAME OF CONTROLLER], [POSTAL ADDRESS], Kenya.
      Email: <a href="mailto:[PRIVACY EMAIL]">[PRIVACY EMAIL]</a>.</p>

    <p class="legal-foot">Policy version {POLICY_VERSION}.
      {DRAFT_NOTICE}</p>
  </article>
</main>
"""


def _fill(text: str) -> str:
    values = {
        "[EFFECTIVE DATE]": config.EFFECTIVE_DATE,
        "[FULL LEGAL NAME OF CONTROLLER]": config.OPERATOR_NAME,
        "[POSTAL ADDRESS]": config.OPERATOR_ADDRESS,
        "[PRIVACY EMAIL]": config.PRIVACY_EMAIL,
        '[ODPC REGISTRATION NUMBER OR "NOT YET REGISTERED"]': (
            config.ODPC_REGISTRATION
        ),
        "[RETENTION PERIOD, FOR EXAMPLE 30 DAYS]": config.RETENTION_PERIOD,
        "[LOG RETENTION PERIOD, FOR EXAMPLE 14 DAYS]": config.LOG_RETENTION,
        '[BACKUP RETENTION PERIOD OR "NONE"]': config.BACKUP_RETENTION,
        "[HOSTING PROVIDER AND LOCATION]": config.HOSTING_PROVIDER,
        '[INTERNATIONAL TRANSFER SAFEGUARDS OR "NONE"]': (
            config.INTERNATIONAL_TRANSFERS
        ),
        "[ODPC CONTACT DETAILS]": config.ODPC_CONTACT,
        "[AGE-ASSURANCE APPROACH]": config.AGE_ASSURANCE,
        "[LIABILITY CAP AND ANY REQUIRED CONSUMER-RIGHTS WORDING]": (
            config.LIABILITY_CAP
        ),
        "[TRADEMARK STATUS AND OWNER]": config.TRADEMARK,
        "[COUNTY]": config.COUNTY,
    }
    for token, value in values.items():
        if value:
            text = text.replace(token, value)
    return text


def privacy_body() -> str:
    return _fill(_PRIVACY_BODY)


def terms_body() -> str:
    return _fill(_TERMS_BODY)
