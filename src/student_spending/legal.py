"""Draft privacy and terms copy for the local Plan It learning tool.

The text is deliberately explicit about what the app does not do: it does not
hold or move money, it does not provide financial advice, and it collects only
the details needed for a local demo account. Every place that needs a real
organisation detail is marked with [BRACKETED PLACEHOLDERS]. A qualified Kenyan
lawyer must review this before launch.
"""

from __future__ import annotations

POLICY_VERSION = "2026-11-07"
DRAFT_NOTICE = (
    "Draft - to be reviewed by a qualified Kenyan lawyer before launch."
)
DISCLAIMER = (
    "Plan It is a tracking tool. It does not provide financial, investment, tax "
    "or legal advice and does not hold or move your money."
)
MPESA_NOTICE = (
    "M-Pesa is a registered trademark of Safaricom PLC. Plan It is not "
    "affiliated with, endorsed by, sponsored by or approved by Safaricom. The "
    "M-Pesa name appears only as an optional payment-method label in synthetic "
    "sample data."
)

_HEAD = f"""
<main class="shell legal-shell">
  <p class="banner note" role="status"><strong>Draft.</strong> {DRAFT_NOTICE}</p>
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
    <p>Plan It is a local learning project. The version in this repository runs
      on the operator's own computer and does not send account or analysis data
      to a remote service.</p>

    <h2>2. What we collect</h2>
    <ul>
      <li><strong>Account details:</strong> display name, email address, a
        salted scrypt password hash (never the password itself), a recovery-code
        hash, account creation time, consent time and the privacy-policy version
        you accepted.</li>
      <li><strong>Session details:</strong> a SHA-256 digest of the session
        token, its creation time and expiry. The cookie itself is HttpOnly and
        SameSite=Strict.</li>
      <li><strong>Uploaded analysis:</strong> the synthetic transactions CSV you
        choose, its filename and row count, the isolated SQLite warehouse, the
        report and quality results built from it.</li>
      <li><strong>Operational logs:</strong> local server and pipeline logs used
        to diagnose errors. They are stored under <code>logs/</code> and are not
        sent anywhere by the application.</li>
    </ul>
    <p>We do not ask for or intentionally store card numbers, bank account
      numbers, mobile-money PINs, national ID numbers, payment credentials or
      real student financial records. Do not enter them. The planner stores no
      plan: its figures exist only in the response to your form submission.</p>

    <h2>3. Why we use it and the lawful basis</h2>
    <ul>
      <li>To create and secure your account, sign you in and let you recover it:
        performance of the service you asked for and your consent.</li>
      <li>To validate and analyse a CSV you upload, and to show the planner and
        dashboard: performance of the service and your consent.</li>
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
        creation, unless you delete them sooner. The operator can run the
        documented pruning command.</li>
      <li>Server and pipeline logs: [LOG RETENTION PERIOD, FOR EXAMPLE 14
        DAYS].</li>
      <li>Backups, if any: [BACKUP RETENTION PERIOD OR "NONE"].</li>
    </ul>

    <h2>5. Who we share it with</h2>
    <p>We do not sell personal data. The application contains no advertising,
      analytics or third-party tracking scripts. If the operator deploys it on a
      hosted server, the hosting provider is
      [HOSTING PROVIDER AND LOCATION]. International transfers:
      [INTERNATIONAL TRANSFER SAFEGUARDS OR "NONE"].</p>

    <h2>6. How we protect it</h2>
    <p>Passwords use scrypt with a random salt; session tokens are stored only as
      SHA-256 digests; cookies are HttpOnly and SameSite=Strict; sign-in attempts
      are rate-limited; state-changing requests are checked for a same-origin
      browser context; uploaded analyses are scoped to the account that created
      them; and warehouse connections are read-only. No method is perfectly
      secure, so keep the server on loopback and use made-up data.</p>

    <h2>7. Your rights</h2>
    <p>Under the Kenya Data Protection Act 2019 you may ask for access,
      correction, deletion, restriction or portability of your data, object to
      processing, and withdraw consent. The <a href="/account">account page</a>
      provides a JSON export and account deletion after password re-entry.
      Withdrawing consent for account processing means deleting the account.
      You may also complain to the Office of the Data Protection Commissioner:
      [ODPC CONTACT DETAILS].</p>

    <h2>8. Cookies</h2>
    <p>The only cookie is the session cookie. It is not used for advertising or
      analytics and is removed when it expires or you sign out.</p>

    <h2>9. Children</h2>
    <p>The service is intended for people aged 18 or over. A student under 18
      should use it only with the involvement of a parent or guardian.
      [AGE-ASSURANCE APPROACH].</p>

    <h2>10. Breach response</h2>
    <p>If a personal-data breach creates a risk to your rights, the operator will
      notify the ODPC and affected people without undue delay and within 72 hours
      where the law requires it. Contact [PRIVACY EMAIL] with questions.</p>

    <h2>11. Changes</h2>
    <p>We will publish a new policy version and ask you to review it before it
      applies. This draft is not legal advice.</p>

    <p class="legal-foot">Policy version {POLICY_VERSION}. {DRAFT_NOTICE}</p>
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
    <p>Plan It is a local budgeting and spending-analysis learning tool. It
      compares numbers you type or upload with each other. It does not connect
      to a bank, card, mobile-money wallet or payment account, and it does not
      execute, receive, hold or move money.</p>

    <h2>2. Not financial services or advice</h2>
    <p>{DISCLAIMER} The rule-based coach is educational and does not create a
      adviser-client relationship. Plan It is not licensed by the Central Bank of
      Kenya, the Capital Markets Authority or any other financial regulator, and
      it does not provide licensed financial services.</p>

    <h2>3. Who may use it</h2>
    <p>You must be at least 18, or use it with the involvement of a parent or
      guardian. You must be able to enter into a binding agreement under Kenyan
      law.</p>

    <h2>4. Your account</h2>
    <ul>
      <li>Use made-up account details and never reuse a real password.</li>
      <li>Keep your recovery code private; it is shown once.</li>
      <li>You are responsible for activity under your account. Tell the operator
        at [PRIVACY EMAIL] if you suspect unauthorised access.</li>
      <li>You may delete your account at any time from the account page.</li>
    </ul>

    <h2>5. Synthetic data only</h2>
    <p>Do not upload or enter real student financial records, bank or card
      numbers, mobile-money PINs, national ID numbers or another person's
      personal data. You are responsible for ensuring you have the right to
      process anything you upload. The operator may remove data that appears to
      breach this rule.</p>

    <h2>6. Acceptable use</h2>
    <p>Do not attempt to break the service, access another account's analyses,
      upload malware, scrape other people's data, or use the service unlawfully.
      Security controls may block suspicious requests.</p>

    <h2>7. Your content</h2>
    <p>You keep ownership of the data you enter. You grant the operator
      permission to process it locally for the purpose of providing the service.
      The planner does not save your plan after the response is rendered.</p>

    <h2>8. Availability and changes</h2>
    <p>The service is provided as a learning project, without a service-level
      commitment. Features may change or stop. The operator may suspend an
      account that abuses the service or creates a security risk.</p>

    <h2>9. Liability</h2>
    <p>To the extent permitted by Kenyan law, the service is provided "as is"
      without warranties. The operator is not liable for indirect or
      consequential loss, or for decisions you make using the figures. Nothing
      in these terms limits liability that cannot lawfully be limited.
      [LIABILITY CAP AND ANY REQUIRED CONSUMER-RIGHTS WORDING].</p>

    <h2>10. Intellectual property</h2>
    <p>The source code is released under the MIT licence in the repository.
      The Plan It name and logo are [TRADEMARK STATUS AND OWNER]. Third-party
      components are listed in <code>THIRD_PARTY_LICENSES.md</code>.</p>

    <h2>11. M-Pesa</h2>
    <p>{MPESA_NOTICE}</p>

    <h2>12. Ending the agreement</h2>
    <p>You may stop using the service and delete your account at any time. The
      operator may end access for a material breach of these terms or where
      required by law.</p>

    <h2>13. Governing law</h2>
    <p>These terms are governed by the laws of Kenya. The courts of
      [COUNTY] have jurisdiction, subject to any mandatory consumer protection
      rules.</p>

    <h2>14. Contact</h2>
    <p>[FULL LEGAL NAME OF CONTROLLER], [POSTAL ADDRESS], Kenya.
      Email: <a href="mailto:[PRIVACY EMAIL]">[PRIVACY EMAIL]</a>.</p>

    <p class="legal-foot">Policy version {POLICY_VERSION}. {DRAFT_NOTICE}</p>
  </article>
</main>
"""


def privacy_body() -> str:
    return _PRIVACY_BODY


def terms_body() -> str:
    return _TERMS_BODY
