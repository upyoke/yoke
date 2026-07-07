"""Correlation helpers for claim-boundary-audit harness preview rows."""

from __future__ import annotations

import json
from typing import Any, Optional

from yoke_core.domain import db_backend


def _coerce_item_id(value: object) -> Optional[int]:
    if value is None:
        return None
    try:
        return int(str(value).replace("YOK-", ""))
    except (TypeError, ValueError):
        return None


def _envelope(raw: object) -> dict:
    if not raw:
        return {}
    try:
        parsed = json.loads(str(raw))
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _json_object_candidates(text: str) -> list[str]:
    lines = text.splitlines()
    candidates = [text.lstrip()] if text.lstrip().startswith("{") else []
    candidates.extend(
        "\n".join(lines[index:]).lstrip()
        for index, line in enumerate(lines)
        if line.lstrip().startswith("{")
    )
    return candidates


def extract_function_response(preview_text: str) -> tuple[str, Optional[int]]:
    """Extract a direct FunctionCallResponse preview, if one is present."""
    decoder = json.JSONDecoder()
    for candidate in _json_object_candidates(preview_text):
        try:
            parsed, _ = decoder.raw_decode(candidate)
        except (TypeError, ValueError):
            continue
        if not isinstance(parsed, dict):
            continue
        if parsed.get("success") is not True:
            continue
        function_name = str(parsed.get("function") or "")
        result = parsed.get("result") if isinstance(parsed.get("result"), dict) else {}
        return function_name, _coerce_item_id(result.get("item_id"))
    return "", None


def has_correlated_function_call(
    conn: Any,
    *,
    harness_row: Any,
    function_name: str,
    item_id: Optional[int],
    id_window: int = 50,
) -> bool:
    """Return true when an adjacent durable function event covers a preview row.

    The harness observer records a best-effort ``HarnessToolCallCompleted``
    preview for shell commands that print a ``FunctionCallResponse``. The
    durable source of truth is the sibling ``YokeFunctionCalled`` event. When
    both rows share session, item, and function within a narrow event-id window,
    the preview row is correlated and should not produce a warning.
    """
    if item_id is None or not function_name:
        return False
    p = "%s" if db_backend.connection_is_postgres(conn) else "?"
    event_id = int(harness_row["id"])
    rows = conn.execute(
        "SELECT envelope FROM events "
        "WHERE event_name='YokeFunctionCalled' "
        f"AND session_id={p} AND item_id={p} AND id BETWEEN {p} AND {p} "
        "ORDER BY id",
        (
            harness_row["session_id"],
            str(item_id),
            event_id - id_window,
            event_id + id_window,
        ),
    ).fetchall()
    for row in rows:
        ctx = _envelope(row["envelope"]).get("context") or {}
        if isinstance(ctx, dict) and str(ctx.get("function") or "") == function_name:
            return True
    return False


__all__ = ["extract_function_response", "has_correlated_function_call"]
