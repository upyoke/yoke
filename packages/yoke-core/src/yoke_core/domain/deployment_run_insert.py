"""Deployment-run insertion with artifact and request identity."""

from __future__ import annotations

from typing import Any
from datetime import datetime
from yoke_contracts.timestamps import parse_instant
from yoke_core.domain.db_helpers import instant_parameter


def insert_run(
    conn: Any,
    *,
    run_id: str,
    project_id: int,
    flow: str,
    target_tier: str | None,
    target_environment_id: int | None,
    release_lineage: str | None,
    created_by: str,
    created_at: datetime | str,
    artifact_identity: str | None,
    create_idempotency_key: str | None = None,
    create_request: str | None = None,
) -> Any:
    """Insert a run and its immutable creation identity."""
    stamp = parse_instant(created_at)
    columns = [
        "id",
        "project_id",
        "flow",
        "target_tier",
        "target_environment_id",
        "release_lineage",
        "created_by",
        "created_at",
    ]
    values: list[Any] = [
        run_id,
        project_id,
        flow,
        target_tier or None,
        target_environment_id or None,
        release_lineage or None,
        created_by,
        instant_parameter(conn, stamp),
    ]
    columns += ["artifact_identity", "create_idempotency_key", "create_request"]
    values += [artifact_identity or None, create_idempotency_key, create_request]
    placeholders = ", ".join(["%s"] * len(columns))
    return conn.execute(
        f"INSERT INTO deployment_runs ({', '.join(columns)}) "
        f"VALUES ({placeholders}) ON CONFLICT (id) DO NOTHING RETURNING id",
        tuple(values),
    ).fetchone()
