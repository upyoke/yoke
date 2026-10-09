"""Rollout-tolerant deployment-run insertion."""

from __future__ import annotations

from typing import Any
from datetime import datetime
from yoke_contracts.timestamps import parse_instant
from yoke_core.domain.db_helpers import instant_parameter

from yoke_core.domain.schema_common import _column_exists


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
    """Insert through both legacy and additively converged run schemas."""
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
    has_artifact_identity = _column_exists(conn, "deployment_runs", "artifact_identity")
    if artifact_identity and not has_artifact_identity:
        raise RuntimeError(
            "deployment_runs.artifact_identity has not converged; apply the "
            "current additive schema before creating an artifact-bound run"
        )
    if has_artifact_identity:
        columns.append("artifact_identity")
        values.append(artifact_identity or None)
    if create_idempotency_key:
        # The create decides the key basis under its lock and passes a key only
        # once the columns converged, so absence here is a caller that skipped
        # that decision.
        if not _column_exists(conn, "deployment_runs", "create_idempotency_key"):
            raise RuntimeError(
                "deployment_runs.create_idempotency_key has not converged; "
                "apply the current additive schema before creating a keyed run"
            )
        columns += ["create_idempotency_key", "create_request"]
        values += [create_idempotency_key, create_request]
    placeholders = ", ".join(["%s"] * len(columns))
    return conn.execute(
        f"INSERT INTO deployment_runs ({', '.join(columns)}) "
        f"VALUES ({placeholders}) ON CONFLICT (id) DO NOTHING RETURNING id",
        tuple(values),
    ).fetchone()
