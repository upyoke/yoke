"""Validation for immutable declarative workflow definitions."""

from __future__ import annotations

from typing import Any, Mapping, Optional

from yoke_core.domain.workflow_definition_builders import (
    ENTRY_SURFACE_IDS,
    TASK_PRODUCING_PLANNING_SKILL_IDS,
    WORKFLOW_DEFINITION_SCHEMA_VERSION,
    WORKFLOW_FILE_BUDGET_OPTIONAL,
    WORKFLOW_FILE_BUDGET_REQUIRED,
    WORKFLOW_FILE_BUDGET_REQUIRED_PER_TASK,
    WORKFLOW_PATH_CLAIMS_OPTIONAL,
    WORKFLOW_PATH_CLAIMS_REQUIRED,
    WORKFLOW_PATH_CLAIMS_REQUIRED_PER_TASK,
    WORKFLOW_PATH_SURVEY_OPTIONAL,
    WORKFLOW_PATH_SURVEY_REQUIRED,
    WORKFLOW_DELIVERY_MERGE_FREE,
    WORKFLOW_QA_OPTIONAL,
    WORKFLOW_WORKTREES_NONE,
)
from yoke_core.domain.workflow_definition_graph_validation import (
    validate_skill_bindings,
    validate_transition_graph,
)
from yoke_core.domain.workflow_definition_validation_support import (
    WorkflowDefinitionError,
    require_exact_keys,
    require_mapping,
    require_nonempty_text,
    require_sequence,
)
from yoke_core.domain.workflow_stage_validation import validate_stages

_DEFINITION_KEYS = frozenset(
    {
        "schema_version",
        "stages",
        "terminal_stage_ids",
        "transitions",
        "entry_surfaces",
        "skill_bindings",
        "policies",
        "stage_mapping",
    }
)
_POLICY_VALUES = {
    "ownership": frozenset(
        {
            "single_item_claim",
            "item_claim_and_task_lanes",
            "session_item_and_document_claim",
            "exclusive_session_work_claim",
        }
    ),
    "path_claims": frozenset(
        {
            WORKFLOW_PATH_CLAIMS_REQUIRED,
            WORKFLOW_PATH_CLAIMS_REQUIRED_PER_TASK,
            WORKFLOW_PATH_CLAIMS_OPTIONAL,
        }
    ),
    "file_budget": frozenset(
        {
            WORKFLOW_FILE_BUDGET_REQUIRED,
            WORKFLOW_FILE_BUDGET_REQUIRED_PER_TASK,
            WORKFLOW_FILE_BUDGET_OPTIONAL,
        }
    ),
    "path_survey": frozenset(
        {WORKFLOW_PATH_SURVEY_REQUIRED, WORKFLOW_PATH_SURVEY_OPTIONAL}
    ),
    "worktrees": frozenset(
        {
            "single_implementation_lane",
            "worker_and_integration_lanes",
            "worker_lanes_optional_integration",
            WORKFLOW_WORKTREES_NONE,
        }
    ),
    "generated_children": frozenset({"none", "epic_tasks"}),
    "qa": frozenset(
        {
            "project_transition_defaults",
            "project_and_task_attachments",
            "item_attachments",
            "optional_item_attachment",
            WORKFLOW_QA_OPTIONAL,
        }
    ),
    "approvals": frozenset(
        {
            "definition_transitions",
            "optional_named_gate",
            "none",
        }
    ),
    "delivery": frozenset(
        {
            "release_stage",
            "continuous_slice_actions",
            "after_merge_action",
            WORKFLOW_DELIVERY_MERGE_FREE,
        }
    ),
}
#: Policy keys that no longer mean anything, accepted so that a definition
#: stored before they were retired still validates.
#:
#: Retiring a policy cannot rewrite the immutable rows that carry it, and the
#: bounded policy-default publication reads a stored definition, edits one key,
#: and publishes the result -- so refusing the retired key there would break
#: every operator edit on a universe still sitting on an older generation.
#: Nothing reads these, no new definition needs them, and taking a canon update
#: drops them: the merge sees Yoke removed the key and the universe left it
#: alone, so an inert key clears itself on the next update.
_RETIRED_POLICY_KEYS = frozenset({"parallelism"})
_APPROVAL_DEFAULT_KEYS = frozenset({"roles", "actors"})
_APPROVAL_ROLES = frozenset({"owner", "operator", "admin"})
_ITEM_POSTURE_VALUES = frozenset(
    {
        "approval",
        "approval_on_done",
        "deployment",
        "file_budget",
        "path_claims",
        "path_survey",
        "verification",
    }
)
_CORE_INVARIANT_KEYS = frozenset(
    {
        "core_invariants",
        "database_safety",
        "governed_migrations",
        "secret_handling",
    }
)


