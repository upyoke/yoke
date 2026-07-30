"""Faithful, idempotent projection of deployment-run authority snapshots."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping

from yoke_core.domain.db_helpers import connect
from yoke_core.domain.deployment_runs_schema import RUN_FIELDS, VALID_STATUSES
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
    normalized = {
        field: (
            None
            if raw[field] is None or raw[field] == ""
            else str(raw[field]).strip()
        )
        for field in RUN_FIELDS
    }
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
    row = conn.execute(
        "SELECT dr.id,p.slug AS project,dr.flow,dr.target_env,"
        "dr.release_lineage,dr.status,dr.current_stage,dr.created_at,"
        "dr.started_at,dr.completed_at,dr.created_by "
        "FROM deployment_runs dr JOIN projects p ON p.id=dr.project_id "
        "WHERE dr.id=%s FOR UPDATE",
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
        existing = _locked_existing(authority, str(snapshot["id"]))
        if existing == snapshot:
            outcome = "unchanged"
            changed: list[str] = []
        elif existing is None:
            authority.execute(
                "INSERT INTO deployment_runs("
                "id,project_id,flow,target_env,release_lineage,status,"
                "current_stage,created_at,started_at,completed_at,created_by"
                ") VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (
                    snapshot["id"], project_id, snapshot["flow"],
                    snapshot["target_env"], snapshot["release_lineage"],
                    snapshot["status"], snapshot["current_stage"],
                    snapshot["created_at"], snapshot["started_at"],
                    snapshot["completed_at"], snapshot["created_by"],
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
                "UPDATE deployment_runs SET target_env=%s,status=%s,"
                "current_stage=%s,created_at=%s,started_at=%s,completed_at=%s,"
                "created_by=%s WHERE id=%s",
                (
                    snapshot["target_env"], snapshot["status"],
                    snapshot["current_stage"], snapshot["created_at"],
                    snapshot["started_at"], snapshot["completed_at"],
                    snapshot["created_by"], snapshot["id"],
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
