"""Control-plane status lookup for the historical ``YOK-N`` cruft lint.

The lint runs both beside a local Postgres authority and inside an HTTPS
client that cannot open the control plane directly.  Prefer one local query
when that authority exists; otherwise relay the same narrow projection
through the registered items-list read.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from yoke_core.domain.workflow_status_queries import terminal_items_sql
from yoke_contracts.lifecycle_status import workflow_status_metadata_refusal
from typing import Any

from yoke_contracts.public_ref import format_item_ref, parse_public_item_ref
from yoke_core.domain import control_plane_transport, db_backend
from yoke_core.domain.db_helpers import connect


@dataclass(frozen=True)
class WorkItemStatus:
    status: str
    terminal: bool


_ITEMS_LIST_FUNCTION_ID = "items.list.run"
_PROJECT_SLUG = "yoke"
_PUBLIC_ITEM_PREFIX = "YOK"


def load_work_item_statuses(
    work_items: Iterable[str],
    *,
    db_path: str | None = None,
) -> dict[str, WorkItemStatus]:
    """Return one status for every valid Yoke public item reference.

    Missing rows remain ``unknown``.  A local schema/query mismatch keeps the
    lint's existing best-effort behavior; a refused relay propagates so the
    Doctor executor records an actionable failure instead of a false pass.
    """
    refs = sorted({_normalise_ref(ref) for ref in work_items} - {""})
    statuses = {ref: WorkItemStatus("unknown", False) for ref in refs}
    if not refs:
        return statuses

    conn = control_plane_transport.local_connection_or_none(
        lambda: connect(path=db_path)
    )
    if conn is None:
        return _load_over_relay(statuses)
    try:
        return _load_over_connection(conn, statuses)
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
    statuses: dict[str, WorkItemStatus],
) -> dict[str, WorkItemStatus]:
    from yoke_core.domain.schema_common import _table_exists

    if not _table_exists(conn, "items"):
        return statuses
    sequences = [
        sequence
        for ref in statuses
        for prefix, sequence in [parse_public_item_ref(ref)]
        if prefix == _PUBLIC_ITEM_PREFIX and sequence is not None
    ]
    marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
    placeholders = ",".join(marker for _ in sequences)
    rows = conn.execute(
        f"""SELECT i.project_sequence, i.status, {terminal_items_sql(conn)} AS terminal
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
            statuses[ref] = WorkItemStatus(
                str(status or "unknown"), bool(_row_value(row, "terminal", 2))
            )
    return statuses


def _load_over_relay(statuses: dict[str, WorkItemStatus]) -> dict[str, WorkItemStatus]:
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
            if "terminal" not in row:
                raise ValueError(workflow_status_metadata_refusal())
            statuses[ref] = WorkItemStatus(
                str(row.get("status") or "unknown"), bool(row["terminal"])
            )
    return statuses


def _row_value(row: Any, name: str, index: int) -> Any:
    if hasattr(row, "keys"):
        return row[name]
    return row[index]


__all__ = ["load_work_item_statuses"]
