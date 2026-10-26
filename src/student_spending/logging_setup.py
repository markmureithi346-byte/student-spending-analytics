"""Logging configuration shared by every entry point."""

from __future__ import annotations

import logging

from . import config

_CONFIGURED = False
FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"


def configure(level: str = "INFO") -> None:
    """Log to the console and to logs/pipeline.log exactly once per process."""
    global _CONFIGURED
    root = logging.getLogger()
    root.setLevel(level.upper())
    if _CONFIGURED:
        return

    config.LOG_DIR.mkdir(parents=True, exist_ok=True)
    formatter = logging.Formatter(FORMAT, datefmt="%Y-%m-%d %H:%M:%S")

    console = logging.StreamHandler()
    console.setFormatter(formatter)
    root.addHandler(console)

    file_handler = logging.FileHandler(config.LOG_DIR / "pipeline.log", encoding="utf-8")
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)

    _CONFIGURED = True
