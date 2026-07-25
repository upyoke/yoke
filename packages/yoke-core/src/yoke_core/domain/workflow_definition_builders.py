"""Vocabulary and small builders for declarative workflow definitions."""

from __future__ import annotations

from typing import Any, Dict, Iterable, Optional, Sequence

WORKFLOW_DEFINITION_SCHEMA_VERSION = 1
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
    stages: Sequence[Dict[str, Any]],
    entry_surfaces: Sequence[str],
    executor_bindings: Sequence[Dict[str, str]],
    policies: Dict[str, Any],
) -> Dict[str, Any]:
    """Build a complete first-version seed fixture."""
    stage_ids = [stage["id"] for stage in stages]
    return {
        "workflow": {
            "id": workflow_id,
            "name": name,
            "description": description,
            "source": "built_in",
        },
        "version": 1,
        "definition": {
            "schema_version": WORKFLOW_DEFINITION_SCHEMA_VERSION,
            "stages": list(stages),
            "terminal_stage_ids": [stage_ids[-1]],
            "transitions": [
                {"from_stage_id": before, "to_stage_id": after}
                for before, after in zip(stage_ids, stage_ids[1:])
            ],
            "entry_surfaces": list(entry_surfaces),
            "executor_bindings": list(executor_bindings),
            "policies": policies,
        },
    }


__all__ = [
    "ENTRY_SURFACE_IDS",
    "IMPLEMENTATION_WORKFLOW_EXECUTOR_IDS",
    "REGISTERED_WORKFLOW_EXECUTOR_IDS",
    "WORKFLOW_DEFINITION_SCHEMA_VERSION",
    "definition_fixture",
    "executor_binding",
    "gate_ref",
    "workflow_stage",
]
