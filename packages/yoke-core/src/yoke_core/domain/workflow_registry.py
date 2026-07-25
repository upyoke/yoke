"""Persistence and version operations for declarative workflows."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, Mapping, Optional

from yoke_core.domain import db_backend
from yoke_core.domain.builtin_workflow_definitions import (
    builtin_workflow_definitions,
)
from yoke_core.domain.db_helpers import iso8601_now
from yoke_core.domain.workflow_definition_validation import (
    validate_workflow_definition,
)


class WorkflowRegistryError(RuntimeError):
    """A requested registry operation cannot preserve registry invariants."""


def canonical_definition_json(definition: Mapping[str, Any]) -> str:
    """Serialize a definition into the stable digest and storage form."""
    return json.dumps(
        definition,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def definition_digest(definition: Mapping[str, Any]) -> str:
    """Return the SHA-256 digest of the canonical definition JSON."""
    encoded = canonical_definition_json(definition).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _decode_definition(raw: Any) -> Dict[str, Any]:
    try:
        value = json.loads(str(raw))
    except (TypeError, json.JSONDecodeError) as exc:
        raise WorkflowRegistryError(
            "stored workflow definition is not valid JSON"
        ) from exc
    if not isinstance(value, dict):
        raise WorkflowRegistryError("stored workflow definition is not an object")
    return value


def _workflow_row(conn: Any, workflow_id: str) -> Optional[dict]:
    row = conn.execute(
        "SELECT * FROM workflows WHERE id = %s",
        (workflow_id,),
    ).fetchone()
    return dict(row) if row is not None else None


def _version_row(
    conn: Any,
    workflow_id: str,
    version: int,
) -> Optional[dict]:
    row = conn.execute(
        "SELECT * FROM workflow_versions "
        "WHERE workflow_id = %s AND version = %s",
        (workflow_id, version),
    ).fetchone()
    return dict(row) if row is not None else None


def _version_by_id(conn: Any, version_id: int) -> Optional[dict]:
    row = conn.execute(
        "SELECT * FROM workflow_versions WHERE id = %s",
        (version_id,),
    ).fetchone()
    return dict(row) if row is not None else None


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
    conn.execute(
        "INSERT INTO workflow_versions "
        "(workflow_id, version, definition_schema_version, definition_json, "
        "definition_digest, published_at, published_by_actor_id, immutable_at) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
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
                "VALUES (%s, %s, %s, %s, 'active', NULL, %s, %s)",
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
                "UPDATE workflows SET current_version_id = %s, updated_at = %s "
                "WHERE id = %s",
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
) -> dict:
    """Validate, append, and select a new immutable workflow version."""
    if db_backend.connection_is_postgres(conn):
        conn.execute(
            "SELECT id FROM workflows WHERE id = %s FOR UPDATE",
            (workflow_id,),
        ).fetchone()
    workflow, current = _current_definition(conn, workflow_id)
    if workflow["status"] != "active":
        raise WorkflowRegistryError(f"workflow {workflow_id!r} is disabled")
    previous = _decode_definition(current["definition_json"])
    validate_workflow_definition(definition, previous=previous)
    row = conn.execute(
        "SELECT COALESCE(MAX(version), 0) AS maximum "
        "FROM workflow_versions WHERE workflow_id = %s",
        (workflow_id,),
    ).fetchone()
    next_version = int(dict(row)["maximum"]) + 1
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
        "UPDATE workflows SET current_version_id = %s, updated_at = %s "
        "WHERE id = %s",
        (int(published["id"]), iso8601_now(), workflow_id),
    )
    conn.commit()
    return {
        "workflow_id": workflow_id,
        "version": next_version,
        "version_id": int(published["id"]),
        "definition_digest": published["definition_digest"],
    }


def set_current_workflow_version(
    conn: Any,
    *,
    workflow_id: str,
    version: int,
) -> dict:
    """Select an existing immutable version for subsequently created items."""
    workflow = _workflow_row(conn, workflow_id)
    if workflow is None:
        raise WorkflowRegistryError(f"unknown workflow {workflow_id!r}")
    target = _version_row(conn, workflow_id, version)
    if target is None:
        raise WorkflowRegistryError(
            f"unknown workflow version {workflow_id}@{version}"
        )
    conn.execute(
        "UPDATE workflows SET current_version_id = %s, updated_at = %s "
        "WHERE id = %s",
        (int(target["id"]), iso8601_now(), workflow_id),
    )
    conn.commit()
    return {
        "workflow_id": workflow_id,
        "version": int(target["version"]),
        "version_id": int(target["id"]),
    }


def list_current_workflows(conn: Any) -> list[dict]:
    """Return each workflow joined to its selected immutable definition."""
    rows = conn.execute(
        "SELECT w.id, w.name, w.description, w.source, w.status, "
        "w.current_version_id, v.version, v.definition_schema_version, "
        "v.definition_json, v.definition_digest, v.published_at, "
        "v.immutable_at "
        "FROM workflows w "
        "JOIN workflow_versions v ON v.id = w.current_version_id "
        "ORDER BY w.name, w.id"
    ).fetchall()
    version_rows = conn.execute(
        "SELECT id, workflow_id, version, definition_digest, published_at, "
        "immutable_at FROM workflow_versions "
        "ORDER BY workflow_id, version"
    ).fetchall()
    versions_by_workflow: dict[str, list[dict]] = {}
    for raw_version in version_rows:
        version_row = dict(raw_version)
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
    for raw in rows:
        row = dict(raw)
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
    "list_current_workflows",
    "publish_workflow_version",
    "resolve_current_workflow_pin",
    "set_current_workflow_version",
]
