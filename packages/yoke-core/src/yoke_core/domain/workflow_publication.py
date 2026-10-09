"""Append validated workflow definitions without changing existing item pins."""

from __future__ import annotations
from typing import Any, Mapping, Optional
from yoke_core.domain import db_backend
from yoke_core.domain.db_helpers import iso8601_now
from yoke_core.domain.workflow_definition_codec import (
    WorkflowRegistryError,
    decode_definition as _decode_definition,
    definition_digest,
)
from yoke_core.domain.workflow_definition_validation import validate_workflow_definition
from yoke_core.domain.workflow_registry_rows import (
    workflow_row,
    version_by_id,
    version_row_by_digest,
)
from yoke_core.domain.workflow_registry_sql import (
    marker as _marker,
    row_dict as _row_dict,
)


def publish_workflow_version(
    conn: Any,
    *,
    workflow_id: str,
    definition: Mapping[str, Any],
    published_by_actor_id: Optional[int] = None,
    expected_current_version: Optional[int] = None,
    keep_current: bool = False,
    require_expected_current: bool = False,
    reason: str = "Workflow definition edited",
) -> dict:
    """Validate, append, and select a new immutable workflow version."""
    from yoke_core.domain.workflow_registry import (
        _insert_version,
        _baseline_for_edit_of,
    )

    if not workflow_id.strip() or not reason.strip():
        raise WorkflowRegistryError(
            "workflow_publish_invalid: workflow id and reason are required; supply both"
        )
    marker = _marker(conn)
    # Serialize creation as well as appends; an absent row cannot be row-locked.
    if db_backend.connection_is_postgres(conn):
        conn.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
            (f"workflow-publish:{workflow_id}",),
        )
        conn.execute(
            f"SELECT id FROM workflows WHERE id = {marker} FOR UPDATE", (workflow_id,)
        ).fetchone()
    workflow = workflow_row(conn, workflow_id)
    current = None
    if workflow is not None:
        if require_expected_current and expected_current_version is None:
            raise WorkflowRegistryError(
                "workflow_expected_version_required: existing workflow publication requires expected_current_version; "
                "read workflows.definition.get and supply its current version"
            )
        current_id = workflow.get("current_version_id")
        current = (
            version_by_id(conn, int(current_id)) if current_id is not None else None
        )
        if current is None or current["workflow_id"] != workflow_id:
            raise WorkflowRegistryError(
                "workflow_current_invalid: current version is missing or mismatched; ask the control-plane operator to repair the workflow"
            )
        if workflow["status"] != "active":
            raise WorkflowRegistryError(
                f"workflow_disabled: {workflow_id!r}; enable it before publishing"
            )
        if (
            expected_current_version is not None
            and int(current["version"]) != expected_current_version
        ):
            raise WorkflowRegistryError(
                f"workflow_current_changed: workflow {workflow_id!r} current version changed from "
                f"{expected_current_version} to {current['version']}; refresh first"
            )
    elif expected_current_version is not None:
        raise WorkflowRegistryError(
            "workflow_not_found: new workflows have no current version; omit expected_current_version"
        )
    elif keep_current:
        raise WorkflowRegistryError(
            "workflow_current_missing: a new workflow needs its first current version; omit keep_current"
        )
    validate_workflow_definition(
        definition,
        previous=(_decode_definition(current["definition_json"]) if current else None),
    )
    digest = definition_digest(definition)
    existing = version_row_by_digest(conn, workflow_id, digest)
    if existing is not None:
        raise WorkflowRegistryError(
            f"workflow_definition_unchanged: new workflow version must change the definition; "
            f"definition already published as version {existing['version']}; select or pin that version"
        )
    if workflow is None:
        now = iso8601_now()
        conn.execute(
            "INSERT INTO workflows (id, name, description, source, status, canon_follow, created_at, updated_at) "
            f"VALUES ({marker}, {marker}, {marker}, 'project', 'active', 'manual', {marker}, {marker})",
            (workflow_id, workflow_id, "Locally authored workflow", now, now),
        )
    cursor = conn.execute(
        "SELECT COALESCE(MAX(version), 0) AS maximum "
        f"FROM workflow_versions WHERE workflow_id = {marker}",
        (workflow_id,),
    )
    row = _row_dict(cursor, cursor.fetchone())
    next_version = int(row["maximum"]) + 1
    published = _insert_version(
        conn,
        workflow_id=workflow_id,
        version=next_version,
        definition=definition,
        published_by_actor_id=published_by_actor_id,
        derived_from_canon_version=_baseline_for_edit_of(current) if current else None,
        published_reason=reason.strip(),
    )
    if not keep_current:
        conn.execute(
            f"UPDATE workflows SET current_version_id = {marker}, "
            "canon_follow = 'manual', canon_adopted_from_version = NULL, "
            f"updated_at = {marker} WHERE id = {marker}",
            (int(published["id"]), iso8601_now(), workflow_id),
        )
    conn.commit()
    return {
        "workflow_id": workflow_id,
        "version": next_version,
        "version_id": int(published["id"]),
        "definition_digest": published["definition_digest"],
        "current": not keep_current,
    }
