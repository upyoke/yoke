"""Persistence and version operations for declarative workflows."""

from __future__ import annotations

from typing import Any, Mapping, Optional

from yoke_core.domain import db_backend
from yoke_core.domain.builtin_workflow_definitions import (
    builtin_workflow_definitions,
)
from yoke_core.domain.db_helpers import iso8601_now
from yoke_core.domain.workflow_definition_codec import (
    WorkflowRegistryError,
    canonical_definition_json,
    decode_definition as _decode_definition,
    definition_digest,
)
from yoke_core.domain.workflow_definition_validation import (
    validate_workflow_definition,
)
from yoke_core.domain.workflow_registry_rows import (
    version_by_id as _version_by_id,
    version_row as _version_row,
    workflow_row as _workflow_row,
)
from yoke_core.domain.workflow_registry_sql import (
    marker as _marker,
    row_dict as _row_dict,
    rows_dict as _rows_dict,
)
from yoke_core.domain.workflow_registry_versions import (
    get_workflow_version,
    set_current_workflow_version,
)


def _insert_version(
    conn: Any,
    *,
    workflow_id: str,
    version: int,
    definition: Mapping[str, Any],
    published_by_actor_id: Optional[int],
) -> dict:
    validate_workflow_definition(definition)
    now = iso8601_now()
    canonical = canonical_definition_json(definition)
    digest = definition_digest(definition)
    marker = _marker(conn)
    conn.execute(
        "INSERT INTO workflow_versions "
        "(workflow_id, version, definition_schema_version, definition_json, "
        "definition_digest, published_at, published_by_actor_id, immutable_at) "
        f"VALUES ({', '.join(marker for _ in range(8))})",
        (
            workflow_id,
            version,
            int(definition["schema_version"]),
            canonical,
            digest,
            now,
            published_by_actor_id,
            now,
        ),
    )
    row = _version_row(conn, workflow_id, version)
    if row is None:
        raise WorkflowRegistryError(
            f"workflow version {workflow_id}@{version} was not inserted"
        )
    return row


def converge_builtin_workflows(conn: Any) -> None:
    """Insert missing built-ins without mutating published versions."""
    now = iso8601_now()
    marker = _marker(conn)
    for fixture in builtin_workflow_definitions():
        workflow = fixture["workflow"]
        workflow_id = str(workflow["id"])
        definition = fixture["definition"]
        validate_workflow_definition(definition)
        existing_workflow = _workflow_row(conn, workflow_id)
        if existing_workflow is None:
            conn.execute(
                "INSERT INTO workflows "
                "(id, name, description, source, status, current_version_id, "
                "created_at, updated_at) "
                f"VALUES ({marker}, {marker}, {marker}, {marker}, "
                f"'active', NULL, {marker}, {marker})",
                (
                    workflow_id,
                    workflow["name"],
                    workflow["description"],
                    workflow["source"],
                    now,
                    now,
                ),
            )
        elif existing_workflow["source"] != "built_in":
            raise WorkflowRegistryError(
                f"built-in workflow id {workflow_id!r} is owned by "
                f"{existing_workflow['source']!r}"
            )
        else:
            conn.execute(
                f"UPDATE workflows SET name = {marker}, "
                f"description = {marker}, updated_at = {marker} "
                f"WHERE id = {marker}",
                (
                    workflow["name"],
                    workflow["description"],
                    now,
                    workflow_id,
                ),
            )

        version = int(fixture["version"])
        existing_version = _version_row(conn, workflow_id, version)
        digest = definition_digest(definition)
        if existing_version is None:
            existing_version = _insert_version(
                conn,
                workflow_id=workflow_id,
                version=version,
                definition=definition,
                published_by_actor_id=None,
            )
        elif existing_version["definition_digest"] != digest:
            raise WorkflowRegistryError(
                f"published built-in {workflow_id}@{version} differs from "
                "the code-owned definition"
            )

        current = _workflow_row(conn, workflow_id)
        if current is None:
            raise WorkflowRegistryError(f"workflow {workflow_id!r} is missing")
        current_id = current.get("current_version_id")
        if current_id is None:
            conn.execute(
                f"UPDATE workflows SET current_version_id = {marker}, "
                f"updated_at = {marker} WHERE id = {marker}",
                (int(existing_version["id"]), now, workflow_id),
            )
        else:
            current_version = _version_by_id(conn, int(current_id))
            if (
                current_version is None
                or current_version["workflow_id"] != workflow_id
            ):
                raise WorkflowRegistryError(
                    f"workflow {workflow_id!r} has an invalid current version"
                )
    conn.commit()


def _current_definition(conn: Any, workflow_id: str) -> tuple[dict, dict]:
    workflow = _workflow_row(conn, workflow_id)
    if workflow is None:
        raise WorkflowRegistryError(f"unknown workflow {workflow_id!r}")
    current_id = workflow.get("current_version_id")
    if current_id is None:
        raise WorkflowRegistryError(
            f"workflow {workflow_id!r} has no current version"
        )
    version = _version_by_id(conn, int(current_id))
    if version is None or version["workflow_id"] != workflow_id:
        raise WorkflowRegistryError(
            f"workflow {workflow_id!r} has an invalid current version"
        )
    return workflow, version


