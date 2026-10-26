"""Generate the synthetic raw CSV files used by the pipeline.

Run from the project root:

    .venv\\Scripts\\python.exe scripts\\generate_synthetic_data.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from student_spending import config  # noqa: E402
from student_spending.synthetic import generate_dataset  # noqa: E402


def main() -> int:
    summary = generate_dataset(config.RAW_DATA_DIR)
    print(f"Wrote {summary['transactions']} transaction rows to data/raw/student_expenses.csv")
    print(f"Wrote {summary['profiles']} student profiles to data/raw/student_profiles.csv")
    print(f"Wrote {summary['budgets']} budget rows to data/raw/student_budgets.csv")
    print("\nPlanted data quality defects:")
    for name, count in sorted(summary["defects"].items()):
        print(f"  {name:<32} {count}")
    print("\nAll records are synthetic. Regenerate with the same seed for identical files.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
