#!/usr/bin/env python3
"""Write a consistent, timestamped snapshot of Plan It's data.

SQLite files are copied with the sqlite3 backup API, so a live server does not
need to be stopped. Uploaded CSVs, metadata and reports are copied as files.
The output is plaintext: encrypt the destination (for example with restic or
an encrypted volume) before it leaves the server.

Run it with the same ``PLANIT_*`` environment as the service. The supplied
``deploy/plan-it-backup.service`` loads ``/etc/plan-it/plan-it.env`` and is the
recommended path. For an ad-hoc run, let systemd parse the same file:

    sudo systemd-run --wait --pipe --uid=planit \
      --property=EnvironmentFile=/etc/plan-it/plan-it.env \
      --property=WorkingDirectory=/opt/plan-it \
      /opt/plan-it/.venv/bin/python /opt/plan-it/scripts/backup_planit.py \
      --dest /var/backups/plan-it

Retention of the snapshots themselves is the operator's job; pair this with
`restic forget --prune` or an equivalent policy.
"""

from __future__ import annotations

import argparse
import shutil
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

from student_spending import config


def _backup_sqlite(source: Path, destination: Path) -> None:
    if not source.is_file():
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    uri = source.resolve().as_uri() + "?mode=ro"
    connection = sqlite3.connect(uri, uri=True)
    copy = sqlite3.connect(destination)
    try:
        connection.backup(copy)
    finally:
        copy.close()
        connection.close()
    config.restrict_file(destination)


def _copy_tree(source: Path, destination: Path) -> int:
    if not source.is_dir():
        return 0
    files = 0
    for item in source.rglob("*"):
        if not item.is_file():
            continue
        target = destination / item.relative_to(source)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(item, target)
        config.restrict_file(target)
        files += 1
    return files


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--dest",
        type=Path,
        required=True,
        help="directory that receives the timestamped snapshot",
    )
    parser.add_argument(
        "--label", default="", help="optional suffix for the snapshot name"
    )
    arguments = parser.parse_args(argv)

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    name = f"plan-it-{stamp}" + (f"-{arguments.label}" if arguments.label else "")
    root = arguments.dest.expanduser().resolve() / name
    root.mkdir(parents=True, exist_ok=False)
    config.ensure_private_dir(root)

    databases: list[tuple[Path, Path]] = [
        (Path(config.ACCOUNTS_DB_PATH), root / "accounts.db"),
        (Path(config.DEFAULT_DB_PATH), root / "warehouse" / "student_spending.db"),
    ]
    warehouses = Path(config.WAREHOUSE_DIR)
    if warehouses.is_dir():
        for item in sorted(warehouses.rglob("*.db")):
            if item.resolve() == Path(config.DEFAULT_DB_PATH).resolve():
                continue
            relative = item.resolve().relative_to(warehouses.resolve())
            databases.append((item, root / "warehouse" / relative))

    copied_databases = 0
    for source, destination in databases:
        if source.is_file():
            _backup_sqlite(source, destination)
            copied_databases += 1

    copied_files = _copy_tree(
        Path(config.UPLOAD_DATA_DIR), root / "uploads"
    ) + _copy_tree(Path(config.UPLOAD_REPORT_DIR), root / "reports")

    print(f"Snapshot: {root}")
    print(f"  databases: {copied_databases}")
    print(f"  uploaded and report files: {copied_files}")
    if not copied_databases and not copied_files:
        print("  warning: nothing was copied; check PLANIT_* paths.", file=sys.stderr)
        return 1
    print("  plaintext snapshot: encrypt it before moving it off this server.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
