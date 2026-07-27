"""First definitions for the Blitz and Dash direct-execution workflows."""

from __future__ import annotations

from yoke_core.domain.workflow_definition_builders import (
    WORKFLOW_PATH_CLAIMS_OPTIONAL,
    definition_fixture,
    executor_binding,
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

BLITZ_WORKFLOW_DEFINITION = definition_fixture(
    workflow_id="blitz",
    name="Blitz",
    description=(
        "Execute a strategy document directly; the item is only its "
        "coordination shell. Releases happen continuously inside implementing; "
        "the close reconciles the document."
    ),
    stages=(
        *_REFINEMENT_STAGES,
        workflow_stage(
            "implementing",
            "implementing",
            (
                gate_ref(GATE_DOC_CLAIM_ACTIVATION),
                gate_ref(GATE_CONFLICT_SURVEY),
                gate_ref(GATE_ARCHITECTURE_IMPACT),
            ),
            "The continuous slice loop — the linked document is executed "
            "directly, and each slice may merge, migrate, and deploy; there "
            "is no separate release stage.",
        ),
        workflow_stage(
            "reviewing-implementation",
            "reviewing implementation",
            (
                gate_ref(GATE_DB_CLAIM_PROSE),
                gate_ref(GATE_DB_MUTATION, "evidence"),
                gate_ref(GATE_ARCHITECTURE_IMPACT),
            ),
            "The once-per-item close — the full suite runs and the document "
            "records what was completed, what changed, what remains, the "
            "evidence, and how the parent strategy was reconciled.",
        ),
        workflow_stage(
            "done",
            "done",
            (
                gate_ref(GATE_ARCHITECTURE_IMPACT),
                gate_ref(GATE_QA_VERIFICATION),
                gate_ref(GATE_DOC_COMPLETION),
            ),
            "The execution document states completion and parent "
            "reconciliation; that evidence is the entry gate.",
        ),
    ),
    entry_surfaces=("harness_skill",),
    executor_bindings=(
        executor_binding("refine", "idea", "refined-idea"),
        executor_binding("blitz", "refined-idea", "done"),
    ),
    policies={
        "ownership": "session_item_and_document_claim",
        "path_claims": WORKFLOW_PATH_CLAIMS_OPTIONAL,
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
)

DASH_WORKFLOW_DEFINITION = definition_fixture(
    workflow_id="dash",
    name="Dash",
    description=(
        "A short instruction you file in seconds — filing is the spec; "
        "an agent executes it end-to-end."
    ),
    stages=(
        workflow_stage("idea", "idea"),
        workflow_stage(
            "implementing",
            "implementing",
            (
                gate_ref(GATE_WORK_CLAIM_ACTIVATION),
                gate_ref(GATE_CONFLICT_SURVEY),
                gate_ref(GATE_ARCHITECTURE_IMPACT),
            ),
            "The agent surveys for conflicts, takes a worktree, and executes "
            "the instruction in one pass.",
        ),
        workflow_stage(
            "reviewing-implementation",
            "reviewing implementation",
            (
                gate_ref(GATE_DB_CLAIM_PROSE),
                gate_ref(GATE_DB_MUTATION, "evidence"),
                gate_ref(GATE_ARCHITECTURE_IMPACT),
            ),
            "The verification close — the agent self-checks, plus any case a "
            "tightened posture knob added.",
        ),
        workflow_stage(
            "done",
            "done",
            (
                gate_ref(GATE_ARCHITECTURE_IMPACT),
                gate_ref(GATE_QA_VERIFICATION),
                gate_ref(GATE_DASH_EVIDENCE),
            ),
            "Result and verification evidence are recorded on the item; "
            "delivery, when enabled, ran as an after-merge action.",
        ),
    ),
    entry_surfaces=("web_form", "cli", "harness_skill", "promotion"),
    executor_bindings=(executor_binding("dash", "idea", "done"),),
    policies={
        "ownership": "exclusive_session_work_claim",
        "path_claims": WORKFLOW_PATH_CLAIMS_OPTIONAL,
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
)

__all__ = ["BLITZ_WORKFLOW_DEFINITION", "DASH_WORKFLOW_DEFINITION"]
