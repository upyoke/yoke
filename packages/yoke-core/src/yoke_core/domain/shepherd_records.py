"""Record formatting and item-reference normalization for shepherd commands."""
from __future__ import annotations

import re
import select as select_mod
import sys
from datetime import datetime, timezone
from typing import Any

from yoke_core.domain.item_ref_columns import render_column_item_ref

_ITEM_REF_RE = re.compile(r"^(?:[A-Za-z][A-Za-z0-9]*-)?(\d+)$")


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def format_row(row) -> str:
    return "|".join("" if value is None else str(value) for value in tuple(row))


def normalize_item_id(raw: str, conn: Any) -> str:
    """Canonicalize an item token to the public PREFIX-N API form.

    The result is rendered from the resolved item's own project — a
    blocker in another project canonicalizes to that project's prefix,
    never the caller's. Accepts a public ``PREFIX-N`` ref or a bare item
    id; anything else raises.
    """
    match = _ITEM_REF_RE.match(str(raw).strip())
    if match is None or int(match.group(1)) == 0:
        raise ValueError(
            f"invalid item ID: {raw} (expected an item id or a PREFIX-N ref)"
        )
    return render_column_item_ref(conn, str(raw).strip())


def read_stdin_safe() -> str:
    if sys.stdin.isatty():
        return ""
    if hasattr(select_mod, "select"):
        readable, _, _ = select_mod.select([sys.stdin], [], [], 0.5)
        if not readable:
            return ""
    return sys.stdin.read()
