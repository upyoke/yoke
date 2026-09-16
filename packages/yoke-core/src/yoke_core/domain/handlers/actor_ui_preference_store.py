"""Shared read/write helpers for actor-scoped workbench preferences.

Every remembered workbench choice — a screen's project selection, a nav
group's open state — is one row in ``actor_ui_preferences`` keyed by a
namespaced ``pref_key``. The storage, the actor resolution, and the
"no resolved actor" contract are identical across those surfaces, so they
live here once: a list read degrades to empty without a bound actor, and a
write refuses by name rather than writing a row nobody owns.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Optional

from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionError,
    HandlerOutcome,
)

from yoke_core.domain import json_helper

#: A preference key segment: a short lowercase slug, the shape both a NAV
#: entry id and a nav group id already have. Validated by shape rather than
#: by duplicating either roster server-side.
KEY_SEGMENT_RE = re.compile(r"^[a-z][a-z0-9-]{0,63}$")


def error(
    code: str,
    message: str,
    *,
    jsonpath: Optional[str] = None,
) -> HandlerOutcome:
    return HandlerOutcome(
        primary_success=False,
        error=FunctionError(code=code, message=message, jsonpath=jsonpath),
    )


def require_global(
    request: FunctionCallRequest,
    function_id: str,
) -> Optional[HandlerOutcome]:
    if request.target.kind != "global":
        return error(
            "target_invalid",
            f"{function_id} requires target.kind='global'",
            jsonpath="$.target.kind",
        )
    return None


def actor_id(request: FunctionCallRequest) -> Optional[int]:
    raw = (request.actor.actor_id or "").strip()
    return int(raw) if raw.isdigit() else None


def actor_required(function_id: str) -> HandlerOutcome:
    return error(
        "actor_required",
        f"{function_id} writes a per-actor preference and needs a bound "
        "actor; this caller has none",
    )


def read_prefixed(resolved_actor_id: int, prefix: str) -> Dict[str, Any]:
    """Every stored value under ``prefix``, keyed by the segment after it.

    A row whose value is not readable JSON is skipped rather than failing
    the whole read: one unreadable preference must not cost an operator
    every other choice they saved.
    """
    from yoke_core.domain import db_helpers

    conn = db_helpers.connect()
    try:
        rows = conn.execute(
            "SELECT pref_key, value FROM actor_ui_preferences "
            "WHERE actor_id = %s AND pref_key LIKE %s",
            (resolved_actor_id, prefix + "%"),
        ).fetchall()
    finally:
        conn.close()
    values: Dict[str, Any] = {}
    for row in rows:
        key = str(row[0])[len(prefix) :]
        try:
            values[key] = json_helper.loads_text(row[1])
        except ValueError:
            continue
    return values


def upsert(resolved_actor_id: int, pref_key: str, value: Any) -> None:
    from yoke_core.domain import db_helpers

    conn = db_helpers.connect()
    try:
        conn.execute(
            "INSERT INTO actor_ui_preferences "
            "(actor_id, pref_key, value, updated_at) "
            "VALUES (%s, %s, %s, %s) "
            "ON CONFLICT (actor_id, pref_key) DO UPDATE SET "
            "value = EXCLUDED.value, updated_at = EXCLUDED.updated_at",
            (
                resolved_actor_id,
                pref_key,
                json_helper.dumps_compact(value),
                db_helpers.iso8601_now(),
            ),
        )
        conn.commit()
    finally:
        conn.close()


__all__ = [
    "KEY_SEGMENT_RE",
    "actor_id",
    "actor_required",
    "error",
    "read_prefixed",
    "require_global",
    "upsert",
]
