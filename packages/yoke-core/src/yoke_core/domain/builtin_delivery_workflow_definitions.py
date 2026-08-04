"""Current definitions for the Issue and Epic delivery workflows.

Editing a definition here changes what NEW items pin. It does not, and
must not, change any generation already published: canon is append-only,
so a change appends generation N+1 and never alters N or earlier.

After changing a definition, append the new generation to the canon in
``builtin_workflow_canon/`` and update both pins in
``runtime/api/domain/test_builtin_workflow_canon.py``. History used to be
derived from this file by subtracting remembered fields, so editing here
silently rewrote it and the fleet refused to boot; see
``docs/archive/decisions/workflow-definitions-are-universe-data.md``.
"""

from __future__ import annotations

from yoke_core.domain.workflow_definition_builders import (
    BUILTIN_WORKFLOW_PREFERRED_VERSION,
    WORKFLOW_FILE_BUDGET_REQUIRED,
    WORKFLOW_FILE_BUDGET_REQUIRED_PER_TASK,
    WORKFLOW_PATH_CLAIMS_REQUIRED,
    WORKFLOW_PATH_CLAIMS_REQUIRED_PER_TASK,
    definition_fixture,
    skill_binding,
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
    workflow_stage("idea", "idea"),
    workflow_stage(
        "refining-idea",
        "refining idea",
        (
            gate_ref(GATE_DB_CLAIM_PROSE),
            gate_ref(GATE_DB_MUTATION, "joint"),
        ),
    ),
    workflow_stage(
        "refined-idea",
        "refined idea",
        (
            gate_ref(GATE_DB_CLAIM_PROSE),
            gate_ref(GATE_ARCHITECTURE_IMPACT),
        ),
    ),
)
def _reviewing_implementation_stage(description: str) -> dict:
    return workflow_stage(
        "reviewing-implementation",
        "reviewing implementation",
        (
            gate_ref(GATE_DB_CLAIM_PROSE),
            gate_ref(GATE_DB_MUTATION, "evidence"),
            gate_ref(GATE_ARCHITECTURE_IMPACT),
        ),
        description,
    )


_IMPLEMENTATION_CLOSE_STAGES = (
    workflow_stage(
        "reviewed-implementation",
        "reviewed implementation",
        (
            gate_ref(GATE_ARCHITECTURE_IMPACT),
            gate_ref(GATE_PATH_CLAIM_BOUNDARY),
            gate_ref(GATE_QA_VERIFICATION),
        ),
    ),
    workflow_stage(
        "polishing-implementation",
        "polishing implementation",
        (gate_ref(GATE_ARCHITECTURE_IMPACT),),
    ),
    workflow_stage(
        "implemented",
        "implemented",
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
        "release",
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
        "One scoped implementation lane with planning, review, QA and delivery."
    ),
    version=BUILTIN_WORKFLOW_PREFERRED_VERSION,
    stages=(
        *_INTAKE_STAGES,
        workflow_stage(
            "implementing",
            "implementing",
            (
                gate_ref(GATE_CHECK_HARD_BLOCKS),
                gate_ref(GATE_CLAIM_ACTIVATION),
                gate_ref(GATE_ARCHITECTURE_IMPACT),
            ),
            "One implementation lane in an isolated worktree; the engineer "
            "builds against the spec and acceptance criteria.",
        ),
        _reviewing_implementation_stage(
            "The in-worktree review loop — the work is checked against the "
            "acceptance criteria before it can leave the lane.",
        ),
        *_IMPLEMENTATION_CLOSE_STAGES,
        workflow_stage(
            "done",
            "done",
            (
                gate_ref(GATE_ARCHITECTURE_IMPACT),
                gate_ref(GATE_QA_VERIFICATION),
            ),
            "Merged and delivered through the selected flow; the item closes.",
        ),
    ),
    entry_surfaces=("harness_skill", "promotion"),
    skill_bindings=(
        skill_binding("refine", "idea", "refined-idea"),
        skill_binding(
            "advance", "refined-idea", "reviewed-implementation",
        ),
        skill_binding(
            "polish", "reviewed-implementation", "implemented",
        ),
        skill_binding("usher", "implemented", "done"),
    ),
    policies={
        "ownership": "single_item_claim",
        "file_budget": WORKFLOW_FILE_BUDGET_REQUIRED,
        "path_claims": WORKFLOW_PATH_CLAIMS_REQUIRED,
        "worktrees": "single_implementation_lane",
        "parallelism": "inside_item",
        "generated_children": "none",
        "qa": "project_transition_defaults",
        "approvals": "definition_transitions",
        "delivery": "release_stage",
        "item_posture_allowlist": ["verification", "approval", "deployment"],
    },
    approval_defaults={},
)

