"""Derive ``session_launches.origin`` from live steering authority.

Any live steering seat in the project is steering authority, whether it
covers the whole project or one strategy document inside it. Matching one
exact scope object here would have recorded a document seat's launches as
operator launches.
"""

from __future__ import annotations

from typing import Any

from yoke_contracts.session_control.launch_origin import (
    LAUNCH_ORIGIN_OPERATOR,
    LAUNCH_ORIGIN_STEERING,
)
from yoke_core.domain import db_backend
from yoke_core.domain.work_claim_target_sql import scope_int_sql
from yoke_core.domain.work_claim_targets import TARGET_KIND_STEERING


def derived_launch_origin(
    conn: Any,
    *,
    session_id: str | None,
    project_id: int,
) -> str:
    """Return ``steering`` when *session_id* holds a seat in this project."""
    if not session_id:
        return LAUNCH_ORIGIN_OPERATOR
    marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
    project_scope = scope_int_sql(conn, "scope", "project_id")
    row = conn.execute(
        "SELECT 1 FROM work_claims "
        f"WHERE session_id = {marker} AND target_kind = {marker} "
        f"AND {project_scope} = {marker} AND released_at IS NULL LIMIT 1",
        (session_id, TARGET_KIND_STEERING, int(project_id)),
    ).fetchone()
    if row is None:
        return LAUNCH_ORIGIN_OPERATOR
    return LAUNCH_ORIGIN_STEERING


__all__ = ["derived_launch_origin"]
