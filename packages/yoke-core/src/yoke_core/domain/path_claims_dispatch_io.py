"""Shared I/O helpers for the path-claims dispatch surfaces.

Hosts the small JSON output / error reporting / arg parsing helpers
:mod:`path_claims_dispatch` and :mod:`path_claims_dispatch_amend`
share. Pulled out so each handler module can stay focused on its own
subcommand semantics.
"""

from __future__ import annotations

import json
import sys
from typing import List, Optional, Sequence

from yoke_core.domain.db_helpers import connect


_YOKE_ITEM_PREFIX = "YOK-"


def parse_item_id(raw: str) -> int:
    text = (raw or "").strip()
    if not text:
        raise ValueError("item id is required")
    upper = text.upper()
    if upper.startswith(_YOKE_ITEM_PREFIX):
        text = text[len(_YOKE_ITEM_PREFIX):]
    try:
        return int(text)
    except ValueError as exc:
        raise ValueError(
            f"invalid item id {raw!r}; expected YOK-N or a bare integer"
        ) from exc


def parse_paths(raw: str) -> List[str]:
    return [p.strip() for p in (raw or "").split(",") if p.strip()]


def split_states(raw: Optional[Sequence[str]]) -> Optional[List[str]]:
    """Flatten repeatable/comma-separated ``--state`` values into one list.

    ``--state`` is ``action="append"``, so repeated flags arrive as a
    list; agents also reach for the comma-separated form
    (``--state planned,active,blocked``). Splitting on commas makes both
    shapes — and any mix — resolve to the same flat list instead of the
    comma-joined string matching no row. ``None``/empty stays ``None`` so
    the caller keeps its "all states" default.
    """
    if not raw:
        return None
    flat = [s.strip() for chunk in raw for s in chunk.split(",") if s.strip()]
    return flat or None


def print_json(payload: object) -> None:
    print(json.dumps(payload))


def print_error(code: str, message: str, **extra: object) -> None:
    payload = {"success": False, "code": code, "message": message}
    payload.update(extra)
    print(json.dumps(payload), file=sys.stderr)


def open_conn():
    return connect()


__all__ = [
    "open_conn",
    "parse_item_id",
    "parse_paths",
    "print_error",
    "print_json",
    "split_states",
]
