"""Allow ``python -m student_spending`` to run the pipeline."""

from __future__ import annotations

from .cli import main

if __name__ == "__main__":
    raise SystemExit(main())
