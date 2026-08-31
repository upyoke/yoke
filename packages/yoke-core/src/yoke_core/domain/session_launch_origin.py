"""Derive ``session_launches.origin`` from live steering authority."""

from __future__ import annotations

from typing import Any

from yoke_contracts.session_control.launch_origin import (
    LAUNCH_ORIGIN_OPERATOR,
    LAUNCH_ORIGIN_STEERING,
)
from yoke_core.domain import db_backend
from yoke_core.domain.work_claim_targets import (
    TARGET_KIND_STEERING,
    make_steering_target,
)


def derived_launch_origin(
    conn: Any,
    *,
    session_id: str | None,
    project_id: int,
) -> str:
    """Return ``steering`` when *session_id* holds that project's steering seat."""
    if not session_id:
        return LAUNCH_ORIGIN_OPERATOR
    target = make_steering_target(int(project_id))
    marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
    row = conn.execute(
        "SELECT 1 FROM work_claims "
        f"WHERE session_id = {marker} AND target_kind = {marker} "
        f"AND scope = {marker} AND released_at IS NULL LIMIT 1",
        (session_id, TARGET_KIND_STEERING, target.scope_json()),
    ).fetchone()
    if row is None:
        return LAUNCH_ORIGIN_OPERATOR
    return LAUNCH_ORIGIN_STEERING


__all__ = ["derived_launch_origin"]
