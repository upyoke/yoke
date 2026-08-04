"""Shared outbound enrichment: pair bare ``item_id`` with ``item_ref``.

Agent-facing function-call results historically returned the internal
``items.id`` alone. When that number drifts from the public
``{prefix}-{project_sequence}`` ref, callers treat the envelope as naming
the wrong item. ``items.create`` already returns both fields; this module
extends that convention at the dispatcher envelope layer so handlers do
not assemble refs themselves.

DB rows, events, telemetry, and test assertions keep bare integer
``item_id`` — only the result envelope is enriched.
"""

from __future__ import annotations

from typing import Any, Mapping, MutableMapping, Optional

# Top-level result keys whose integer (or numeric-string) value is an
# internal items.id that should gain a sibling public-ref field.
_ID_TO_REF_KEYS: tuple[tuple[str, str], ...] = (
    ("item_id", "item_ref"),
    ("current_item_id", "current_item_ref"),
    ("recent_item_id", "recent_item_ref"),
)


def _coerce_internal_item_id(raw: Any) -> Optional[int]:
    """Return an internal id when ``raw`` is clearly numeric; else None.

    String public refs (``YOK-2008``) and other non-numeric tokens are left
    alone — those surfaces already carry display identity.
    """
    if raw is None or isinstance(raw, bool):
        return None
    if isinstance(raw, int):
        return raw if raw > 0 else None
    if isinstance(raw, str):
        text = raw.strip()
        if text.isdigit():
            value = int(text)
            return value if value > 0 else None
    return None


def _render_ref(conn: Any, item_id: int) -> Optional[str]:
    from yoke_core.domain.project_identity import render_item_ref

    try:
        return render_item_ref(conn, item_id, required=False)
    except Exception:
        return None


def _enrich_mapping(payload: MutableMapping[str, Any], conn: Any) -> None:
    for id_key, ref_key in _ID_TO_REF_KEYS:
        if ref_key in payload and payload.get(ref_key):
            continue
        item_id = _coerce_internal_item_id(payload.get(id_key))
        if item_id is None:
            continue
        rendered = _render_ref(conn, item_id)
        if rendered:
            payload[ref_key] = rendered


def enrich_result_item_refs(
    result: Mapping[str, Any] | None,
    *,
    conn: Any = None,
) -> dict[str, Any]:
    """Return a shallow copy of ``result`` with public refs beside bare ids.

    Enriches the top-level mapping and one nested level (e.g. a ``session``
    object that carries ``current_item_id``). Opens a short-lived control-plane
    connection when ``conn`` is omitted. On connection or lookup failure the
    original fields are preserved unchanged — never invent a wrong ref.
    """
    if not result:
        return {}
    out: dict[str, Any] = dict(result)

    owns_conn = False
    active = conn
    if active is None:
        try:
            from yoke_core.domain import db_helpers

            active = db_helpers.connect()
            owns_conn = True
        except Exception:
            return out
    try:
        _enrich_mapping(out, active)
        for key, value in list(out.items()):
            if isinstance(value, dict):
                nested = dict(value)
                _enrich_mapping(nested, active)
                out[key] = nested
    finally:
        if owns_conn and active is not None:
            try:
                active.close()
            except Exception:
                pass
    return out
