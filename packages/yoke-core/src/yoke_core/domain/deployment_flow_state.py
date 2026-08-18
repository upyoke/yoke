"""Lifecycle state and history-safety rules for deployment flows."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from yoke_core.domain import db_backend
from yoke_core.domain.deployment_run_target_resolution import (
    coerce_target_environment_id,
)
from yoke_core.domain.schema_common import _table_exists


FLOW_STATUS_ACTIVE = "active"
FLOW_STATUS_DISABLED = "disabled"
FLOW_STATUSES = frozenset({FLOW_STATUS_ACTIVE, FLOW_STATUS_DISABLED})


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def lock_deployment_flow_rows(
    conn: Any,
    flow_ids: Iterable[str],
    *,
    binding: bool,
) -> dict[str, tuple[int, str, str, int | None]]:
    """Lock flow rows in stable order for definitions or new references."""
    normalized = tuple(sorted({str(flow_id) for flow_id in flow_ids}))
    if not normalized:
        return {}
    suffix = ""
    if db_backend.connection_is_postgres(conn):
        suffix = " FOR SHARE" if binding else " FOR UPDATE"
    rows: dict[str, tuple[int, str, str, int | None]] = {}
    for flow_id in normalized:
        row = conn.execute(
            "SELECT id, project_id, status, "
            "COALESCE(target_tier, '') AS target_tier, "
            "target_environment_id "
            f"FROM deployment_flows WHERE id = {_p(conn)}{suffix}",
            (flow_id,),
        ).fetchone()
        if row is None:
            continue
        row_id = str(row["id"] if hasattr(row, "keys") else row[0])
        rows[row_id] = (
            int(row["project_id"] if hasattr(row, "keys") else row[1]),
            str(row["status"] if hasattr(row, "keys") else row[2]),
            str((row["target_tier"] if hasattr(row, "keys") else row[3]) or ""),
            coerce_target_environment_id(
                row["target_environment_id"] if hasattr(row, "keys") else row[4]
            ),
        )
    return rows


def require_flow_for_new_run(
    conn: Any,
    flow_id: str,
    *,
    project_id: int | None = None,
) -> tuple[int, str, int | None]:
    """Return project, tier, and environment when a flow accepts new runs."""
    row = lock_deployment_flow_rows(conn, (flow_id,), binding=True).get(flow_id)
    if row is None:
        raise LookupError(f"deployment flow '{flow_id}' not found")
    flow_project_id, status, target_tier, target_environment_id = row
    if project_id is not None and flow_project_id != project_id:
        raise ValueError(f"deployment flow '{flow_id}' belongs to another project")
    if status != FLOW_STATUS_ACTIVE:
        raise ValueError(
            f"deployment flow '{flow_id}' is {status} and cannot start new runs"
        )
    return flow_project_id, target_tier, target_environment_id


def assert_flow_definition_mutable(conn: Any, flow_id: str) -> None:
    """Refuse edits that would reinterpret an existing run's history."""
    p = _p(conn)
    if not _table_exists(conn, "deployment_runs"):
        return
    row = conn.execute(
        f"SELECT COUNT(*) FROM deployment_runs WHERE flow = {p}",
        (flow_id,),
    ).fetchone()
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
    "lock_deployment_flow_rows",
    "require_flow_for_new_run",
    "validate_flow_status",
]
