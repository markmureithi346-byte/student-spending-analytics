-- Schema for the Student Spending Analytics warehouse.
-- Monetary values are stored as integer cents (KES * 100) so SUM() never
-- drifts through floating-point error.

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS students (
    student_id           TEXT    PRIMARY KEY,
    profile_label        TEXT    NOT NULL,
    campus               TEXT    NOT NULL,
    study_year           INTEGER NOT NULL CHECK (study_year BETWEEN 1 AND 6),
    monthly_income_cents INTEGER NOT NULL CHECK (monthly_income_cents >= 0)
);

CREATE TABLE IF NOT EXISTS categories (
    category         TEXT    PRIMARY KEY,
    is_discretionary INTEGER NOT NULL CHECK (is_discretionary IN (0, 1))
);

CREATE TABLE IF NOT EXISTS transactions (
    transaction_id   TEXT    PRIMARY KEY,
    student_id       TEXT    NOT NULL REFERENCES students(student_id),
    transaction_date TEXT    NOT NULL CHECK (transaction_date GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'),
    amount_cents     INTEGER NOT NULL CHECK (amount_cents > 0),
    category         TEXT    NOT NULL REFERENCES categories(category),
    description      TEXT    NOT NULL,
    payment_method   TEXT    NOT NULL,
    merchant         TEXT    NOT NULL,
    is_recurring     INTEGER NOT NULL CHECK (is_recurring IN (0, 1)),
    record_hash      TEXT    NOT NULL,
    is_anomaly       INTEGER NOT NULL DEFAULT 0 CHECK (is_anomaly IN (0, 1)),
    anomaly_reason   TEXT,
    first_loaded_at  TEXT    NOT NULL,
    last_updated_at  TEXT    NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_transactions_student_date
    ON transactions (student_id, transaction_date);
CREATE INDEX IF NOT EXISTS idx_transactions_category
    ON transactions (category);

CREATE TABLE IF NOT EXISTS budgets (
    student_id   TEXT    NOT NULL REFERENCES students(student_id),
    budget_month TEXT    NOT NULL CHECK (budget_month GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]'),
    category     TEXT    NOT NULL REFERENCES categories(category),
    budget_cents INTEGER NOT NULL CHECK (budget_cents >= 0),
    PRIMARY KEY (student_id, budget_month, category)
);

CREATE TABLE IF NOT EXISTS transactions_quarantine (
    quarantine_id  INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id         TEXT    NOT NULL,
    transaction_id TEXT,
    student_id     TEXT,
    reason_code    TEXT    NOT NULL,
    reason_detail  TEXT    NOT NULL,
    raw_payload    TEXT    NOT NULL,
    quarantined_at TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS rejected_transactions (
    reject_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id         TEXT    NOT NULL,
    transaction_id TEXT,
    reason_code    TEXT    NOT NULL,
    reason_detail  TEXT    NOT NULL,
    raw_payload    TEXT    NOT NULL,
    rejected_at    TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS pipeline_runs (
    run_id           TEXT    PRIMARY KEY,
    started_at       TEXT    NOT NULL,
    finished_at      TEXT,
    status           TEXT    NOT NULL CHECK (status IN ('running', 'success', 'failed')),
    input_file       TEXT    NOT NULL,
    rows_read        INTEGER NOT NULL DEFAULT 0,
    rows_accepted    INTEGER NOT NULL DEFAULT 0,
    rows_rejected    INTEGER NOT NULL DEFAULT 0,
    rows_quarantined INTEGER NOT NULL DEFAULT 0,
    rows_inserted    INTEGER NOT NULL DEFAULT 0,
    rows_updated     INTEGER NOT NULL DEFAULT 0,
    rows_unchanged   INTEGER NOT NULL DEFAULT 0,
    message          TEXT
);

CREATE TABLE IF NOT EXISTS data_quality_results (
    run_id      TEXT    NOT NULL,
    check_name  TEXT    NOT NULL,
    passed      INTEGER NOT NULL CHECK (passed IN (0, 1)),
    observed    TEXT    NOT NULL,
    expected    TEXT    NOT NULL,
    checked_at  TEXT    NOT NULL,
    PRIMARY KEY (run_id, check_name)
);

-- Clean, enriched view of the fact table. All analytics build on this so
-- that amount_kes, month and weekday are defined exactly once.
CREATE VIEW IF NOT EXISTS v_transactions AS
SELECT
    t.transaction_id,
    t.student_id,
    s.profile_label,
    t.transaction_date,
    CAST(substr(t.transaction_date, 1, 4) AS INTEGER) AS transaction_year,
    substr(t.transaction_date, 1, 7) AS transaction_month,
    CAST(strftime('%W', t.transaction_date) AS INTEGER) AS week_of_year,
    strftime('%Y-W%W', t.transaction_date) AS year_week,
    CASE CAST(strftime('%w', t.transaction_date) AS INTEGER)
        WHEN 0 THEN 'Sunday'
        WHEN 1 THEN 'Monday'
        WHEN 2 THEN 'Tuesday'
        WHEN 3 THEN 'Wednesday'
        WHEN 4 THEN 'Thursday'
        WHEN 5 THEN 'Friday'
        ELSE 'Saturday'
    END AS weekday_name,
    t.amount_cents,
    t.amount_cents / 100.0 AS amount_kes,
    t.category,
    c.is_discretionary,
    t.description,
    t.payment_method,
    t.merchant,
    t.is_recurring,
    t.is_anomaly,
    t.anomaly_reason
FROM transactions AS t
JOIN students   AS s ON s.student_id = t.student_id
JOIN categories AS c ON c.category   = t.category;

CREATE VIEW IF NOT EXISTS v_monthly_category AS
SELECT
    student_id,
    profile_label,
    transaction_month,
    category,
    COUNT(*)                            AS transaction_count,
    SUM(amount_cents)                   AS total_cents,
    SUM(amount_cents) / 100.0           AS total_kes,
    ROUND(AVG(amount_cents) / 100.0, 2) AS avg_transaction_kes
FROM v_transactions
GROUP BY student_id, profile_label, transaction_month, category;

CREATE VIEW IF NOT EXISTS v_monthly_student AS
SELECT
    student_id,
    profile_label,
    transaction_month,
    COUNT(*)                  AS transaction_count,
    SUM(amount_cents)         AS total_cents,
    SUM(amount_cents) / 100.0 AS total_kes
FROM v_transactions
GROUP BY student_id, profile_label, transaction_month;

CREATE VIEW IF NOT EXISTS v_monthly_totals AS
SELECT
    transaction_month,
    COUNT(DISTINCT student_id) AS active_students,
    COUNT(*)                   AS transaction_count,
    SUM(amount_cents) / 100.0  AS total_kes
FROM v_transactions
GROUP BY transaction_month;

CREATE VIEW IF NOT EXISTS v_category_totals AS
SELECT
    category,
    COUNT(*)                  AS transaction_count,
    SUM(amount_cents)         AS total_cents,
    SUM(amount_cents) / 100.0 AS total_kes,
    ROUND(100.0 * SUM(amount_cents)
          / (SELECT SUM(amount_cents) FROM transactions), 2) AS share_pct
FROM v_transactions
GROUP BY category;

CREATE VIEW IF NOT EXISTS v_weekly_spending AS
SELECT
    student_id,
    profile_label,
    year_week,
    MIN(transaction_date)     AS week_start_date,
    COUNT(*)                  AS transaction_count,
    SUM(amount_cents)         AS total_cents,
    SUM(amount_cents) / 100.0 AS total_kes
FROM v_transactions
GROUP BY student_id, profile_label, year_week;

CREATE VIEW IF NOT EXISTS v_week_over_week AS
SELECT
    student_id,
    profile_label,
    year_week,
    transaction_count,
    total_kes,
    LAG(total_kes) OVER (
        PARTITION BY student_id ORDER BY year_week
    ) AS previous_week_kes,
    ROUND(total_kes - LAG(total_kes) OVER (
        PARTITION BY student_id ORDER BY year_week
    ), 2) AS change_kes,
    CASE
        WHEN LAG(total_kes) OVER (PARTITION BY student_id ORDER BY year_week) IS NULL THEN NULL
        ELSE ROUND(100.0 * (total_kes - LAG(total_kes) OVER (
                 PARTITION BY student_id ORDER BY year_week))
             / LAG(total_kes) OVER (PARTITION BY student_id ORDER BY year_week), 1)
    END AS change_pct
FROM v_weekly_spending;

CREATE VIEW IF NOT EXISTS v_weekday_spending AS
SELECT
    weekday_name,
    COUNT(*)                            AS transaction_count,
    SUM(amount_cents) / 100.0           AS total_kes,
    ROUND(AVG(amount_cents) / 100.0, 2) AS avg_transaction_kes
FROM v_transactions
GROUP BY weekday_name;

CREATE VIEW IF NOT EXISTS v_daily_spending AS
SELECT
    transaction_date,
    COUNT(*)                  AS transaction_count,
    SUM(amount_cents)         AS total_cents,
    SUM(amount_cents) / 100.0 AS total_kes
FROM v_transactions
GROUP BY transaction_date;

CREATE VIEW IF NOT EXISTS v_student_totals AS
SELECT
    student_id,
    profile_label,
    COUNT(*)                            AS transaction_count,
    SUM(amount_cents)                   AS total_cents,
    SUM(amount_cents) / 100.0           AS total_kes,
    ROUND(AVG(amount_cents) / 100.0, 2) AS avg_transaction_kes,
    MIN(transaction_date)               AS first_transaction_date,
    MAX(transaction_date)               AS last_transaction_date
FROM v_transactions
GROUP BY student_id, profile_label;

CREATE VIEW IF NOT EXISTS v_budget_vs_actual AS
WITH actuals AS (
    SELECT
        student_id,
        transaction_month AS budget_month,
        category,
        SUM(amount_cents) / 100.0 AS actual_kes
    FROM v_transactions
    GROUP BY student_id, transaction_month, category
)
SELECT
    b.student_id,
    s.profile_label,
    b.budget_month,
    b.category,
    b.budget_cents / 100.0                       AS budget_kes,
    COALESCE(a.actual_kes, 0)                    AS actual_kes,
    ROUND(COALESCE(a.actual_kes, 0) - b.budget_cents / 100.0, 2) AS variance_kes,
    CASE
        WHEN COALESCE(a.actual_kes, 0) > b.budget_cents / 100.0 THEN 1
        ELSE 0
    END                                          AS is_over_budget
FROM budgets AS b
JOIN students AS s ON s.student_id = b.student_id
LEFT JOIN actuals AS a
       ON a.student_id    = b.student_id
      AND a.budget_month  = b.budget_month
      AND a.category      = b.category;

CREATE VIEW IF NOT EXISTS v_flagged_transactions AS
SELECT
    transaction_id,
    student_id,
    profile_label,
    transaction_date,
    category,
    amount_kes,
    merchant,
    description,
    anomaly_reason
FROM v_transactions
WHERE is_anomaly = 1;
