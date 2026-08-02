"""Vocabulary and small builders for declarative workflow definitions."""

from __future__ import annotations

from typing import Any, Dict, Iterable, Optional, Sequence

WORKFLOW_DEFINITION_SCHEMA_VERSION = 2
BUILTIN_WORKFLOW_PREFERRED_VERSION = 3
WORKFLOW_FILE_BUDGET_OPTIONAL = "optional"
WORKFLOW_FILE_BUDGET_REQUIRED = "required"
WORKFLOW_FILE_BUDGET_REQUIRED_PER_TASK = "required_per_task"
WORKFLOW_PATH_CLAIMS_OPTIONAL = "optional"
WORKFLOW_PATH_CLAIMS_REQUIRED = "required"
WORKFLOW_PATH_CLAIMS_REQUIRED_PER_TASK = "required_per_task"
WORKFLOW_PATH_SURVEY_OPTIONAL = WORKFLOW_PATH_CLAIMS_OPTIONAL
WORKFLOW_PATH_SURVEY_REQUIRED = WORKFLOW_PATH_CLAIMS_REQUIRED
REGISTERED_WORKFLOW_EXECUTOR_IDS = frozenset({
    "advance",
    "blitz",
    "conduct",
    "dash",
    "polish",
    "refine",
    "shepherd",
    "usher",
})
IMPLEMENTATION_WORKFLOW_EXECUTOR_IDS = frozenset({
    "advance",
    "blitz",
    "conduct",
    "dash",
})
ENTRY_SURFACE_IDS = frozenset({
    "cli",
    "harness_skill",
    "promotion",
    "web_form",
})


def gate_ref(gate_id: str, mode: Optional[str] = None) -> Dict[str, str]:
    """Build one definition-owned reference to the closed gate catalog."""
    ref = {"id": gate_id}
    if mode:
        ref["mode"] = mode
    return ref


def workflow_stage(
    stage_id: str,
    label: str,
    gates: Iterable[Dict[str, str]] = (),
    description: Optional[str] = None,
) -> Dict[str, Any]:
    """Build one stage with a stable id and version-owned display fields."""
    stage: Dict[str, Any] = {
        "id": stage_id,
        "label": label,
        "gates": list(gates),
    }
    if description:
        stage["description"] = description
    return stage


def executor_binding(
    executor_id: str,
    from_stage_id: str,
    through_stage_id: str,
) -> Dict[str, str]:
    """Bind a registered executor to a contiguous lifecycle segment."""
    return {
        "executor_id": executor_id,
        "from_stage_id": from_stage_id,
        "through_stage_id": through_stage_id,
    }


def definition_fixture(
    *,
    workflow_id: str,
    name: str,
    description: str,
    version: int = 1,
    stages: Sequence[Dict[str, Any]],
    entry_surfaces: Sequence[str],
    executor_bindings: Sequence[Dict[str, str]],
    policies: Dict[str, Any],
    approval_defaults: Optional[Dict[str, Any]] = None,
    schema_version: int = WORKFLOW_DEFINITION_SCHEMA_VERSION,
) -> Dict[str, Any]:
    """Build one immutable built-in workflow-version fixture."""
    stage_ids = [stage["id"] for stage in stages]
    normalized_policies = dict(policies)
    if approval_defaults is not None:
        normalized_policies["approval_defaults"] = dict(approval_defaults)
    return {
        "workflow": {
            "id": workflow_id,
            "name": name,
            "description": description,
            "source": "built_in",
        },
        "version": version,
        "definition": {
            "schema_version": schema_version,
            "stages": list(stages),
            "terminal_stage_ids": [stage_ids[-1]],
            "transitions": [
                {"from_stage_id": before, "to_stage_id": after}
                for before, after in zip(stage_ids, stage_ids[1:])
            ],
            "entry_surfaces": list(entry_surfaces),
            "executor_bindings": list(executor_bindings),
            "policies": normalized_policies,
        },
    }


__all__ = [
    "BUILTIN_WORKFLOW_PREFERRED_VERSION",
    "ENTRY_SURFACE_IDS",
    "IMPLEMENTATION_WORKFLOW_EXECUTOR_IDS",
    "REGISTERED_WORKFLOW_EXECUTOR_IDS",
    "WORKFLOW_DEFINITION_SCHEMA_VERSION",
    "WORKFLOW_FILE_BUDGET_OPTIONAL",
    "WORKFLOW_FILE_BUDGET_REQUIRED",
    "WORKFLOW_FILE_BUDGET_REQUIRED_PER_TASK",
    "WORKFLOW_PATH_CLAIMS_OPTIONAL",
    "WORKFLOW_PATH_CLAIMS_REQUIRED",
    "WORKFLOW_PATH_CLAIMS_REQUIRED_PER_TASK",
    "WORKFLOW_PATH_SURVEY_OPTIONAL",
    "WORKFLOW_PATH_SURVEY_REQUIRED",
    "definition_fixture",
    "executor_binding",
    "gate_ref",
    "workflow_stage",
]
