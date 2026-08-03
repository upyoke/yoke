"""Focused workflow-version fixtures shared by registry-authority tests."""

from __future__ import annotations

from typing import Any, Optional

from yoke_core.domain.builtin_workflow_definitions import (
    builtin_workflow_definition,
)
from yoke_core.domain.workflow_registry import publish_workflow_version


def publish_issue_completion_stage(
    conn: Any,
    *,
    stage_id: str = "archived",
    generated_children: Optional[str] = None,
) -> dict:
    """Publish an Issue version whose successful terminal follows ``done``."""
    definition = builtin_workflow_definition("issue")["definition"]
    previous_stage_ids = [stage["id"] for stage in definition["stages"]]
    definition["stages"].append(
        {
            "id": stage_id,
            "label": stage_id,
            "gates": [],
        }
    )
    definition["terminal_stage_ids"] = [stage_id]
    definition["transitions"].append(
        {
            "from_stage_id": "done",
            "to_stage_id": stage_id,
        }
    )
    definition["skill_bindings"][-1]["through_stage_id"] = stage_id
    definition["stage_mapping"] = {
        previous_stage_id: previous_stage_id for previous_stage_id in previous_stage_ids
    }
    if generated_children is not None:
        definition["policies"]["generated_children"] = generated_children
    return publish_workflow_version(
        conn,
        workflow_id="issue",
        definition=definition,
    )


__all__ = ["publish_issue_completion_stage"]
