"""SQL selectors for claim-boundary audit event candidates."""

from __future__ import annotations

from typing import Any, Optional, Sequence

from yoke_core.domain import db_backend
from yoke_core.domain.check_claim_boundary_audit_cutoff import (
    apply_event_id_cutoff,
)


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def select_unattributed_harness_events(
    conn: Any,
    since: Optional[str],
    *,
    mutating_prefixes: Sequence[str],
) -> list[Any]:
    marker = _p(conn)
    params: list[Any] = ["HarnessToolCallCompleted", "%unattributed%"]
    where = (
        f"event_name={marker} "
        f"AND anomaly_flags LIKE {marker}"
    )
    if since:
        where += f" AND created_at >= {marker}"
        params.append(since)

    preview_clauses: list[str] = []
    for prefix in mutating_prefixes:
        preview_clauses.append(f"envelope LIKE {marker}")
        params.append(f"%{prefix}%")
    where += " AND (" + " OR ".join(preview_clauses) + ")"
    where, params = apply_event_id_cutoff(where, params, marker=marker)
    sql = (
        "SELECT id, session_id, item_id, created_at, envelope, "
        "anomaly_flags, tool_name "
        f"FROM events WHERE {where} ORDER BY id"
    )
    return conn.execute(sql, params).fetchall()


__all__ = ["select_unattributed_harness_events"]
