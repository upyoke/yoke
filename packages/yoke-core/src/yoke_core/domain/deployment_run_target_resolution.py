"""Resolve a deployment run's typed target before creation.

One question, answered once: which tier and which registered environment
does a run of this flow deploy to? Copies the flow's registered target by
default; an operator override names another of the project's environments
and forces the persistent tier.
"""

from __future__ import annotations

from typing import Optional

from yoke_core.domain.db_helpers import connect, query_one
from yoke_core.domain.project_identity import resolve_project


def cmd_resolve_target(
    project: str,
    flow: str,
    environment_override: Optional[str] = None,
    db_path: Optional[str] = None,
) -> tuple[str, int | None, str]:
    """Resolve an internal key plus the operator-facing environment name."""
    from yoke_core.domain.environment_delivery_record import (
        environment_name,
        require_registered_environment,
    )

    conn = connect(db_path)
    try:
        ident = resolve_project(conn, project)
        assert ident is not None
        if environment_override:
            environment_id = require_registered_environment(
                conn, ident.id, environment_override,
            )
            return (
                "persistent",
                environment_id,
                environment_name(conn, environment_id) or "",
            )
        row = query_one(
            conn,
            "SELECT COALESCE(target_tier, '') AS target_tier, "
            "target_environment_id "
            "FROM deployment_flows WHERE id=%s AND project_id=%s",
            (flow, ident.id),
        )
        if row is None:
            return "", None, ""
        tier = str(row["target_tier"] if hasattr(row, "keys") else row[0])
        raw_environment_id = (
            row["target_environment_id"] if hasattr(row, "keys") else row[1]
        )
        environment_id = (
            int(raw_environment_id) if raw_environment_id not in (None, "") else None
        )
        return (
            tier,
            environment_id,
            environment_name(conn, environment_id) or "",
        )
    finally:
        conn.close()


__all__ = ["cmd_resolve_target"]
