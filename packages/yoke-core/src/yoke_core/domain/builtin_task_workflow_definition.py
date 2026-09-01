"""Current definition for the floor task workflow.

Editing a definition here changes what NEW items pin. It does not, and
must not, change any generation already published: canon is append-only.
After changing this definition, append the new generation to the canon.
"""

from __future__ import annotations

from yoke_core.domain.workflow_definition_builders import (
    WORKFLOW_DELIVERY_MERGE_FREE,
    WORKFLOW_FILE_BUDGET_OPTIONAL,
    WORKFLOW_PATH_CLAIMS_OPTIONAL,
    WORKFLOW_PATH_SURVEY_OPTIONAL,
    WORKFLOW_QA_OPTIONAL,
    WORKFLOW_WORKTREES_NONE,
    definition_fixture,
    skill_binding,
    gate_ref,
    workflow_stage,
)
from yoke_core.domain.workflow_gate_catalog import (
    GATE_FLOOR_ATTESTATION,
    GATE_WORK_CLAIM_ACTIVATION,
)

TASK_WORKFLOW_DEFINITION = definition_fixture(
    workflow_id="task",
    name="Task",
    description=(
        "A floor workflow for folder-only and non-code work — idea, "
        "implementing, done; no git lane, no merge, done is the floor "
        "attestation."
    ),
    stages=(
        workflow_stage("idea", "idea"),
        workflow_stage(
            "implementing",
            "implementing",
            (gate_ref(GATE_WORK_CLAIM_ACTIVATION),),
            "The executing session takes the exclusive work claim and "
            "performs the work without a git lane.",
        ),
        workflow_stage(
            "done",
            "done",
            (gate_ref(GATE_FLOOR_ATTESTATION),),
            "The floor attestation is recorded — the agent account plus "
            "observed changes, with no merge SHA required.",
        ),
    ),
    entry_surfaces=("harness_skill", "cli", "web_form", "promotion"),
    skill_bindings=(
        skill_binding("advance", "idea", "implementing"),
        skill_binding("dash", "implementing", "done"),
    ),
    policies={
        "ownership": "exclusive_session_work_claim",
        "file_budget": WORKFLOW_FILE_BUDGET_OPTIONAL,
        "path_claims": WORKFLOW_PATH_CLAIMS_OPTIONAL,
        "path_survey": WORKFLOW_PATH_SURVEY_OPTIONAL,
        "worktrees": WORKFLOW_WORKTREES_NONE,
        "generated_children": "none",
        "qa": WORKFLOW_QA_OPTIONAL,
        "approvals": "none",
        "delivery": WORKFLOW_DELIVERY_MERGE_FREE,
        "item_posture_allowlist": [],
    },
    approval_defaults={},
)

__all__ = ["TASK_WORKFLOW_DEFINITION"]
