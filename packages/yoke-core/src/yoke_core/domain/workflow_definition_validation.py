"""Validation for immutable declarative workflow definitions."""

from __future__ import annotations

import re
from typing import Any, Mapping, Optional

from yoke_core.domain.workflow_definition_builders import (
    ENTRY_SURFACE_IDS,
    WORKFLOW_DEFINITION_SCHEMA_VERSION,
    WORKFLOW_FILE_BUDGET_OPTIONAL,
    WORKFLOW_FILE_BUDGET_REQUIRED,
    WORKFLOW_FILE_BUDGET_REQUIRED_PER_TASK,
    WORKFLOW_PATH_CLAIMS_OPTIONAL,
    WORKFLOW_PATH_CLAIMS_REQUIRED,
    WORKFLOW_PATH_CLAIMS_REQUIRED_PER_TASK,
)
from yoke_core.domain.workflow_definition_graph_validation import (
    validate_executor_bindings,
    validate_transition_graph,
)
from yoke_core.domain.workflow_definition_validation_support import (
    WorkflowDefinitionError,
    require_exact_keys,
    require_mapping,
    require_nonempty_text,
    require_sequence,
)
from yoke_core.domain.workflow_gate_catalog import workflow_gate_catalog

_ID_RE = re.compile(r"^[a-z][a-z0-9-]*$")
_DEFINITION_KEYS = frozenset({
    "schema_version",
    "stages",
    "terminal_stage_ids",
    "transitions",
    "entry_surfaces",
    "executor_bindings",
    "policies",
    "stage_mapping",
})
_STAGE_KEYS = frozenset({"id", "label", "description", "gates"})
_GATE_REF_KEYS = frozenset({"id", "mode"})
_POLICY_VALUES = {
    "ownership": frozenset({
        "single_item_claim",
        "item_claim_and_task_lanes",
        "session_item_and_document_claim",
        "exclusive_session_work_claim",
    }),
    "path_claims": frozenset({
        WORKFLOW_PATH_CLAIMS_REQUIRED,
        WORKFLOW_PATH_CLAIMS_REQUIRED_PER_TASK,
        WORKFLOW_PATH_CLAIMS_OPTIONAL,
    }),
    "file_budget": frozenset({
        WORKFLOW_FILE_BUDGET_REQUIRED,
        WORKFLOW_FILE_BUDGET_REQUIRED_PER_TASK,
        WORKFLOW_FILE_BUDGET_OPTIONAL,
    }),
    "worktrees": frozenset({
        "single_implementation_lane",
        "worker_and_integration_lanes",
        "worker_lanes_optional_integration",
    }),
    "parallelism": frozenset({
        "inside_item",
        "task_graph",
        "maximum_safe_slices",
        "none",
    }),
    "generated_children": frozenset({"none", "epic_tasks"}),
    "qa": frozenset({
        "project_transition_defaults",
        "project_and_task_attachments",
        "item_attachments",
        "optional_item_attachment",
    }),
    "approvals": frozenset({
        "definition_transitions",
        "optional_named_gate",
        "none",
    }),
    "delivery": frozenset({
        "release_stage",
        "continuous_slice_actions",
        "after_merge_action",
    }),
}
_APPROVAL_DEFAULT_KEYS = frozenset({"roles", "actors"})
_APPROVAL_ROLES = frozenset({"owner", "operator", "admin"})
_ITEM_POSTURE_VALUES = frozenset({
    "approval",
    "approval_on_done",
    "deployment",
    "file_budget",
    "path_claims",
    "verification",
})
_CORE_INVARIANT_KEYS = frozenset({
    "core_invariants",
    "database_safety",
    "governed_migrations",
    "secret_handling",
})


