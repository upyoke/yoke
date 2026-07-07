"""Listing / liveness diagnostics for ``coordination_leases``.

Sibling of :mod:`yoke_core.domain.coordination_leases`. Owns read helpers
that doctor / operator / board consumers use to inspect active, released,
and stale-candidate leases without dropping to raw SQL. Pure reads; no
mutation, no auto-release.
"""

from __future__ import annotations

from typing import Any, List, Optional, Union

from yoke_core.domain import db_backend
from yoke_core.domain.coordination_leases import (
    Lease,
    SELECT_COLUMNS,
    row_to_lease,
)
from yoke_core.domain.project_identity import resolve_project_id


def list_leases(
    conn: Any,
    *,
    project_id: Optional[Union[str, int]] = None,
    lease_key: Optional[str] = None,
    session_id: Optional[str] = None,
    active_only: bool = False,
) -> List[Lease]:
    """Read helper for inspecting leases without raw SQL.

    Filters compose with AND. ``active_only`` restricts to non-released rows
    (``released_at IS NULL``) — the same predicate doctor and the BOARD
    Claims column use when rendering live ownership.
    """
    p = "%s" if db_backend.connection_is_postgres(conn) else "?"
    where: List[str] = []
    params: List[Any] = []
    if project_id is not None:
        where.append(f"project_id = {p}")
        params.append(resolve_project_id(conn, project_id))
    if lease_key is not None:
        where.append(f"lease_key = {p}")
        params.append(lease_key)
    if session_id is not None:
        where.append(f"session_id = {p}")
        params.append(session_id)
    if active_only:
        where.append("released_at IS NULL")
    sql = f"SELECT {SELECT_COLUMNS} FROM coordination_leases"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY acquired_at DESC, id DESC"
    rows = conn.execute(sql, tuple(params)).fetchall()
    return [row_to_lease(row) for row in rows]


def stale_lease_candidates(
    conn: Any,
    *,
    threshold_iso: str,
    project_id: Optional[Union[str, int]] = None,
) -> List[Lease]:
    """Return active leases whose ``heartbeat_at`` is older than ``threshold_iso``.

    Pure diagnostic surface — no auto-release. Doctor consumes this and
    surfaces recovery candidates; operators recover via
    :func:`yoke_core.domain.coordination_leases.operator_release`.
    """
    p = "%s" if db_backend.connection_is_postgres(conn) else "?"
    sql = (
        f"SELECT {SELECT_COLUMNS} FROM coordination_leases "
        "WHERE released_at IS NULL "
        f"AND (heartbeat_at IS NULL OR heartbeat_at < {p})"
    )
    params: List[Any] = [threshold_iso]
    if project_id is not None:
        sql += f" AND project_id = {p}"
        params.append(resolve_project_id(conn, project_id))
    sql += " ORDER BY heartbeat_at ASC, id ASC"
    rows = conn.execute(sql, tuple(params)).fetchall()
    return [row_to_lease(row) for row in rows]


__all__ = ["list_leases", "stale_lease_candidates"]
