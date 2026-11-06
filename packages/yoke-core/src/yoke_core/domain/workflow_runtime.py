"""Load and verify an item's pinned workflow version."""

from __future__ import annotations
import json
from typing import Any
from yoke_core.domain import db_backend
from yoke_core.domain.builtin_workflow_definitions import builtin_workflow_definition
from yoke_core.domain.workflow_registry import WorkflowRegistryError, definition_digest
from yoke_core.domain.workflow_registry_sql import row_dict as _row_dict
from yoke_core.domain.project_identity import render_item_ref
from yoke_contracts.public_ref import ITEM_NOT_FOUND
from yoke_core.domain.workflow_runtime_model import (
    WorkflowRuntime,
)
from yoke_contracts.lifecycle_status import (
    ENGINE_TERMINAL_STAGE_IDS,
    ENGINE_WAIT_STAGE_IDS,
    ENGINE_EXCEPTIONAL_STAGE_IDS,
)


def _placeholder(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _runtime_from_row(row: Any) -> WorkflowRuntime:
    values = dict(row)
    raw_definition = values["definition_json"]
    try:
        definition = json.loads(str(raw_definition))
    except (TypeError, json.JSONDecodeError) as exc:
        raise WorkflowRegistryError(
            "stored workflow definition is not valid JSON"
        ) from exc
    if not isinstance(definition, dict):
        raise WorkflowRegistryError("stored workflow definition is not an object")
    stored_digest = str(values["definition_digest"])
    if definition_digest(definition) != stored_digest:
        raise WorkflowRegistryError(
            f"workflow version {values['workflow_id']}@{values['version']} "
            "does not match its immutable digest"
        )
    return WorkflowRuntime(
        workflow_id=str(values["workflow_id"]),
        workflow_version_id=int(values["workflow_version_id"]),
        version=int(values["version"]),
        definition_digest=stored_digest,
        definition=definition,
    )


def workflow_runtime_from_row(row: Any) -> WorkflowRuntime:
    """Interpret a joined workflow-version row without another DB query."""
    return _runtime_from_row(row)


def load_workflow_runtime(
    conn: Any,
    *,
    workflow_id: str,
    workflow_version_id: int,
) -> WorkflowRuntime:
    """Load and verify one explicitly pinned workflow version."""
    placeholder = _placeholder(conn)
    cursor = conn.execute(
        "SELECT v.id AS workflow_version_id, v.workflow_id, v.version, "
        "v.definition_json, v.definition_digest "
        "FROM workflow_versions v "
        f"WHERE v.id = {placeholder} AND v.workflow_id = {placeholder}",
        (workflow_version_id, workflow_id),
    )
    row = _row_dict(cursor, cursor.fetchone())
    if row is None:
        raise WorkflowRegistryError(
            f"unknown workflow pin {workflow_id}@version-id:{workflow_version_id}"
        )
    return _runtime_from_row(row)


def builtin_workflow_runtime(workflow_id: str) -> WorkflowRuntime:
    """Build a non-persistent runtime for pure domain tests and tooling.

    Nothing is stored, so there is no universe to hold a version number. The
    published generation stands in for one, which keeps the runtime honest
    about which definition it carries.
    """
    fixture = builtin_workflow_definition(workflow_id)
    definition = fixture["definition"]
    return WorkflowRuntime(
        workflow_id=workflow_id,
        workflow_version_id=0,
        version=int(fixture["canon_version"]),
        definition_digest=definition_digest(definition),
        definition=definition,
    )


def load_item_workflow_runtime(
    conn: Any,
    item_id: int,
) -> WorkflowRuntime:
    """Load and verify the immutable workflow version pinned by an item."""
    placeholder = _placeholder(conn)
    cursor = conn.execute(
        "SELECT i.workflow_id, i.workflow_version_id, v.version, "
        "v.definition_json, v.definition_digest "
        "FROM items i "
        "LEFT JOIN workflow_versions v ON v.id = i.workflow_version_id "
        f"WHERE i.id = {placeholder}",
        (item_id,),
    )
    row = _row_dict(cursor, cursor.fetchone())
    if row is None:
        raise WorkflowRegistryError(ITEM_NOT_FOUND)
    values = dict(row)
    if (
        values.get("workflow_id") is None
        or values.get("workflow_version_id") is None
        or values.get("version") is None
    ):
        raise WorkflowRegistryError(
            f"{render_item_ref(conn, item_id)} has no complete workflow-version pin"
        )
    return _runtime_from_row(row)


__all__ = [
    "ENGINE_EXCEPTIONAL_STAGE_IDS",
    "ENGINE_TERMINAL_STAGE_IDS",
    "ENGINE_WAIT_STAGE_IDS",
    "WorkflowRuntime",
    "builtin_workflow_runtime",
    "load_item_workflow_runtime",
    "load_workflow_runtime",
    "workflow_runtime_from_row",
]
