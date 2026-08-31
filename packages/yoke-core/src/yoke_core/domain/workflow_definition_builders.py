"""Vocabulary and small builders for declarative workflow definitions."""

from __future__ import annotations

from typing import Any, Dict, Iterable, Optional, Sequence

from yoke_contracts.item_worktrees import WORKFLOW_WORKTREES_NONE
from yoke_contracts.lifecycle_status import (
    LEGACY_STATUS_BUCKETS,
    LEGACY_STATUS_GLYPHS,
)

WORKFLOW_DEFINITION_SCHEMA_VERSION = 4
WORKFLOW_FILE_BUDGET_OPTIONAL = "optional"
WORKFLOW_FILE_BUDGET_REQUIRED = "required"
WORKFLOW_FILE_BUDGET_REQUIRED_PER_TASK = "required_per_task"
WORKFLOW_PATH_CLAIMS_OPTIONAL = "optional"
WORKFLOW_PATH_CLAIMS_REQUIRED = "required"
WORKFLOW_PATH_CLAIMS_REQUIRED_PER_TASK = "required_per_task"
WORKFLOW_PATH_SURVEY_OPTIONAL = WORKFLOW_PATH_CLAIMS_OPTIONAL
WORKFLOW_PATH_SURVEY_REQUIRED = WORKFLOW_PATH_CLAIMS_REQUIRED
WORKFLOW_DELIVERY_MERGE_FREE = "merge_free"
WORKFLOW_QA_OPTIONAL = "optional"
REGISTERED_WORKFLOW_SKILL_IDS = frozenset(
    {
        "advance",
        "blitz",
        "conduct",
        "dash",
        "polish",
        "refine",
        "shepherd",
        "usher",
    }
)
IMPLEMENTATION_WORKFLOW_SKILL_IDS = frozenset(
    {
        "advance",
        "blitz",
        "conduct",
        "dash",
    }
)
#: Skills whose planning phase writes ``epic_tasks`` rows. A definition may only
#: declare ``generated_children="epic_tasks"`` when it binds one of these, or it
#: promises decomposition no skill in its own lifecycle ever produces.
TASK_PRODUCING_PLANNING_SKILL_IDS = frozenset({"shepherd"})
ENTRY_SURFACE_IDS = frozenset(
    {
        "cli",
        "harness_skill",
        "promotion",
        "web_form",
    }
)


def with_generated_epic_tasks(definition: Dict[str, Any]) -> Dict[str, Any]:
    """Declare epic-task generation together with the skill that writes them.

    The two facts are one decision: a definition that generates tasks must bind
    a skill whose planning phase produces them, or it promises decomposition
    nothing performs. Callers that only mean "make this generate tasks" get the
    producing binding as part of the same edit rather than discovering the
    refusal afterwards. Bindings union their coverage, so adding one spanning
    the whole lifecycle never invalidates the coverage the definition already
    had.
    """
    # Replaces the two containers rather than mutating them, because callers
    # routinely hold a shallow copy of a shared fixture: appending to the
    # original list would edit that fixture for everyone who reads it later,
    # which shows up as an unrelated definition mysteriously failing to be
    # recognized. Only the mapping the caller owns is written through.
    policies = dict(definition["policies"])
    policies["generated_children"] = "epic_tasks"
    definition["policies"] = policies
    bindings = [dict(binding) for binding in definition["skill_bindings"]]
    bound = {str(binding["skill_id"]) for binding in bindings}
    if not bound & TASK_PRODUCING_PLANNING_SKILL_IDS:
        stage_ids = [str(stage["id"]) for stage in definition["stages"]]
        bindings.append(
            {
                "skill_id": sorted(TASK_PRODUCING_PLANNING_SKILL_IDS)[0],
                "from_stage_id": stage_ids[0],
                "through_stage_id": stage_ids[-1],
            }
        )
    definition["skill_bindings"] = bindings
    return definition


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


def skill_binding(
    skill_id: str,
    from_stage_id: str,
    through_stage_id: str,
) -> Dict[str, str]:
    """Bind a registered skill to a contiguous lifecycle segment."""
    return {
        "skill_id": skill_id,
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
    skill_bindings: Sequence[Dict[str, str]],
    policies: Dict[str, Any],
    approval_defaults: Optional[Dict[str, Any]] = None,
    schema_version: int = WORKFLOW_DEFINITION_SCHEMA_VERSION,
) -> Dict[str, Any]:
    """Build one built-in workflow fixture: its identity and its definition.

    Carries no version number. A version is a position in some universe's own
    sequence, not a property of the content, so the number a definition ends up
    stored under is that universe's to decide.
    """
    normalized_stages = [dict(stage) for stage in stages]
    if schema_version >= 4:
        for stage in normalized_stages:
            stage_id = str(stage["id"])
            stage["glyph"] = LEGACY_STATUS_GLYPHS.get(stage_id, "▫")
            stage["board_bucket"] = LEGACY_STATUS_BUCKETS.get(stage_id, "unknown")
    stage_ids = [stage["id"] for stage in normalized_stages]
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
        "definition": {
            "schema_version": schema_version,
            "stages": normalized_stages,
            "terminal_stage_ids": [stage_ids[-1]],
            "transitions": [
                {"from_stage_id": before, "to_stage_id": after}
                for before, after in zip(stage_ids, stage_ids[1:])
            ],
            "entry_surfaces": list(entry_surfaces),
            "skill_bindings": list(skill_bindings),
            "policies": normalized_policies,
        },
    }


__all__ = [
    "ENTRY_SURFACE_IDS",
    "IMPLEMENTATION_WORKFLOW_SKILL_IDS",
    "REGISTERED_WORKFLOW_SKILL_IDS",
    "TASK_PRODUCING_PLANNING_SKILL_IDS",
    "with_generated_epic_tasks",
    "WORKFLOW_DEFINITION_SCHEMA_VERSION",
    "WORKFLOW_FILE_BUDGET_OPTIONAL",
    "WORKFLOW_FILE_BUDGET_REQUIRED",
    "WORKFLOW_FILE_BUDGET_REQUIRED_PER_TASK",
    "WORKFLOW_PATH_CLAIMS_OPTIONAL",
    "WORKFLOW_PATH_CLAIMS_REQUIRED",
    "WORKFLOW_PATH_CLAIMS_REQUIRED_PER_TASK",
    "WORKFLOW_PATH_SURVEY_OPTIONAL",
    "WORKFLOW_PATH_SURVEY_REQUIRED",
    "WORKFLOW_WORKTREES_NONE",
    "WORKFLOW_DELIVERY_MERGE_FREE",
    "WORKFLOW_QA_OPTIONAL",
    "definition_fixture",
    "skill_binding",
    "gate_ref",
    "workflow_stage",
]
