-- Example analytical queries for the Student Spending Analytics warehouse.
-- Run them with any SQLite client pointed at warehouse/student_spending.db.

-- 1. Total spend per student.
SELECT profile_label,
       transaction_count,
       ROUND(total_kes, 2)        AS total_kes,
       ROUND(avg_transaction_kes, 2) AS avg_transaction_kes
FROM v_student_totals
ORDER BY total_kes DESC;

-- 2. Monthly spend by category for one student.
SELECT transaction_month,
       category,
       transaction_count,
       ROUND(total_kes, 2) AS total_kes
FROM v_monthly_category
WHERE student_id = 'STU-001'
ORDER BY transaction_month, total_kes DESC;

-- 3. Average daily spend across the whole dataset.
SELECT ROUND(AVG(total_kes), 2) AS avg_daily_kes,
       ROUND(MAX(total_kes), 2) AS busiest_day_kes
FROM v_daily_spending;

-- 4. The five most expensive spending days.
SELECT transaction_date,
       transaction_count,
       ROUND(total_kes, 2) AS total_kes
FROM v_daily_spending
ORDER BY total_kes DESC
LIMIT 5;

-- 5. Budget lines that overspent, worst first.
SELECT profile_label,
       budget_month,
       category,
       ROUND(budget_kes, 2)               AS budget_kes,
       ROUND(actual_kes, 2)               AS actual_kes,
       ROUND(actual_kes - budget_kes, 2)  AS overspend_kes
FROM v_budget_vs_actual
WHERE is_over_budget = 1
ORDER BY overspend_kes DESC;

-- 6. Week-over-week movement, using the LAG window function.
SELECT profile_label,
       year_week,
       ROUND(total_kes, 2) AS total_kes,
       previous_week_kes,
       change_pct
FROM v_week_over_week
ORDER BY year_week, profile_label;

-- 7. Essential versus discretionary spending, using a CASE expression and a CTE.
WITH split AS (
    SELECT CASE WHEN is_discretionary = 1 THEN 'discretionary' ELSE 'essential' END AS bucket,
           SUM(amount_cents) AS total_cents
    FROM v_transactions
    GROUP BY bucket
)
SELECT bucket,
       ROUND(total_cents / 100.0, 2) AS total_kes,
       ROUND(100.0 * total_cents / (SELECT SUM(total_cents) FROM split), 2) AS share_pct
FROM split
ORDER BY total_cents DESC;

-- 8. Transactions flagged for investigation.
SELECT transaction_date, profile_label, category,
       ROUND(amount_kes, 2) AS amount_kes, merchant, anomaly_reason
FROM v_flagged_transactions
ORDER BY amount_kes DESC;

-- 9. Why rows were quarantined in the latest run.
SELECT q.reason_code, COUNT(*) AS rows_held
FROM transactions_quarantine AS q
WHERE q.run_id = (SELECT run_id FROM pipeline_runs ORDER BY rowid DESC LIMIT 1)
GROUP BY q.reason_code
ORDER BY rows_held DESC;

-- 10. Quality evidence for the latest run.
SELECT d.check_name,
       CASE d.passed WHEN 1 THEN 'PASS' ELSE 'FAIL' END AS result,
       d.observed,
       d.expected
FROM data_quality_results AS d
WHERE d.run_id = (SELECT run_id FROM pipeline_runs ORDER BY rowid DESC LIMIT 1)
ORDER BY d.check_name;

-- 11. Merchant concentration: where the money actually goes.
SELECT merchant,
       COUNT(*) AS transaction_count,
       ROUND(SUM(amount_kes), 2) AS total_kes
FROM v_transactions
GROUP BY merchant
ORDER BY SUM(amount_cents) DESC
LIMIT 10;