def _validate_approval_defaults(
    definition: Mapping[str, Any],
    policies: Mapping[str, Any],
) -> None:
    defaults = require_mapping(
        policies["approval_defaults"],
        "policies.approval_defaults",
    )
    target_stage_ids = {
        str(edge["to_stage_id"])
        for edge in require_sequence(definition["transitions"], "transitions")
    }
    for transition_id, raw_gate in defaults.items():
        path = f"policies.approval_defaults.{transition_id}"
        if not isinstance(transition_id, str) or transition_id not in target_stage_ids:
            raise WorkflowDefinitionError(
                f"{path} does not name a declared transition target"
            )
        gate = require_mapping(raw_gate, path)
        require_exact_keys(gate, _APPROVAL_DEFAULT_KEYS, path)
        roles = require_sequence(gate.get("roles"), f"{path}.roles")
        actors = require_sequence(gate.get("actors"), f"{path}.actors")
        if not roles and not actors:
            raise WorkflowDefinitionError(
                f"{path} must name at least one role or actor"
            )
        if any(not isinstance(role, str) for role in roles) or len(roles) != len(
            set(roles)
        ):
            raise WorkflowDefinitionError(f"{path}.roles must be unique")
        unknown_roles = set(roles) - _APPROVAL_ROLES
        if unknown_roles:
            raise WorkflowDefinitionError(
                f"{path}.roles has unknown values: {sorted(unknown_roles)}"
            )
        if any(
            isinstance(actor_id, bool) or not isinstance(actor_id, int) or actor_id <= 0
            for actor_id in actors
        ) or len(actors) != len(set(actors)):
            raise WorkflowDefinitionError(
                f"{path}.actors must be unique positive integer actor ids"
            )


def _validate_generated_children_producer(
    definition: Mapping[str, Any],
    policies: Mapping[str, Any],
) -> None:
    """Refuse promised decomposition no skill in this lifecycle produces.

    ``generated_children="epic_tasks"`` is a claim that this workflow's own
    planning phase writes ``epic_tasks`` rows. Only a task-producing planning
    skill does, so a definition declaring the policy without binding one
    validates today and then never populates anything -- readers downstream
    treat the empty task set as a finished decomposition rather than an absent
    one. Keyed on the bound skills rather than the workflow id, so the rule
    stays true of a workflow nobody has authored yet.
    """
    if policies["generated_children"] != "epic_tasks":
        return
    bound = {
        str(binding.get("skill_id"))
        for binding in require_sequence(
            definition.get("skill_bindings"), "skill_bindings"
        )
        if isinstance(binding, Mapping)
    }
    if not bound & TASK_PRODUCING_PLANNING_SKILL_IDS:
        raise WorkflowDefinitionError(
            "policies.generated_children=epic_tasks requires a skill binding "
            "that produces tasks: "
            f"{sorted(TASK_PRODUCING_PLANNING_SKILL_IDS)}"
        )


