"""Record formatting and stdin helpers for shepherd commands."""

from __future__ import annotations

import select as select_mod
import sys
from datetime import datetime
from yoke_contracts.timestamps import utc_now, format_instant


def now_iso() -> datetime:
    return utc_now()


def format_row(row) -> str:
    return "|".join(
        ""
        if value is None
        else format_instant(value)
        if isinstance(value, datetime)
        else str(value)
        for value in tuple(row)
    )


def read_stdin_safe() -> str:
    if sys.stdin.isatty():
        return ""
    if hasattr(select_mod, "select"):
        readable, _, _ = select_mod.select([sys.stdin], [], [], 0.5)
        if not readable:
            return ""
    return sys.stdin.read()
