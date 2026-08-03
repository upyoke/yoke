"""Context, DB helpers, and ref/timestamp parsing for ``validate_epic``.

Split out from ``validate_epic`` so the entry-point module stays focused on
orchestration and CLI plumbing. Contains pure-state types and side-effect-free
helpers (plus `_connect`, which opens a sqlite connection) that the
orchestrator and any future per-check carve-outs can share.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional, TextIO

from yoke_core.domain import db_backend
from yoke_core.domain.task_lifecycle import TASK_TERMINAL_SUCCESS


_NUMERIC_REF_RE = re.compile(r"^(?:[Yy][Oo][Kk]-)?([0-9]+)$")
_ACTIVE_TASK_STATUSES = ("implementing", "reviewing-implementation")


@dataclass(frozen=True)
class ValidateContext:
    repo_root: Path


def _connect(db_path: Optional[Path] = None) -> Any:
    # Route through the backend factory so Postgres authority reads the
    # DSN-pointed database instead of a SQLite file.
    from yoke_core.domain import db_backend

    return db_backend.connect(str(db_path) if db_path is not None else None)


def _p(conn) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _query_scalar(conn: Any, sql: str, params: tuple = ()) -> Optional[str]:
    row = conn.execute(sql, params).fetchone()
    if row is None:
        return None
    value = row[0]
    return None if value is None else str(value)


def _int_scalar(conn: Any, sql: str, params: tuple = ()) -> int:
    value = _query_scalar(conn, sql, params)
    if value in (None, "", "null"):
        return 0
    return int(value)


def _is_numeric_ref(epic_ref: str) -> bool:
    return _NUMERIC_REF_RE.fullmatch(epic_ref) is not None


def _resolve_epic(
    conn: Any, epic_ref: str
) -> tuple[str, str]:
    """Return ``(display_ref, canonical_epic_id)``.

    ``PREFIX-N`` resolves via the project's ``public_item_prefix`` +
    ``items.project_sequence``; a bare number stays an internal id.
    """

    display_ref = epic_ref
    if not _is_numeric_ref(epic_ref):
        return display_ref, epic_ref

    from yoke_core.domain.yok_n_parser import parse_item_id_or_none

    item_id = parse_item_id_or_none(
        epic_ref, conn=conn, allow_bare_internal=True
    )
    resolved = (
        None
        if item_id is None
        else _query_scalar(
            conn,
            f"SELECT CAST(id AS TEXT) FROM items WHERE id={_p(conn)} LIMIT 1",
            (item_id,),
        )
    )
    if not resolved:
        raise ValueError(f"Item {epic_ref} does not exist")

    return display_ref, resolved


def _parse_timestamp(value: str) -> Optional[datetime]:
    if not value:
        return None
    text = value.strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    if " " in text and "T" not in text:
        text = text.replace(" ", "T", 1)
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _result(out: TextIO, icon: str, message: str) -> None:
    out.write(f"{icon} {message}\n")


def _terminal_success_placeholders(conn) -> str:
    return ",".join(_p(conn) for _ in TASK_TERMINAL_SUCCESS)


__all__ = [
    "_ACTIVE_TASK_STATUSES",
    "ValidateContext",
    "_connect",
    "_query_scalar",
    "_int_scalar",
    "_is_numeric_ref",
    "_resolve_epic",
    "_parse_timestamp",
    "_p",
    "_result",
    "_terminal_success_placeholders",
]