def _validate_stages(
    definition: Mapping[str, Any],
) -> tuple[list[str], set[str]]:
    stages = require_sequence(definition.get("stages"), "stages")
    if len(stages) < 2:
        raise WorkflowDefinitionError("stages must contain at least two rows")
    ids: list[str] = []
    labels: list[str] = []
    catalog = {row["id"]: row for row in workflow_gate_catalog()}
    gate_pairs: set[tuple[str, Optional[str]]] = set()
    for index, raw_stage in enumerate(stages):
        path = f"stages[{index}]"
        stage = require_mapping(raw_stage, path)
        require_exact_keys(stage, _STAGE_KEYS, path)
        stage_id = require_nonempty_text(stage.get("id"), f"{path}.id")
        if not _ID_RE.fullmatch(stage_id):
            raise WorkflowDefinitionError(
                f"{path}.id must use lowercase kebab-case"
            )
        ids.append(stage_id)
        labels.append(require_nonempty_text(stage.get("label"), f"{path}.label"))
        if "description" in stage:
            require_nonempty_text(stage["description"], f"{path}.description")
        for gate_index, raw_gate in enumerate(
            require_sequence(stage.get("gates"), f"{path}.gates")
        ):
            gate_path = f"{path}.gates[{gate_index}]"
            gate = require_mapping(raw_gate, gate_path)
            require_exact_keys(gate, _GATE_REF_KEYS, gate_path)
            gate_id = require_nonempty_text(gate.get("id"), f"{gate_path}.id")
            catalog_row = catalog.get(gate_id)
            if catalog_row is None:
                raise WorkflowDefinitionError(
                    f"{gate_path}.id references unknown gate {gate_id!r}"
                )
            mode = gate.get("mode")
            valid_modes = {row["id"] for row in catalog_row["modes"]}
            if valid_modes:
                mode = require_nonempty_text(mode, f"{gate_path}.mode")
                if mode not in valid_modes:
                    raise WorkflowDefinitionError(
                        f"{gate_path}.mode references unknown mode {mode!r}"
                    )
            elif mode is not None:
                raise WorkflowDefinitionError(
                    f"{gate_path}.mode is not supported by gate {gate_id!r}"
                )
            pair = (gate_id, mode)
            if pair in gate_pairs:
                raise WorkflowDefinitionError(
                    f"{path}.gates repeats {gate_id!r} mode {mode!r}"
                )
            gate_pairs.add(pair)
        gate_pairs.clear()
    if len(ids) != len(set(ids)):
        raise WorkflowDefinitionError("stage ids must be unique")
    if len(labels) != len({label.casefold() for label in labels}):
        raise WorkflowDefinitionError("stage labels must be unique")
    return ids, set(ids)


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
        if (
            not isinstance(transition_id, str)
            or transition_id not in target_stage_ids
        ):
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
        if (
            any(not isinstance(role, str) for role in roles)
            or len(roles) != len(set(roles))
        ):
            raise WorkflowDefinitionError(f"{path}.roles must be unique")
        unknown_roles = set(roles) - _APPROVAL_ROLES
        if unknown_roles:
            raise WorkflowDefinitionError(
                f"{path}.roles has unknown values: {sorted(unknown_roles)}"
            )
        if (
            any(
                isinstance(actor_id, bool)
                or not isinstance(actor_id, int)
                or actor_id <= 0
                for actor_id in actors
            )
            or len(actors) != len(set(actors))
        ):
            raise WorkflowDefinitionError(
                f"{path}.actors must be unique positive integer actor ids"
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
    required = set(policy_values) | {"item_posture_allowlist"}
    allowed = required | {"approval_defaults"}
    missing = required - set(policies)
    extra = set(policies) - allowed
    if missing or extra:
        raise WorkflowDefinitionError(
            f"policies keys mismatch; missing={sorted(missing)} "
            f"unknown={sorted(extra)}"
        )
    for key, allowed in policy_values.items():
        if policies[key] not in allowed:
            raise WorkflowDefinitionError(
                f"policies.{key} has unknown value {policies[key]!r}"
            )
    posture = require_sequence(
        policies["item_posture_allowlist"],
        "policies.item_posture_allowlist",
    )
    if len(posture) != len(set(posture)):
        raise WorkflowDefinitionError(
            "policies.item_posture_allowlist must be unique"
        )
    unknown = set(posture) - _ITEM_POSTURE_VALUES
    if unknown:
        raise WorkflowDefinitionError(
            "policies.item_posture_allowlist has unknown values: "
            f"{sorted(unknown)}"
        )
    if "file_budget" in posture and schema_version == 1:
        raise WorkflowDefinitionError(
            "file_budget posture requires a schema-v2 policy"
        )
    task_scoped = (
        policies["path_claims"] == WORKFLOW_PATH_CLAIMS_REQUIRED_PER_TASK
        or policies.get("file_budget") == WORKFLOW_FILE_BUDGET_REQUIRED_PER_TASK
    )
    if task_scoped and policies["generated_children"] != "epic_tasks":
        raise WorkflowDefinitionError(
            "required_per_task policies require generated_children=epic_tasks"
        )
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
        for stage in require_sequence(
            previous.get("stages"), "previous.stages"
        )
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
        WORKFLOW_DEFINITION_SCHEMA_VERSION,
    }:
        raise WorkflowDefinitionError(
            "definition.schema_version is unsupported"
        )
    stage_ids, stage_id_set = _validate_stages(value)
    edges = validate_transition_graph(value, stage_ids, stage_id_set)
    surfaces = [
        require_nonempty_text(surface, "entry_surfaces[]")
        for surface in require_sequence(
            value.get("entry_surfaces"), "entry_surfaces"
        )
    ]
    if not surfaces or len(surfaces) != len(set(surfaces)):
        raise WorkflowDefinitionError(
            "entry_surfaces must be a non-empty unique list"
        )
    unknown_surfaces = set(surfaces) - ENTRY_SURFACE_IDS
    if unknown_surfaces:
        raise WorkflowDefinitionError(
            f"entry_surfaces has unknown values: {sorted(unknown_surfaces)}"
        )
    validate_executor_bindings(value, stage_ids, edges)
    _validate_policies(value)
    _validate_structural_change(value, previous, stage_ids)


__all__ = ["WorkflowDefinitionError", "validate_workflow_definition"]
