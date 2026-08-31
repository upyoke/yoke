"""Faithful, idempotent projection of deployment-run authority snapshots."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping

from yoke_core.domain.db_helpers import connect
from yoke_core.domain.deployment_run_carried_work import parse_carried_work
from yoke_core.domain.deployment_runs_schema import (
    RUN_FIELDS,
    VALID_STATUSES,
    _run_named_columns,
)
from yoke_core.domain.json_helper import dumps_compact
from yoke_core.domain.project_identity import resolve_project


class DeploymentRunProjectionError(ValueError):
    """A deployment-run snapshot cannot be projected safely."""


class DeploymentRunProjectionCollision(DeploymentRunProjectionError):
    """Destination state conflicts with the supplied projection authority."""


def normalize_snapshot(raw: Mapping[str, Any]) -> dict[str, str | None]:
    """Validate one canonical portable deployment-run row."""
    if set(raw) != set(RUN_FIELDS):
        raise DeploymentRunProjectionError(
            "snapshot must contain exactly the canonical deployment-run fields"
        )
    normalized: dict[str, str | None] = {}
    for field in RUN_FIELDS:
        value = raw[field]
        if value is None or value == "":
            normalized[field] = None
        elif field == "carried_work":
            parsed = parse_carried_work(value)
            if parsed is None:
                raise DeploymentRunProjectionError(
                    "snapshot carried_work must be a JSON object"
                )
            normalized[field] = dumps_compact(parsed)
        else:
            normalized[field] = str(value).strip()
    for required in ("id", "project", "flow", "status", "created_at"):
        if not normalized[required]:
            raise DeploymentRunProjectionError(
                f"snapshot field {required!r} must be non-empty"
            )
    if normalized["status"] not in VALID_STATUSES:
        raise DeploymentRunProjectionError("snapshot status is not registered")
    return normalized


def snapshot_digest(snapshot: Mapping[str, Any]) -> str:
    """Return the stable digest used for optimistic destination repair."""
    normalized = normalize_snapshot(snapshot)
    encoded = json.dumps(
        normalized,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def _row_snapshot(row: Any) -> dict[str, str | None]:
    return normalize_snapshot(
        {
            field: (row[field] if hasattr(row, "keys") else row[index])
            for index, field in enumerate(RUN_FIELDS)
        }
    )


def _locked_existing(conn: Any, run_id: str) -> dict[str, str | None] | None:
    columns, env_join = _run_named_columns(conn)
    row = conn.execute(
        f"SELECT {columns} "
        "FROM deployment_runs dr JOIN projects p ON p.id=dr.project_id "
        f"{env_join} "
        "WHERE dr.id=%s FOR UPDATE OF dr",
        (run_id,),
    ).fetchone()
    return None if row is None else _row_snapshot(row)


def _project_and_flow(conn: Any, snapshot: Mapping[str, Any]) -> int:
    project = resolve_project(conn, str(snapshot["project"]), required=True)
    row = conn.execute(
        "SELECT project_id FROM deployment_flows WHERE id=%s FOR UPDATE",
        (snapshot["flow"],),
    ).fetchone()
    if row is None:
        raise DeploymentRunProjectionError(
            f"deployment flow {snapshot['flow']!r} is absent"
        )
    flow_project_id = int(row["project_id"] if hasattr(row, "keys") else row[0])
    if flow_project_id != project.id:
        raise DeploymentRunProjectionError(
            "deployment flow does not belong to the snapshot project"
        )
    return project.id


def _target_environment_id(
    conn: Any,
    *,
    project_id: int,
    environment: str | None,
) -> int | None:
    if environment is None:
        return None
    from yoke_core.domain.environment_reference import resolve

    return resolve(conn, project_id=project_id, name=environment).id


def _changed_fields(
    before: Mapping[str, Any],
    after: Mapping[str, Any],
) -> list[str]:
    return [field for field in RUN_FIELDS if before[field] != after[field]]


def project_snapshot(
    raw_snapshot: Mapping[str, Any],
    *,
    expected_destination_digest: str | None = None,
    conn: Any | None = None,
) -> dict[str, Any]:
    """Insert, replay, or CAS-repair one canonical deployment-run snapshot."""
    snapshot = normalize_snapshot(raw_snapshot)
    owns_connection = conn is None
    authority = connect() if conn is None else conn
    try:
        project_id = _project_and_flow(authority, snapshot)
        target_environment_id = _target_environment_id(
            authority,
            project_id=project_id,
            environment=snapshot["target_environment"],
        )
        existing = _locked_existing(authority, str(snapshot["id"]))
        if existing == snapshot:
            outcome = "unchanged"
            changed: list[str] = []
        elif existing is None:
            authority.execute(
                "INSERT INTO deployment_runs("
                "id,project_id,flow,target_tier,target_environment_id,"
                "release_lineage,status,"
                "current_stage,created_at,started_at,completed_at,created_by,"
                "carried_work) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (
                    snapshot["id"],
                    project_id,
                    snapshot["flow"],
                    snapshot["target_tier"],
                    target_environment_id,
                    snapshot["release_lineage"],
                    snapshot["status"],
                    snapshot["current_stage"],
                    snapshot["created_at"],
                    snapshot["started_at"],
                    snapshot["completed_at"],
                    snapshot["created_by"],
                    snapshot["carried_work"],
                ),
            )
            outcome = "created"
            changed = list(RUN_FIELDS)
        else:
            for field in ("project", "flow", "release_lineage"):
                if existing[field] != snapshot[field]:
                    raise DeploymentRunProjectionCollision(
                        f"deployment run projection collides on {field}"
                    )
            current_digest = snapshot_digest(existing)
            if expected_destination_digest != current_digest:
                raise DeploymentRunProjectionCollision(
                    "deployment run projection requires the current "
                    "destination snapshot digest"
                )
            changed = _changed_fields(existing, snapshot)
            authority.execute(
                "UPDATE deployment_runs SET target_tier=%s,"
                "target_environment_id=%s,status=%s,"
                "current_stage=%s,created_at=%s,started_at=%s,completed_at=%s,"
                "created_by=%s,carried_work=%s WHERE id=%s",
                (
                    snapshot["target_tier"],
                    target_environment_id,
                    snapshot["status"],
                    snapshot["current_stage"],
                    snapshot["created_at"],
                    snapshot["started_at"],
                    snapshot["completed_at"],
                    snapshot["created_by"],
                    snapshot["carried_work"],
                    snapshot["id"],
                ),
            )
            outcome = "updated"
        authority.commit()
        return {
            "run_id": snapshot["id"],
            "outcome": outcome,
            "snapshot_digest": snapshot_digest(snapshot),
            "changed_fields": changed,
        }
    except Exception:
        authority.rollback()
        raise
    finally:
        if owns_connection:
            authority.close()


__all__ = [
    "DeploymentRunProjectionCollision",
    "DeploymentRunProjectionError",
    "normalize_snapshot",
    "project_snapshot",
    "snapshot_digest",
]
