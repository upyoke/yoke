"""Previously published Blitz and Dash workflow definitions."""

from __future__ import annotations

from yoke_core.domain.workflow_definition_builders import (
    definition_fixture,
    skill_binding,
    gate_ref,
    workflow_stage,
)
from yoke_core.domain.workflow_gate_catalog import (
    GATE_ARCHITECTURE_IMPACT,
    GATE_CONFLICT_SURVEY,
    GATE_DASH_EVIDENCE,
    GATE_DB_CLAIM_PROSE,
    GATE_DB_MUTATION,
    GATE_DOC_CLAIM_ACTIVATION,
    GATE_DOC_COMPLETION,
    GATE_QA_VERIFICATION,
    GATE_WORK_CLAIM_ACTIVATION,
)

_REFINEMENT_STAGES = (
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

BLITZ_WORKFLOW_VERSION_ONE = definition_fixture(
    workflow_id="blitz",
    name="Blitz",
    description=(
        "Execute one strategy document directly with continuous slice delivery."
    ),
    stages=(
        *_REFINEMENT_STAGES,
        workflow_stage(
            "implementing",
            "Implementing",
            (
                gate_ref(GATE_DOC_CLAIM_ACTIVATION),
                gate_ref(GATE_CONFLICT_SURVEY),
                gate_ref(GATE_ARCHITECTURE_IMPACT),
            ),
            "The linked document drives a continuous loop of integrated slices.",
        ),
        workflow_stage(
            "reviewing-implementation",
            "Reviewing implementation",
            (
                gate_ref(GATE_DB_CLAIM_PROSE),
                gate_ref(GATE_DB_MUTATION, "evidence"),
                gate_ref(GATE_ARCHITECTURE_IMPACT),
            ),
            "The complete result and its evidence are reconciled in the document.",
        ),
        workflow_stage(
            "done",
            "Done",
            (
                gate_ref(GATE_ARCHITECTURE_IMPACT),
                gate_ref(GATE_QA_VERIFICATION),
                gate_ref(GATE_DOC_COMPLETION),
            ),
            "The document records completion and parent reconciliation.",
        ),
    ),
    entry_surfaces=("harness_skill",),
    skill_bindings=(
        skill_binding("refine", "idea", "refined-idea"),
        skill_binding("blitz", "refined-idea", "done"),
    ),
    policies={
        "ownership": "session_item_and_document_claim",
        "path_claims": "optional",
        "worktrees": "worker_lanes_optional_integration",
        "parallelism": "maximum_safe_slices",
        "generated_children": "none",
        "qa": "item_attachments",
        "approvals": "optional_named_gate",
        "delivery": "continuous_slice_actions",
        "item_posture_allowlist": [
            "verification",
            "path_claims",
            "approval",
            "deployment",
        ],
    },
    schema_version=1,
)

DASH_WORKFLOW_VERSION_ONE = definition_fixture(
    workflow_id="dash",
    name="Dash",
    description=(
        "A short instruction filed in seconds and executed end to end."
    ),
    stages=(
        workflow_stage("idea", "Idea"),
        workflow_stage(
            "implementing",
            "Implementing",
            (
                gate_ref(GATE_WORK_CLAIM_ACTIVATION),
                gate_ref(GATE_CONFLICT_SURVEY),
                gate_ref(GATE_ARCHITECTURE_IMPACT),
            ),
            "The skill surveys conflicts and completes the instruction.",
        ),
        workflow_stage(
            "reviewing-implementation",
            "Reviewing implementation",
            (
                gate_ref(GATE_DB_CLAIM_PROSE),
                gate_ref(GATE_DB_MUTATION, "evidence"),
                gate_ref(GATE_ARCHITECTURE_IMPACT),
            ),
            "The skill self-checks plus any item-declared verification.",
        ),
        workflow_stage(
            "done",
            "Done",
            (
                gate_ref(GATE_ARCHITECTURE_IMPACT),
                gate_ref(GATE_QA_VERIFICATION),
                gate_ref(GATE_DASH_EVIDENCE),
            ),
            "The result and verification evidence are recorded on the item.",
        ),
    ),
    entry_surfaces=("web_form", "cli", "harness_skill", "promotion"),
    skill_bindings=(skill_binding("dash", "idea", "done"),),
    policies={
        "ownership": "exclusive_session_work_claim",
        "path_claims": "optional",
        "worktrees": "single_implementation_lane",
        "parallelism": "none",
        "generated_children": "none",
        "qa": "optional_item_attachment",
        "approvals": "none",
        "delivery": "after_merge_action",
        "item_posture_allowlist": [
            "verification",
            "path_claims",
            "approval_on_done",
            "deployment",
        ],
    },
    schema_version=1,
)

__all__ = ["BLITZ_WORKFLOW_VERSION_ONE", "DASH_WORKFLOW_VERSION_ONE"]
