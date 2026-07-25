"""First definitions for the Issue and Epic delivery workflows."""

from __future__ import annotations

from yoke_core.domain.workflow_definition_builders import (
    definition_fixture,
    executor_binding,
    gate_ref,
    workflow_stage,
)
from yoke_core.domain.workflow_gate_catalog import (
    GATE_ARCHITECTURE_IMPACT,
    GATE_CHECK_HARD_BLOCKS,
    GATE_CLAIM_ACTIVATION,
    GATE_DB_CLAIM_PROSE,
    GATE_DB_MUTATION,
    GATE_PATH_CLAIM_BOUNDARY,
    GATE_PLAN_SIMULATION,
    GATE_QA_VERIFICATION,
)

_INTAKE_STAGES = (
    workflow_stage("idea", "Idea"),
    workflow_stage(
        "refining-idea",
        "Refining idea",
        (
            gate_ref(GATE_DB_CLAIM_PROSE),
            gate_ref(GATE_DB_MUTATION, "joint"),
        ),
    ),
    workflow_stage(
        "refined-idea",
        "Refined idea",
        (
            gate_ref(GATE_DB_CLAIM_PROSE),
            gate_ref(GATE_ARCHITECTURE_IMPACT),
        ),
    ),
)
_IMPLEMENTATION_CLOSE_STAGES = (
    workflow_stage(
        "reviewing-implementation",
        "Reviewing implementation",
        (
            gate_ref(GATE_DB_CLAIM_PROSE),
            gate_ref(GATE_DB_MUTATION, "evidence"),
            gate_ref(GATE_ARCHITECTURE_IMPACT),
        ),
    ),
    workflow_stage(
        "reviewed-implementation",
        "Reviewed implementation",
        (
            gate_ref(GATE_ARCHITECTURE_IMPACT),
            gate_ref(GATE_PATH_CLAIM_BOUNDARY),
            gate_ref(GATE_QA_VERIFICATION),
        ),
    ),
    workflow_stage(
        "polishing-implementation",
        "Polishing implementation",
        (gate_ref(GATE_ARCHITECTURE_IMPACT),),
    ),
    workflow_stage(
        "implemented",
        "Implemented",
        (
            gate_ref(GATE_DB_CLAIM_PROSE),
            gate_ref(GATE_DB_MUTATION, "polish"),
            gate_ref(GATE_ARCHITECTURE_IMPACT),
            gate_ref(GATE_PATH_CLAIM_BOUNDARY),
            gate_ref(GATE_QA_VERIFICATION),
        ),
    ),
    workflow_stage(
        "release",
        "Release",
        (
            gate_ref(GATE_ARCHITECTURE_IMPACT),
            gate_ref(GATE_PATH_CLAIM_BOUNDARY),
            gate_ref(GATE_QA_VERIFICATION),
        ),
    ),
)

ISSUE_WORKFLOW_DEFINITION = definition_fixture(
    workflow_id="issue",
    name="Issue",
    description=(
        "One scoped implementation lane with planning, review, QA, and delivery."
    ),
    stages=(
        *_INTAKE_STAGES,
        workflow_stage(
            "implementing",
            "Implementing",
            (
                gate_ref(GATE_CHECK_HARD_BLOCKS),
                gate_ref(GATE_CLAIM_ACTIVATION),
                gate_ref(GATE_ARCHITECTURE_IMPACT),
            ),
            "One implementation lane builds against the item's acceptance criteria.",
        ),
        *_IMPLEMENTATION_CLOSE_STAGES,
        workflow_stage(
            "done",
            "Done",
            (
                gate_ref(GATE_ARCHITECTURE_IMPACT),
                gate_ref(GATE_QA_VERIFICATION),
            ),
            "The item is merged, delivered, and closed.",
        ),
    ),
    entry_surfaces=("harness_skill", "promotion"),
    executor_bindings=(
        executor_binding("refine", "idea", "refined-idea"),
        executor_binding(
            "advance", "refined-idea", "reviewed-implementation",
        ),
        executor_binding(
            "polish", "reviewed-implementation", "implemented",
        ),
        executor_binding("usher", "implemented", "done"),
    ),
    policies={
        "ownership": "single_item_claim",
        "path_claims": "required",
        "worktrees": "single_implementation_lane",
        "parallelism": "inside_item",
        "generated_children": "none",
        "qa": "project_transition_defaults",
        "approvals": "definition_transitions",
        "delivery": "release_stage",
        "item_posture_allowlist": ["verification", "approval", "deployment"],
    },
)

EPIC_WORKFLOW_DEFINITION = definition_fixture(
    workflow_id="epic",
    name="Epic",
    description=(
        "Planned task decomposition with parallel worktree lanes and an "
        "integration boundary."
    ),
    stages=(
        *_INTAKE_STAGES,
        workflow_stage(
            "planning",
            "Planning",
            (gate_ref(GATE_ARCHITECTURE_IMPACT),),
            "The plan is decomposed into tasks, interfaces, budgets, and lanes.",
        ),
        workflow_stage(
            "plan-drafted",
            "Plan drafted",
            (gate_ref(GATE_ARCHITECTURE_IMPACT),),
        ),
        workflow_stage(
            "refining-plan",
            "Refining plan",
            (gate_ref(GATE_ARCHITECTURE_IMPACT),),
        ),
        workflow_stage(
            "planned",
            "Planned",
            (
                gate_ref(GATE_DB_CLAIM_PROSE),
                gate_ref(GATE_ARCHITECTURE_IMPACT),
                gate_ref(GATE_PLAN_SIMULATION),
            ),
            "The committed task plan has passed cross-task simulation.",
        ),
        workflow_stage(
            "implementing",
            "Implementing",
            (
                gate_ref(GATE_CHECK_HARD_BLOCKS),
                gate_ref(GATE_CLAIM_ACTIVATION),
                gate_ref(GATE_ARCHITECTURE_IMPACT),
            ),
            "Task lanes execute in parallel and the main session integrates them.",
        ),
        *_IMPLEMENTATION_CLOSE_STAGES,
        workflow_stage(
            "done",
            "Done",
            (
                gate_ref(GATE_ARCHITECTURE_IMPACT),
                gate_ref(GATE_QA_VERIFICATION),
            ),
            "Every task is integrated, delivered, and closed.",
        ),
    ),
    entry_surfaces=("harness_skill",),
    executor_bindings=(
        executor_binding("refine", "idea", "refined-idea"),
        executor_binding("shepherd", "refined-idea", "plan-drafted"),
        executor_binding("refine", "plan-drafted", "planned"),
        executor_binding("conduct", "planned", "reviewed-implementation"),
        executor_binding(
            "polish", "reviewed-implementation", "implemented",
        ),
        executor_binding("usher", "implemented", "done"),
    ),
    policies={
        "ownership": "item_claim_and_task_lanes",
        "path_claims": "required_per_task",
        "worktrees": "worker_and_integration_lanes",
        "parallelism": "task_graph",
        "generated_children": "epic_tasks",
        "qa": "project_and_task_attachments",
        "approvals": "definition_transitions",
        "delivery": "release_stage",
        "item_posture_allowlist": ["verification", "approval", "deployment"],
    },
)

__all__ = ["EPIC_WORKFLOW_DEFINITION", "ISSUE_WORKFLOW_DEFINITION"]
