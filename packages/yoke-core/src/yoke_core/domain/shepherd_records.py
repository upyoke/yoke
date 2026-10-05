"""Record formatting and stdin helpers for shepherd commands."""
from __future__ import annotations

import select as select_mod
import sys
from datetime import datetime, timezone


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def format_row(row) -> str:
    return "|".join("" if value is None else str(value) for value in tuple(row))


def read_stdin_safe() -> str:
    if sys.stdin.isatty():
        return ""
    if hasattr(select_mod, "select"):
        readable, _, _ = select_mod.select([sys.stdin], [], [], 0.5)
        if not readable:
            return ""
    return sys.stdin.read()