def resolve_current_workflow_pin(
    conn: Any,
    workflow_id: str,
) -> tuple[str, int]:
    """Return the active workflow id and immutable current-version row id."""
    workflow, version = _current_definition(conn, workflow_id)
    if workflow["status"] != "active":
        raise WorkflowRegistryError(f"workflow {workflow_id!r} is disabled")
    return workflow_id, int(version["id"])


def publish_workflow_version(
    conn: Any,
    *,
    workflow_id: str,
    definition: Mapping[str, Any],
    published_by_actor_id: Optional[int] = None,
    expected_current_version: Optional[int] = None,
) -> dict:
    """Validate, append, and select a new immutable workflow version."""
    marker = _marker(conn)
    if db_backend.connection_is_postgres(conn):
        conn.execute(
            f"SELECT id FROM workflows WHERE id = {marker} FOR UPDATE",
            (workflow_id,),
        ).fetchone()
    workflow, current = _current_definition(conn, workflow_id)
    if workflow["status"] != "active":
        raise WorkflowRegistryError(f"workflow {workflow_id!r} is disabled")
    if (
        expected_current_version is not None
        and int(current["version"]) != int(expected_current_version)
    ):
        raise WorkflowRegistryError(
            f"workflow {workflow_id!r} current version changed from "
            f"{expected_current_version} to {current['version']}; refresh first"
        )
    previous = _decode_definition(current["definition_json"])
    validate_workflow_definition(definition, previous=previous)
    cursor = conn.execute(
        "SELECT COALESCE(MAX(version), 0) AS maximum "
        f"FROM workflow_versions WHERE workflow_id = {marker}",
        (workflow_id,),
    )
    row = _row_dict(cursor, cursor.fetchone())
    next_version = int(row["maximum"]) + 1
    if definition_digest(definition) == current["definition_digest"]:
        raise WorkflowRegistryError(
            "new workflow version must change the definition"
        )
    published = _insert_version(
        conn,
        workflow_id=workflow_id,
        version=next_version,
        definition=definition,
        published_by_actor_id=published_by_actor_id,
    )
    conn.execute(
        f"UPDATE workflows SET current_version_id = {marker}, "
        f"updated_at = {marker} WHERE id = {marker}",
        (int(published["id"]), iso8601_now(), workflow_id),
    )
    conn.commit()
    return {
        "workflow_id": workflow_id,
        "version": next_version,
        "version_id": int(published["id"]),
        "definition_digest": published["definition_digest"],
    }


def list_current_workflows(conn: Any) -> list[dict]:
    """Return each workflow joined to its selected immutable definition."""
    workflow_cursor = conn.execute(
        "SELECT w.id, w.name, w.description, w.source, w.status, "
        "w.current_version_id, v.version, v.definition_schema_version, "
        "v.definition_json, v.definition_digest, v.published_at, "
        "v.immutable_at "
        "FROM workflows w "
        "JOIN workflow_versions v ON v.id = w.current_version_id "
        "ORDER BY w.name, w.id"
    )
    rows = _rows_dict(workflow_cursor)
    version_cursor = conn.execute(
        "SELECT id, workflow_id, version, definition_digest, published_at, "
        "immutable_at FROM workflow_versions "
        "ORDER BY workflow_id, version"
    )
    version_rows = _rows_dict(version_cursor)
    versions_by_workflow: dict[str, list[dict]] = {}
    for version_row in version_rows:
        versions_by_workflow.setdefault(
            str(version_row["workflow_id"]), []
        ).append({
            "id": int(version_row["id"]),
            "version": int(version_row["version"]),
            "definition_digest": version_row["definition_digest"],
            "published_at": version_row["published_at"],
            "immutable_at": version_row["immutable_at"],
        })
    result: list[dict] = []
    for row in rows:
        result.append({
            "id": row["id"],
            "name": row["name"],
            "description": row["description"],
            "source": row["source"],
            "status": row["status"],
            "current_version": int(row["version"]),
            "current_version_id": int(row["current_version_id"]),
            "definition_schema_version": int(
                row["definition_schema_version"]
            ),
            "definition_digest": row["definition_digest"],
            "published_at": row["published_at"],
            "immutable_at": row["immutable_at"],
            "definition": _decode_definition(row["definition_json"]),
            "versions": versions_by_workflow.get(str(row["id"]), []),
        })
    return result


__all__ = [
    "WorkflowRegistryError",
    "canonical_definition_json",
    "converge_builtin_workflows",
    "definition_digest",
    "get_workflow_version",
    "list_current_workflows",
    "publish_workflow_version",
    "resolve_current_workflow_pin",
    "set_current_workflow_version",
]
