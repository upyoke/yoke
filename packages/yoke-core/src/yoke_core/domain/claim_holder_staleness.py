"""Persisted work claims keep their session holder authoritative.

Silence, parking, and a missing native process do not release a work claim.
Only an explicit terminal action or claim release changes ownership. Readers
and reclaim paths use this rule so a restart does not open a claim to a
second worker before its owner can reattach.
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping

from yoke_core.domain import db_backend
from yoke_core.domain.schema_common import _get_columns

#: What :func:`holder_claim_is_stale` reads off a holder's session row. The
#: process observation needs its own evidence plus the activity that could
#: supersede it, so the set is wider than mode and ``ended_at``.
HOLDER_SESSION_COLUMNS = ("session_id", "ended_at")


def holder_claim_is_stale(
    row: Mapping[str, Any],
    *,
    inactivity_stale: bool,
) -> bool:
    """Whether this holder's claim reads reclaimable to another viewer.

    A live session's active claim cannot be reclaimed for inactivity.
    """
    if row.get("ended_at") is not None:
        return True
    return False


def protected_claim_holders(
    conn: Any,
    session_ids: Iterable[Any],
) -> frozenset[str]:
    """Live holders whose persisted claims survive inactivity and process exit."""
    wanted = sorted({str(value) for value in session_ids if value})
    if not wanted:
        return frozenset()
    try:
        available = set(_get_columns(conn, "harness_sessions"))
    except db_backend.operational_error_types(conn):
        _rollback(conn)
        return frozenset()
    columns = [name for name in HOLDER_SESSION_COLUMNS if name in available]
    if "session_id" not in columns or "ended_at" not in columns:
        return frozenset()
    marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
    placeholders = ", ".join(marker for _ in wanted)
    try:
        rows = conn.execute(
            f"SELECT {', '.join(columns)} FROM harness_sessions "
            f"WHERE session_id IN ({placeholders})",
            tuple(wanted),
        ).fetchall()
    except db_backend.operational_error_types(conn):
        _rollback(conn)
        return frozenset()
    exempt = set()
    for row in rows:
        record = _record(row, columns)
        if holder_claim_is_stale(record, inactivity_stale=True):
            continue
        holder = str(record.get("session_id") or "")
        if holder:
            exempt.add(holder)
    return frozenset(exempt)


def _record(row: Any, columns: list[str]) -> dict[str, Any]:
    """One holder row as a mapping, whatever row shape the engine returns."""
    if hasattr(row, "keys"):
        return {name: row[name] for name in columns}
    return dict(zip(columns, tuple(row)))


def _rollback(conn: Any) -> None:
    if db_backend.connection_is_postgres(conn):
        try:
            conn.rollback()
        except Exception:
            pass


__all__ = [
    "HOLDER_SESSION_COLUMNS",
    "holder_claim_is_stale",
    "protected_claim_holders",
]
