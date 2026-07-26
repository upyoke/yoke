"""Constrained publication of operator-editable workflow policy defaults."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping, Optional

from yoke_core.domain import db_backend
from yoke_core.domain.workflow_definition_builders import (
    WORKFLOW_PATH_CLAIMS_OPTIONAL,
    WORKFLOW_PATH_CLAIMS_REQUIRED,
)
from yoke_core.domain.workflow_definition_codec import WorkflowRegistryError
from yoke_core.domain.workflow_registry import (
    get_workflow_version,
    list_current_workflows,
    publish_workflow_version,
)


def publish_workflow_policy_defaults(
    conn: Any,
    *,
    workflow_id: str,
    expected_current_version: int,
    path_claims_default: Optional[bool] = None,
    approval_defaults: Optional[Mapping[str, Any]] = None,
    published_by_actor_id: Optional[int] = None,
) -> dict:
    """Publish one new version after editing only declared policy defaults."""
    current_rows = {
        str(row["id"]): row for row in list_current_workflows(conn)
    }
    current = current_rows.get(workflow_id)
    if current is None:
        raise WorkflowRegistryError(f"unknown workflow {workflow_id!r}")
    current_version = int(current["current_version"])
    if current_version != int(expected_current_version):
        raise WorkflowRegistryError(
            f"workflow {workflow_id!r} current version changed from "
            f"{expected_current_version} to {current_version}; refresh first"
        )
    supplied = sum((
        path_claims_default is not None,
        approval_defaults is not None,
    ))
    if supplied == 0:
        raise WorkflowRegistryError("no workflow policy default was supplied")
    if supplied > 1:
        raise WorkflowRegistryError(
            "publish exactly one workflow policy default at a time"
        )

    definition = deepcopy(
        get_workflow_version(
            conn,
            workflow_id=workflow_id,
            version=current_version,
        )["definition"]
    )
    policies = definition["policies"]
    # An immutable definition read may omit this optional address field. Every
    # new policy publication carries the normalized shape, regardless of which
    # bounded default the operator edited.
    policies.setdefault("approval_defaults", {})
    result_fields: dict[str, Any]
    if path_claims_default is not None:
        existing = str(policies["path_claims"])
        if "path_claims" not in set(policies["item_posture_allowlist"]):
            raise WorkflowRegistryError(
                f"workflow {workflow_id!r} does not expose path claims "
                "as an operator-editable default"
            )
        if existing not in {
            WORKFLOW_PATH_CLAIMS_OPTIONAL,
            WORKFLOW_PATH_CLAIMS_REQUIRED,
        }:
            raise WorkflowRegistryError(
                f"workflow {workflow_id!r} path-claim policy {existing!r} "
                "is not an editable default"
            )
        policies["path_claims"] = (
            WORKFLOW_PATH_CLAIMS_REQUIRED
            if path_claims_default
            else WORKFLOW_PATH_CLAIMS_OPTIONAL
        )
        result_fields = {"path_claims_default": bool(path_claims_default)}
    else:
        assert approval_defaults is not None
        role_order = {"owner": 0, "operator": 1, "admin": 2}
        normalized = {}
        for transition_id, raw_gate in approval_defaults.items():
            gate = dict(raw_gate)
            roles = sorted(
                {str(value) for value in gate.get("roles", ())},
                key=lambda value: (role_order.get(value, 99), value),
            )
            actors = sorted({int(value) for value in gate.get("actors", ())})
            if roles or actors:
                normalized[str(transition_id)] = {
                    "roles": roles,
                    "actors": actors,
                }
        actor_ids = {
            actor_id
            for gate in normalized.values()
            for actor_id in gate["actors"]
        }
        marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
        for actor_id in actor_ids:
            if conn.execute(
                f"SELECT 1 FROM actors WHERE id={marker}",
                (actor_id,),
            ).fetchone() is None:
                raise WorkflowRegistryError(
                    f"approval actor {actor_id} does not exist"
                )
        policies["approval_defaults"] = normalized
        result_fields = {"approval_defaults": normalized}
    result = publish_workflow_version(
        conn,
        workflow_id=workflow_id,
        definition=definition,
        published_by_actor_id=published_by_actor_id,
        expected_current_version=current_version,
    )
    return {
        **result,
        **result_fields,
    }


__all__ = ["publish_workflow_policy_defaults"]
