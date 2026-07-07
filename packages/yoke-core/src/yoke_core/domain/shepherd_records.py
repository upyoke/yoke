"""Record formatting and item-reference normalization for shepherd commands."""
from __future__ import annotations

import re
import select as select_mod
import sys
from datetime import datetime, timezone


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def format_row(row) -> str:
    return "|".join("" if value is None else str(value) for value in tuple(row))


def normalize_item_id(raw: str) -> str:
    """Normalize numeric or YOK-prefixed input to canonical YOK-N format."""
    num = re.sub(r"^[Yy][Oo][Kk]-", "", raw)
    if not num or not num.isdigit():
        raise ValueError(f"invalid item ID: {raw} (expected numeric item ID or YOK-N ref)")
    num = num.lstrip("0") or "0"
    if num == "0":
        raise ValueError(f"invalid item ID: {raw} (expected numeric item ID or YOK-N ref)")
    return f"YOK-{num}"


def read_stdin_safe() -> str:
    if sys.stdin.isatty():
        return ""
    if hasattr(select_mod, "select"):
        readable, _, _ = select_mod.select([sys.stdin], [], [], 0.5)
        if not readable:
            return ""
    return sys.stdin.read()
