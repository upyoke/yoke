"""Whole-definition updates, validation, ordering, and version publication."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any

from yoke_core.domain import json_helper
from yoke_core.domain.deployment_flow_target_support import (
    configured_identity_path,
    require_provable_qa_identity,
    require_supported_stage_targets,
    unprovable_qa_identity_stages,
    unsupported_stage_target_kinds,
)
from yoke_core.domain.deployment_flow_policy import (
    CURRENT_EXECUTION_SCHEMA_VERSION,
    definition_schema_version,
    require_supported_definition_schema,
    validate_stage_references,
)
from yoke_core.domain.deployment_flow_state import (
    FLOW_STATUS_ACTIVE,
    assert_flow_definition_mutable,
    lock_deployment_flow_rows,
    validate_flow_status,
)
from yoke_core.domain.flow_create import cmd_create
from yoke_core.domain.flow_target import resolve_flow_target
from yoke_core.domain.flow_validation import (
    require_human_approval_addresses,
    validate_stages,
)

CONFIG_FIELDS = frozenset(
    {
        "name",
        "description",
        "stages",
        "on_failure",
        "target_tier",
        "environment",
        "done_description",
    }
)
ON_FAILURE_VALUES = frozenset({"halt", "continue"})


def _cell(row: Any, key: str, index: int) -> Any:
    return row[key] if hasattr(row, "keys") else row[index]


def _definition(conn: Any, flow_id: str) -> dict[str, Any]:
    row = conn.execute(
        "SELECT df.id,df.project_id,p.slug AS project,df.name,df.description,df.stages,"
        "df.on_failure,df.target_tier,e.name AS environment,df.done_description,df.status,"
        "df.definition_schema_version,df.supersedes_flow_id "
        "FROM deployment_flows df JOIN projects p ON p.id=df.project_id "
        "LEFT JOIN environments e ON e.id=df.target_environment_id WHERE df.id=%s",
        (flow_id,),
    ).fetchone()
    if row is None:
        raise LookupError(f"deployment flow {flow_id!r} not found")
    fields = (
        "id",
        "project_id",
        "project",
        "name",
        "description",
        "stages",
        "on_failure",
        "target_tier",
        "environment",
        "done_description",
        "status",
        "definition_schema_version",
        "supersedes_flow_id",
    )
    return {name: _cell(row, name, index) for index, name in enumerate(fields)}


def _validate_definition(conn: Any, definition: Mapping[str, Any]) -> int:
    stages = str(definition["stages"])
    validate_stages(stages)
    require_human_approval_addresses(stages)
    project = str(definition["project"])
    validate_stage_references(conn, project=project, stages_json=stages)
    on_failure = str(definition.get("on_failure") or "halt")
    if on_failure not in ON_FAILURE_VALUES:
        raise ValueError(
            f"on_failure must be one of: {', '.join(sorted(ON_FAILURE_VALUES))}"
        )
    resolve_flow_target(
        conn,
        project=project,
        target_tier=definition.get("target_tier"),
        environment=definition.get("environment"),
    )
    status = validate_flow_status(str(definition.get("status") or "active"))
    schema_version = definition_schema_version(stages)
    if status == FLOW_STATUS_ACTIVE:
        require_supported_definition_schema(
            schema_version, operation="activating this deployment flow"
        )
        require_supported_stage_targets(
            stages, operation="activating this deployment flow"
        )
        require_provable_qa_identity(
            stages,
            operation="activating this deployment flow",
            conn=conn,
            project=project,
        )
    return schema_version


def cmd_validate_definition(
    conn: Any,
    *,
    project: str,
    stages: str,
    target_tier: str | None = None,
    environment: str | None = None,
    status: str = "disabled",
) -> dict[str, Any]:
    definition = {
        "project": project,
        "stages": stages,
        "target_tier": target_tier,
        "environment": environment,
        "on_failure": "halt",
        "status": status,
    }
    schema_version = _validate_definition(conn, definition)
    # Two independent axes, and the answer promises both: the vocabulary
    # this runtime executes, and whether anything can observe the QA
    # targets THIS definition names. Reporting only the version would
    # advertise a definition that activates and then fails mid-run.
    decoded = json_helper.loads_text(stages)
    unsupported = unsupported_stage_target_kinds(decoded)
    # The same configuration the activation gate reads, so a preview of a
    # definition and the gate that admits it can never disagree about
    # whether this project's environments can prove what they serve.
    identity = configured_identity_path(conn, project)
    unprovable = unprovable_qa_identity_stages(
        decoded, identity_path_configured=identity.configured
    )
    return {
        "valid": True,
        "definition_schema_version": schema_version,
        "identity_config_error": identity.error,
        "execution_supported": (
            schema_version <= CURRENT_EXECUTION_SCHEMA_VERSION
            and not unsupported
            and not unprovable
        ),
        "serving_schema_version": CURRENT_EXECUTION_SCHEMA_VERSION,
        "unsupported_target_kinds": list(unsupported),
        "unprovable_qa_identity_stages": list(unprovable),
    }


def _assert_name_available(
    conn: Any,
    *,
    project_id: int,
    flow_id: str,
    name: str,
) -> None:
    row = conn.execute(
        "SELECT id FROM deployment_flows WHERE project_id=%s AND name=%s",
        (project_id, name),
    ).fetchone()
    if row is not None and str(row[0]) != flow_id:
        raise ValueError(
            f"display name {name!r} already belongs to deployment flow {row[0]!r}"
        )


def _merged_definition(
    current: Mapping[str, Any], changes: Mapping[str, Any]
) -> dict[str, Any]:
    unknown = set(changes) - CONFIG_FIELDS
    if unknown:
        raise ValueError(f"unknown deployment-flow update fields: {sorted(unknown)}")
    if not changes:
        raise ValueError("at least one deployment-flow field must be updated")
    merged = dict(current)
    merged.update(changes)
    name = merged.get("name")
    if not isinstance(name, str) or not name.strip():
        raise ValueError("name must be a non-empty string")
    description = merged.get("description")
    if description is not None and not isinstance(description, str):
        raise ValueError("description must be a string")
    return merged


def cmd_update_definition(
    conn: Any,
    flow_id: str,
    changes: Mapping[str, Any],
) -> dict[str, Any]:
    locked = lock_deployment_flow_rows(conn, (flow_id,), binding=False)
    if flow_id not in locked:
        raise LookupError(f"deployment flow {flow_id!r} not found")
    assert_flow_definition_mutable(conn, flow_id)
    current = _definition(conn, flow_id)
    merged = _merged_definition(current, changes)
    schema_version = _validate_definition(conn, merged)
    _assert_name_available(
        conn,
        project_id=int(current["project_id"]),
        flow_id=flow_id,
        name=str(merged["name"]),
    )
    target_environment_id = resolve_flow_target(
        conn,
        project=str(current["project"]),
        target_tier=merged.get("target_tier"),
        environment=merged.get("environment"),
    )
    conn.execute(
        "UPDATE deployment_flows SET name=%s,description=%s,stages=%s,"
        "on_failure=%s,target_tier=%s,target_environment_id=%s,"
        "done_description=%s,definition_schema_version=%s WHERE id=%s",
        (
            str(merged["name"]),
            merged.get("description"),
            str(merged["stages"]),
            str(merged.get("on_failure") or "halt"),
            merged.get("target_tier"),
            target_environment_id,
            merged.get("done_description"),
            schema_version,
            flow_id,
        ),
    )
    conn.commit()
    return _definition(conn, flow_id)


def cmd_reorder_stages(
    conn: Any,
    flow_id: str,
    ordered_names: Sequence[str],
) -> dict[str, Any]:
    current = _definition(conn, flow_id)
    stages = json.loads(str(current["stages"]))
    existing = [str(stage.get("name") or "") for stage in stages]
    requested = [str(name) for name in ordered_names]
    if len(requested) != len(set(requested)):
        raise ValueError("stage order must not contain duplicate names")
    if set(requested) != set(existing) or len(requested) != len(existing):
        raise ValueError(
            "stage order must name every existing stage exactly once; "
            f"existing={existing!r}"
        )
    by_name = {str(stage["name"]): stage for stage in stages}
    return cmd_update_definition(
        conn,
        flow_id,
        {
            "stages": json.dumps(
                [by_name[name] for name in requested], separators=(",", ":")
            )
        },
    )


def cmd_version_definition(
    conn: Any,
    source_flow_id: str,
    new_flow_id: str,
    *,
    name: str,
    changes: Mapping[str, Any] | None = None,
    status: str = "disabled",
) -> dict[str, Any]:
    source = _definition(conn, source_flow_id)
    merged = _merged_definition(source, {**dict(changes or {}), "name": name})
    merged["status"] = status
    _validate_definition(conn, merged)
    cmd_create(
        conn,
        new_flow_id,
        str(source["project"]),
        str(merged["name"]),
        str(merged.get("description") or ""),
        str(merged["stages"]),
        on_failure=str(merged.get("on_failure") or "halt"),
        target_tier=merged.get("target_tier"),
        environment=merged.get("environment"),
        done_description=merged.get("done_description"),
        status=status,
        supersedes_flow_id=source_flow_id,
    )
    return _definition(conn, new_flow_id)


__all__ = [
    "CONFIG_FIELDS",
    "cmd_reorder_stages",
    "cmd_update_definition",
    "cmd_validate_definition",
    "cmd_version_definition",
]
