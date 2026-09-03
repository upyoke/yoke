"""Control-plane status lookup for the historical ``YOK-N`` cruft lint.

The lint runs both beside a local Postgres authority and inside an HTTPS
client that cannot open the control plane directly.  Prefer one local query
when that authority exists; otherwise relay the same narrow projection
through the registered items-list read.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from yoke_contracts.public_ref import format_item_ref, parse_public_item_ref
from yoke_core.domain import control_plane_transport, db_backend
from yoke_core.domain.db_helpers import connect


_ITEMS_LIST_FUNCTION_ID = "items.list.run"
_PROJECT_SLUG = "yoke"
_PUBLIC_ITEM_PREFIX = "YOK"


def load_work_item_statuses(
    work_items: Iterable[str],
    *,
    db_path: str | None = None,
) -> dict[str, str]:
    """Return one status for every valid Yoke public item reference.

    Missing rows remain ``unknown``.  A local schema/query mismatch keeps the
    lint's existing best-effort behavior; a refused relay propagates so the
    Doctor executor records an actionable failure instead of a false pass.
    """
    refs = sorted({_normalise_ref(ref) for ref in work_items} - {""})
    statuses = {ref: "unknown" for ref in refs}
    if not refs:
        return statuses

    conn = control_plane_transport.local_connection_or_none(
        lambda: connect(path=db_path)
    )
    if conn is None:
        return _load_over_relay(statuses)
    try:
        return _load_over_connection(conn, statuses)
    except Exception:
        return statuses
    finally:
        try:
            conn.close()
        except Exception:
            pass


def _normalise_ref(value: object) -> str:
    prefix, sequence = parse_public_item_ref(value)
    if prefix != _PUBLIC_ITEM_PREFIX or sequence is None:
        return ""
    return format_item_ref(_PROJECT_SLUG, prefix, sequence)


def _load_over_connection(
    conn: Any,
    statuses: dict[str, str],
) -> dict[str, str]:
    sequences = [
        sequence
        for ref in statuses
        for prefix, sequence in [parse_public_item_ref(ref)]
        if prefix == _PUBLIC_ITEM_PREFIX and sequence is not None
    ]
    marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
    placeholders = ",".join(marker for _ in sequences)
    rows = conn.execute(
        f"""SELECT i.project_sequence, i.status
            FROM items i
            JOIN projects p ON p.id = i.project_id
            WHERE UPPER(p.public_item_prefix) = {marker}
              AND i.project_sequence IN ({placeholders})""",
        (_PUBLIC_ITEM_PREFIX, *sequences),
    ).fetchall()
    for row in rows:
        sequence = _row_value(row, "project_sequence", 0)
        status = _row_value(row, "status", 1)
        ref = format_item_ref(_PROJECT_SLUG, _PUBLIC_ITEM_PREFIX, sequence)
        if ref in statuses:
            statuses[ref] = str(status or "unknown")
    return statuses


def _load_over_relay(statuses: dict[str, str]) -> dict[str, str]:
    result = control_plane_transport.relay(
        _ITEMS_LIST_FUNCTION_ID,
        {
            "project": _PROJECT_SLUG,
            "fields": ["id", "status"],
        },
    )
    for row in result.get("rows") or []:
        if not isinstance(row, dict):
            continue
        ref = _normalise_ref(row.get("id"))
        if ref in statuses:
            statuses[ref] = str(row.get("status") or "unknown")
    return statuses


def _row_value(row: Any, name: str, index: int) -> Any:
    if hasattr(row, "keys"):
        return row[name]
    return row[index]


__all__ = ["load_work_item_statuses"]
