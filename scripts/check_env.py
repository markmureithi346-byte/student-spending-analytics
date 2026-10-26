"""Check that the interpreter running this script is usable for the project.

Run from the project root:

    .venv\\Scripts\\python.exe scripts\\check_env.py
"""

from __future__ import annotations

import sqlite3
import sys

MINIMUM_PYTHON = (3, 12)
MINIMUM_SQLITE = (3, 35)


def main() -> int:
    python_ok = sys.version_info[:2] >= MINIMUM_PYTHON
    sqlite_version = sqlite3.sqlite_version
    sqlite_ok = tuple(int(part) for part in sqlite_version.split(".")[:2]) >= MINIMUM_SQLITE
    in_venv = sys.prefix != sys.base_prefix

    print(f"Python: {sys.version.split()[0]}")
    print(f"Interpreter: {sys.executable}")
    print(f"SQLite: {sqlite_version}")
    print(f"Virtual environment: {'active' if in_venv else 'NOT active'}")

    ok = python_ok and sqlite_ok and in_venv
    if not python_ok:
        print(f"FAIL: Python {MINIMUM_PYTHON[0]}.{MINIMUM_PYTHON[1]}+ is required")
    if not sqlite_ok:
        print(f"FAIL: SQLite {MINIMUM_SQLITE[0]}.{MINIMUM_SQLITE[1]}+ is required")
    if not in_venv:
        print("FAIL: activate .venv before running the pipeline")
    print("Environment OK" if ok else "Environment NOT OK")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
