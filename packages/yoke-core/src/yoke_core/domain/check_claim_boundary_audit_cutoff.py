"""Closed-form residue cutoff + event selection for ``HC-claim-boundary-audit``.

The audit observes historical events on the canonical ledger. After the
writer-side prevention code is deployed, pre-fix rows remain in the
events table forever and would keep the doctor red. The cutoff suppresses
event ids strictly below the configured threshold; rows at or above the
threshold still surface as FAIL / WARN through the existing classification.

The cutoff value is read from machine config key
``hc_claim_boundary_audit_min_event_id``
via :mod:`yoke_core.domain.runtime_settings`. The default ``0`` means
"no cutoff" so a fresh project deploying the HC sees the full audit until
it sets the post-fix value explicitly.

This module also owns ``select_events`` — the single SQL helper the
scanner uses to read events for every finding class — so the cutoff
clause is applied in one place rather than duplicated at each call site.
"""

from __future__ import annotations

from typing import Any, List, Optional

from yoke_core.domain import db_backend
from yoke_core.domain.runtime_settings import get_int


_CONFIG_KEY = "hc_claim_boundary_audit_min_event_id"
_DEFAULT_CUTOFF = 0


def _p(conn) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def read_min_event_id_cutoff() -> int:
    """Return the configured minimum event id, or ``0`` (no cutoff)."""
    value = get_int(_CONFIG_KEY, _DEFAULT_CUTOFF)
    return value if value > 0 else 0


def apply_event_id_cutoff(
    where_clause: str,
    params: list,
    *,
    cutoff: Optional[int] = None,
    marker: str = "?",
) -> tuple[str, list]:
    """Append an ``events.id >= ?`` clause when the cutoff is positive."""
    if cutoff is None:
        cutoff = read_min_event_id_cutoff()
    if cutoff <= 0:
        return where_clause, params
    extended_params = list(params)
    extended_params.append(cutoff)
    return where_clause + f" AND events.id >= {marker}", extended_params


def select_events(
    conn: Any,
    event_name: str,
    since: Optional[str],
) -> List[Any]:
    """Read events for one event_name, honouring the configured cutoff."""
    marker = _p(conn)
    params: list = [event_name]
    where = f"event_name={marker}"
    if since:
        where += f" AND created_at >= {marker}"
        params.append(since)
    where, params = apply_event_id_cutoff(where, params, marker=marker)
    sql = (
        "SELECT id, session_id, item_id, created_at, envelope, "
        "anomaly_flags, tool_name "
        f"FROM events WHERE {where} ORDER BY id"
    )
    return conn.execute(sql, params).fetchall()


__all__ = [
    "apply_event_id_cutoff",
    "read_min_event_id_cutoff",
    "select_events",
]
