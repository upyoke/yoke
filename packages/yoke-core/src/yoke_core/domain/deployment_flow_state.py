"""Lifecycle state and history-safety rules for deployment flows."""

from __future__ import annotations

from typing import Any

from yoke_core.domain import db_backend


FLOW_STATUS_ACTIVE = "active"
FLOW_STATUS_DISABLED = "disabled"
FLOW_STATUSES = frozenset({FLOW_STATUS_ACTIVE, FLOW_STATUS_DISABLED})


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def require_flow_for_new_run(
    conn: Any,
    flow_id: str,
    *,
    project_id: int | None = None,
) -> tuple[int, str]:
    """Return project and target env when a flow accepts new runs."""
    p = _p(conn)
    row = conn.execute(
        "SELECT project_id, COALESCE(status, 'active'), "
        "COALESCE(target_env, '') FROM deployment_flows "
        f"WHERE id = {p}",
        (flow_id,),
    ).fetchone()
    if row is None:
        raise LookupError(f"deployment flow '{flow_id}' not found")
    flow_project_id = int(row[0])
    status = str(row[1] or FLOW_STATUS_ACTIVE)
    target_env = str(row[2] or "")
    if project_id is not None and flow_project_id != project_id:
        raise ValueError(
            f"deployment flow '{flow_id}' belongs to another project"
        )
    if status != FLOW_STATUS_ACTIVE:
        raise ValueError(
            f"deployment flow '{flow_id}' is {status} and cannot start new runs"
        )
    return flow_project_id, target_env


def assert_flow_definition_mutable(conn: Any, flow_id: str) -> None:
    """Refuse edits that would reinterpret an existing run's history."""
    p = _p(conn)
    try:
        row = conn.execute(
            f"SELECT COUNT(*) FROM deployment_runs WHERE flow = {p}",
            (flow_id,),
        ).fetchone()
    except db_backend.operational_error_types(conn):
        return
    run_count = int(row[0] or 0) if row is not None else 0
    if run_count:
        raise ValueError(
            f"deployment flow '{flow_id}' has {run_count} historical run(s); "
            "disable it and create a new flow instead of changing its definition"
        )


def validate_flow_status(status: str) -> str:
    normalized = str(status or "").strip().lower()
    if normalized not in FLOW_STATUSES:
        raise ValueError(
            f"invalid deployment flow status {status!r}; "
            f"choose one of: {', '.join(sorted(FLOW_STATUSES))}"
        )
    return normalized


__all__ = [
    "FLOW_STATUS_ACTIVE",
    "FLOW_STATUS_DISABLED",
    "FLOW_STATUSES",
    "assert_flow_definition_mutable",
    "require_flow_for_new_run",
    "validate_flow_status",
]
