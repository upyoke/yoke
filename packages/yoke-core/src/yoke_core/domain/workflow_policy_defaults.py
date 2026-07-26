"""Constrained publication of operator-editable workflow policy defaults."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Optional

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
    if path_claims_default is None:
        raise WorkflowRegistryError("no workflow policy default was supplied")

    definition = deepcopy(
        get_workflow_version(
            conn,
            workflow_id=workflow_id,
            version=current_version,
        )["definition"]
    )
    policies = definition["policies"]
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
    result = publish_workflow_version(
        conn,
        workflow_id=workflow_id,
        definition=definition,
        published_by_actor_id=published_by_actor_id,
        expected_current_version=current_version,
    )
    return {
        **result,
        "path_claims_default": bool(path_claims_default),
    }


__all__ = ["publish_workflow_policy_defaults"]