EPIC_WORKFLOW_DEFINITION = definition_fixture(
    workflow_id="epic",
    name="Epic",
    description=(
        "Planned task decomposition with parallel worktree lanes and an "
        "integration boundary."
    ),
    version=BUILTIN_WORKFLOW_PREFERRED_VERSION,
    stages=(
        *_INTAKE_STAGES,
        workflow_stage(
            "planning",
            "planning",
            (gate_ref(GATE_ARCHITECTURE_IMPACT),),
            "The Architect decomposes the epic into tasks — file budgets, "
            "interface contracts, and worktree lanes.",
        ),
        workflow_stage(
            "plan-drafted",
            "plan drafted",
            (gate_ref(GATE_ARCHITECTURE_IMPACT),),
            "The task plan is drafted and awaits the refine pass before it "
            "can be committed.",
        ),
        workflow_stage(
            "refining-plan",
            "refining plan",
            (gate_ref(GATE_ARCHITECTURE_IMPACT),),
            "The plan is refined against the spec — simplify lenses and "
            "readiness repair — before it commits.",
        ),
        workflow_stage(
            "planned",
            "planned",
            (
                gate_ref(GATE_DB_CLAIM_PROSE),
                gate_ref(GATE_ARCHITECTURE_IMPACT),
                gate_ref(GATE_PLAN_SIMULATION),
            ),
            "The plan is committed and has passed the simulator; the tasks "
            "are ready to fan out into worktree lanes.",
        ),
        workflow_stage(
            "implementing",
            "implementing",
            (
                gate_ref(GATE_CHECK_HARD_BLOCKS),
                gate_ref(GATE_CLAIM_ACTIVATION),
                gate_ref(GATE_ARCHITECTURE_IMPACT),
            ),
            "Parallel task lanes execute against the plan, each in its own "
            "worktree, with the main session integrating.",
        ),
        _reviewing_implementation_stage(
            "Integrated task work is reviewed across the whole epic before "
            "the set can advance.",
        ),
        *_IMPLEMENTATION_CLOSE_STAGES,
        workflow_stage(
            "done",
            "done",
            (
                gate_ref(GATE_ARCHITECTURE_IMPACT),
                gate_ref(GATE_QA_VERIFICATION),
            ),
            "Every task merged, integrated, and delivered; the epic closes.",
        ),
    ),
    entry_surfaces=("harness_skill",),
    skill_bindings=(
        skill_binding("refine", "idea", "refined-idea"),
        skill_binding("shepherd", "refined-idea", "plan-drafted"),
        skill_binding("refine", "plan-drafted", "planned"),
        skill_binding("conduct", "planned", "reviewed-implementation"),
        skill_binding(
            "polish", "reviewed-implementation", "implemented",
        ),
        skill_binding("usher", "implemented", "done"),
    ),
    policies={
        "ownership": "item_claim_and_task_lanes",
        "file_budget": WORKFLOW_FILE_BUDGET_REQUIRED_PER_TASK,
        "path_claims": WORKFLOW_PATH_CLAIMS_REQUIRED_PER_TASK,
        "worktrees": "worker_and_integration_lanes",
        "parallelism": "task_graph",
        "generated_children": "epic_tasks",
        "qa": "project_and_task_attachments",
        "approvals": "definition_transitions",
        "delivery": "release_stage",
        "item_posture_allowlist": ["verification", "approval", "deployment"],
    },
    approval_defaults={},
)

__all__ = ["EPIC_WORKFLOW_DEFINITION", "ISSUE_WORKFLOW_DEFINITION"]