def _validate_policies(definition: Mapping[str, Any]) -> None:
    policies = require_mapping(definition.get("policies"), "policies")
    forbidden = set(policies) & _CORE_INVARIANT_KEYS
    if forbidden:
        raise WorkflowDefinitionError(
            f"core invariants cannot be workflow policy: {sorted(forbidden)}"
        )
    schema_version = int(definition["schema_version"])
    policy_values = dict(_POLICY_VALUES)
    if schema_version == 1:
        policy_values.pop("file_budget")
    required = (set(policy_values) - {"path_survey"}) | {"item_posture_allowlist"}
    allowed = required | {"path_survey", "approval_defaults"} | _RETIRED_POLICY_KEYS
    missing = required - set(policies)
    extra = set(policies) - allowed
    if missing or extra:
        raise WorkflowDefinitionError(
            f"policies keys mismatch; missing={sorted(missing)} unknown={sorted(extra)}"
        )
    for key, allowed in policy_values.items():
        if key in policies and policies[key] not in allowed:
            raise WorkflowDefinitionError(
                f"policies.{key} has unknown value {policies[key]!r}"
            )
    if policies.get("path_survey") == WORKFLOW_PATH_SURVEY_REQUIRED and policies[
        "path_claims"
    ] in {
        WORKFLOW_PATH_CLAIMS_REQUIRED,
        WORKFLOW_PATH_CLAIMS_REQUIRED_PER_TASK,
    }:
        raise WorkflowDefinitionError(
            "policies.path_survey=required cannot be combined with required "
            "policies.path_claims"
        )
    posture = require_sequence(
        policies["item_posture_allowlist"],
        "policies.item_posture_allowlist",
    )
    if len(posture) != len(set(posture)):
        raise WorkflowDefinitionError("policies.item_posture_allowlist must be unique")
    unknown = set(posture) - _ITEM_POSTURE_VALUES
    if unknown:
        raise WorkflowDefinitionError(
            f"policies.item_posture_allowlist has unknown values: {sorted(unknown)}"
        )
    if "file_budget" in posture and schema_version == 1:
        raise WorkflowDefinitionError("file_budget posture requires a schema-v2 policy")
    task_scoped = (
        policies["path_claims"] == WORKFLOW_PATH_CLAIMS_REQUIRED_PER_TASK
        or policies.get("file_budget") == WORKFLOW_FILE_BUDGET_REQUIRED_PER_TASK
    )
    if task_scoped and policies["generated_children"] != "epic_tasks":
        raise WorkflowDefinitionError(
            "required_per_task policies require generated_children=epic_tasks"
        )
    _validate_generated_children_producer(definition, policies)
    if "approval_defaults" in policies:
        _validate_approval_defaults(definition, policies)


def _validate_structural_change(
    definition: Mapping[str, Any],
    previous: Optional[Mapping[str, Any]],
    stage_ids: list[str],
) -> None:
    if previous is None:
        return
    previous_ids = [
        str(stage["id"])
        for stage in require_sequence(previous.get("stages"), "previous.stages")
    ]
    structural = previous_ids != stage_ids
    mapping = definition.get("stage_mapping")
    if not structural:
        if mapping is not None:
            raise WorkflowDefinitionError(
                "stage_mapping is only valid for structural stage changes"
            )
        return
    mapping = require_mapping(mapping, "stage_mapping")
    if set(mapping) != set(previous_ids):
        raise WorkflowDefinitionError(
            "stage_mapping must map every previous stage id exactly once"
        )
    unknown = set(mapping.values()) - set(stage_ids)
    if unknown:
        raise WorkflowDefinitionError(
            f"stage_mapping targets undeclared stages: {sorted(unknown)}"
        )


def validate_workflow_definition(
    definition: Mapping[str, Any],
    *,
    previous: Optional[Mapping[str, Any]] = None,
) -> None:
    """Raise :class:`WorkflowDefinitionError` unless the definition is valid."""
    value = require_mapping(definition, "definition")
    require_exact_keys(value, _DEFINITION_KEYS, "definition")
    if value.get("schema_version") not in {
        1,
        3,
        WORKFLOW_DEFINITION_SCHEMA_VERSION,
    }:
        raise WorkflowDefinitionError("definition.schema_version is unsupported")
    stage_ids, stage_id_set = validate_stages(value)
    edges = validate_transition_graph(value, stage_ids, stage_id_set)
    surfaces = [
        require_nonempty_text(surface, "entry_surfaces[]")
        for surface in require_sequence(value.get("entry_surfaces"), "entry_surfaces")
    ]
    if not surfaces or len(surfaces) != len(set(surfaces)):
        raise WorkflowDefinitionError("entry_surfaces must be a non-empty unique list")
    unknown_surfaces = set(surfaces) - ENTRY_SURFACE_IDS
    if unknown_surfaces:
        raise WorkflowDefinitionError(
            f"entry_surfaces has unknown values: {sorted(unknown_surfaces)}"
        )
    validate_skill_bindings(value, stage_ids, edges)
    _validate_policies(value)
    _validate_structural_change(value, previous, stage_ids)


__all__ = ["WorkflowDefinitionError", "validate_workflow_definition"]
