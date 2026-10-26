"""Pipeline orchestration: extract -> validate -> load -> analyse -> check -> report."""

from __future__ import annotations

import argparse
import logging
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from . import analytics, config, database, extract, load, logging_setup, quality, report, validate
from .errors import PipelineError

logger = logging.getLogger(__name__)


@dataclass
class PipelineOptions:
    transactions_csv: Path = config.DEFAULT_TRANSACTIONS_CSV
    profiles_csv: Path = config.DEFAULT_PROFILES_CSV
    budgets_csv: Path = config.DEFAULT_BUDGETS_CSV
    db_path: Path = config.DEFAULT_DB_PATH
    reports_dir: Path = config.REPORTS_DIR
    quarantine_dir: Path = config.QUARANTINE_DIR
    full_refresh: bool = False


def _new_run_id() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{stamp}-{uuid.uuid4().hex[:6]}"


def _display(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(config.PROJECT_ROOT))
    except ValueError:
        return str(path)


def _print_summary(
    run_id: str,
    counts: dict[str, int],
    flagged: int,
    rejection_path: Path,
    report_path: Path,
    skipped_budgets: int,
    failures: list[quality.CheckResult],
) -> None:
    accepted = counts["rows_accepted"]
    line = "-" * 64
    print(line)
    print(f"Run {run_id}")
    print(f"Rows read .......... {counts['rows_read']}")
    print(
        f"Accepted ........... {accepted} "
        f"(inserted {counts['rows_inserted']}, updated {counts['rows_updated']}, "
        f"unchanged {counts['rows_unchanged']})"
    )
    print(f"Rejected ........... {counts['rows_rejected']} duplicate row(s)")
    print(f"Quarantined ........ {counts['rows_quarantined']} row(s) held for review")
    if skipped_budgets:
        print(f"Budget rows skipped  {skipped_budgets}")
    print(f"Flagged anomalies .. {flagged}")
    print(f"Quality checks ..... {'FAILED (' + str(len(failures)) + ')' if failures else 'all passed'}")
    print(f"Report ............. {_display(report_path)}")
    print(f"Audit trail ........ {_display(rejection_path)}")
    print(line)


def run_pipeline(options: PipelineOptions | None = None) -> int:
    """Execute every stage. Returns a process exit code."""
    options = options or PipelineOptions()
    run_id = _new_run_id()
    started_at = config.utc_now()

    if options.full_refresh:
        database.reset_database(options.db_path)

    connection = database.connect(options.db_path)
    database.initialize_database(connection)
    load.start_run(connection, run_id, str(options.transactions_csv), started_at)

    try:
        profiles = extract.read_profiles(options.profiles_csv)
        known_students = {str(profile["student_id"]) for profile in profiles}
        load.load_students(connection, profiles)
        load.ensure_categories(connection)

        budgets, skipped_budgets = extract.read_budgets(
            options.budgets_csv, known_students, set(config.ALLOWED_CATEGORIES)
        )
        load.load_budgets(connection, budgets)

        raw_records = extract.extract_transactions(options.transactions_csv)
        validation = validate.validate_records(raw_records, known_students)
        for warning in validation.warnings:
            logger.warning("%s", warning)

        loaded_at = config.utc_now()
        stats = load.load_transactions(connection, validation.accepted, loaded_at)
        load.save_rejections(connection, run_id, validation.rejected, loaded_at)

        counts = {
            "rows_read": validation.rows_read,
            "rows_accepted": len(validation.accepted),
            "rows_rejected": validation.rejected_count,
            "rows_quarantined": validation.quarantined_count,
            "rows_inserted": stats.inserted,
            "rows_updated": stats.updated,
            "rows_unchanged": stats.unchanged,
        }

        flagged = analytics.flag_anomalies(connection)
        load.finish_run(
            connection,
            run_id,
            status="success",
            finished_at=config.utc_now(),
            counts=counts,
        )

        rejection_path = report.write_rejection_csv(
            validation.rejected, options.quarantine_dir, run_id
        )
        checks = quality.run_checks(connection, run_id)
        quality.save_results(connection, run_id, checks, config.utc_now())
        failures = [check for check in checks if not check.passed]
        if failures:
            load.finish_run(
                connection,
                run_id,
                status="failed",
                finished_at=config.utc_now(),
                counts=counts,
                message=f"{len(failures)} data quality check(s) failed",
            )

        report_path = report.write_report(connection, run_id, options.reports_dir)
        _print_summary(
            run_id, counts, flagged, rejection_path, report_path, skipped_budgets, failures
        )
        return 0 if not failures else 1

    except PipelineError as error:
        logger.error("pipeline failed: %s", error)
        _mark_failed(connection, run_id, str(error))
        return 2
    except Exception as error:  # noqa: BLE001 - top-level safety net
        logger.exception("unexpected pipeline failure")
        _mark_failed(connection, run_id, f"{type(error).__name__}: {error}")
        return 3
    finally:
        connection.close()


def _mark_failed(connection: sqlite3.Connection, run_id: str, message: str) -> None:
    try:
        load.finish_run(
            connection,
            run_id,
            status="failed",
            finished_at=config.utc_now(),
            counts={},
            message=message,
        )
    except sqlite3.Error:
        logger.exception("could not record the failed run in pipeline_runs")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the Student Spending Analytics pipeline end to end."
    )
    parser.add_argument(
        "--transactions",
        type=Path,
        default=config.DEFAULT_TRANSACTIONS_CSV,
        help="raw transaction CSV (default: data/raw/student_expenses.csv)",
    )
    parser.add_argument(
        "--profiles",
        type=Path,
        default=config.DEFAULT_PROFILES_CSV,
        help="student profile CSV (default: data/raw/student_profiles.csv)",
    )
    parser.add_argument(
        "--budgets",
        type=Path,
        default=config.DEFAULT_BUDGETS_CSV,
        help="budget CSV (default: data/raw/student_budgets.csv)",
    )
    parser.add_argument(
        "--db",
        type=Path,
        default=config.DEFAULT_DB_PATH,
        help="SQLite warehouse path (default: warehouse/student_spending.db)",
    )
    parser.add_argument(
        "--full-refresh",
        action="store_true",
        help="delete the existing warehouse file before loading (destructive)",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="console log level (default: INFO)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    logging_setup.configure(arguments.log_level)
    options = PipelineOptions(
        transactions_csv=arguments.transactions,
        profiles_csv=arguments.profiles,
        budgets_csv=arguments.budgets,
        db_path=arguments.db,
        full_refresh=arguments.full_refresh,
    )
    return run_pipeline(options)


if __name__ == "__main__":
    raise SystemExit(main())
