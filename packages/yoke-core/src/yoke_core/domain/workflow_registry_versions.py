"""Read and select immutable workflow versions."""

from __future__ import annotations

from typing import Any, Optional

from yoke_core.domain import db_backend
from yoke_core.domain.db_helpers import iso8601_now
from yoke_core.domain.workflow_definition_codec import (
    WorkflowRegistryError,
    decode_definition,
)
from yoke_core.domain.workflow_registry_rows import (
    version_by_id,
    version_row,
    workflow_row,
)
from yoke_core.domain.workflow_registry_sql import marker


def set_current_workflow_version(
    conn: Any,
    *,
    workflow_id: str,
    version: int,
    expected_current_version: Optional[int] = None,
) -> dict:
    """Select an existing immutable version for subsequently created items."""
    bind = marker(conn)
    if db_backend.connection_is_postgres(conn):
        conn.execute(
            f"SELECT id FROM workflows WHERE id = {bind} FOR UPDATE",
            (workflow_id,),
        ).fetchone()
    workflow = workflow_row(conn, workflow_id)
    if workflow is None:
        raise WorkflowRegistryError(f"unknown workflow {workflow_id!r}")
    current_id = workflow.get("current_version_id")
    current = (
        version_by_id(conn, int(current_id))
        if current_id is not None
        else None
    )
    if current is None or current["workflow_id"] != workflow_id:
        raise WorkflowRegistryError(
            f"workflow {workflow_id!r} has an invalid current version"
        )
    if (
        expected_current_version is not None
        and int(current["version"]) != int(expected_current_version)
    ):
        raise WorkflowRegistryError(
            f"workflow {workflow_id!r} current version changed from "
            f"{expected_current_version} to {current['version']}; refresh first"
        )
    target = version_row(conn, workflow_id, version)
    if target is None:
        raise WorkflowRegistryError(
            f"unknown workflow version {workflow_id}@{version}"
        )
    conn.execute(
        f"UPDATE workflows SET current_version_id = {bind}, "
        f"updated_at = {bind} WHERE id = {bind}",
        (int(target["id"]), iso8601_now(), workflow_id),
    )
    conn.commit()
    return {
        "workflow_id": workflow_id,
        "version": int(target["version"]),
        "version_id": int(target["id"]),
    }


def get_workflow_version(
    conn: Any,
    *,
    workflow_id: str,
    version: int,
) -> dict:
    """Return one immutable definition and whether it is current."""
    workflow = workflow_row(conn, workflow_id)
    if workflow is None:
        raise WorkflowRegistryError(f"unknown workflow {workflow_id!r}")
    row = version_row(conn, workflow_id, version)
    if row is None:
        raise WorkflowRegistryError(
            f"unknown workflow version {workflow_id}@{version}"
        )
    return {
        "workflow_id": workflow_id,
        "version": int(row["version"]),
        "version_id": int(row["id"]),
        "definition_schema_version": int(row["definition_schema_version"]),
        "definition_digest": row["definition_digest"],
        "published_at": row["published_at"],
        "immutable_at": row["immutable_at"],
        "published_by_actor_id": row.get("published_by_actor_id"),
        "current": int(workflow["current_version_id"]) == int(row["id"]),
        "definition": decode_definition(row["definition_json"]),
    }


__all__ = ["get_workflow_version", "set_current_workflow_version"]
