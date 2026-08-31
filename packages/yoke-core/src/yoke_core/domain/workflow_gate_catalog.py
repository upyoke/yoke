"""Closed catalog of gate identities referenced by workflow definitions.

Workflow versions own gate placement.  This module owns the stable gate ids
and their operator-facing meaning so definitions and user interfaces do not
duplicate those strings.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict, Tuple

GATE_DB_CLAIM_PROSE = "db_claim_prose"
GATE_DB_MUTATION = "db_mutation"
GATE_ARCHITECTURE_IMPACT = "architecture_impact"
GATE_PATH_CLAIM_BOUNDARY = "path_claim_boundary"
GATE_PLAN_SIMULATION = "plan_simulation"
GATE_QA_VERIFICATION = "qa_verification"
GATE_CHECK_HARD_BLOCKS = "check_hard_blocks"
GATE_CLAIM_ACTIVATION = "claim_activation"
GATE_WORK_CLAIM_ACTIVATION = "work_claim_activation"
GATE_DOC_CLAIM_ACTIVATION = "doc_claim_activation"
GATE_CONFLICT_SURVEY = "conflict_survey"
GATE_DOC_COMPLETION = "doc_completion"
GATE_DASH_EVIDENCE = "dash_evidence"
GATE_FLOOR_ATTESTATION = "floor_attestation"
GATE_APPROVAL = "approval"

_GATE_CATALOG: Tuple[Dict[str, Any], ...] = (
    {
        "id": GATE_DB_CLAIM_PROSE,
        "name": "DB claim consistency",
        "description": (
            "The item's declared DB claim must agree with what its own text "
            "describes — prose about migrations alongside a claim of none "
            "is refused."
        ),
        "source_kind": "status_gate",
        "availability": "live",
        "modes": [],
    },
    {
        "id": GATE_DB_MUTATION,
        "name": "Governed DB mutation",
        "description": (
            "A declared governed mutation must satisfy this point's check — "
            "joint: the strategy fits the project's breakage policy with no "
            "cross-item overlap; evidence: the authoritative apply evidence "
            "exists; polish: migration closeout is complete."
        ),
        "source_kind": "status_gate",
        "availability": "live",
        "modes": [
            {
                "id": "joint",
                "name": "Joint",
                "description": (
                    "The change fits project breakage policy and has no "
                    "unresolved cross-item overlap."
                ),
            },
            {
                "id": "evidence",
                "name": "Evidence",
                "description": "Authoritative apply evidence exists.",
            },
            {
                "id": "polish",
                "name": "Polish",
                "description": "Migration closeout is complete.",
            },
        ],
    },
    {
        "id": GATE_ARCHITECTURE_IMPACT,
        "name": "Architecture impact",
        "description": (
            "The item's declared architecture impact must be resolved before "
            "it advances: an item still marked 'uncertain' is refused past "
            "refined-idea. Conformance to the project's architecture model "
            "itself is reported by the architecture Doctor checks, which hold "
            "the checkout this gate does not."
        ),
        "source_kind": "status_gate",
        "availability": "live",
        "modes": [],
    },
    {
        "id": GATE_PATH_CLAIM_BOUNDARY,
        "name": "Path-claim boundary",
        "description": (
            "The item's changed files must stay inside its registered path "
            "claims, diffed against the highest reachable rung of the "
            "integration ladder — the remote integration ref, else the "
            "local one. An item with no claims is clear; an item with "
            "claims and no worktree, or no resolvable ref, is refused."
        ),
        "source_kind": "status_gate",
        "availability": "live",
        "modes": [],
    },
    {
        "id": GATE_PLAN_SIMULATION,
        "name": "Plan simulation",
        "description": (
            "The epic's plan must pass the simulator's cross-task execution "
            "trace."
        ),
        "source_kind": "status_gate",
        "availability": "live",
        "modes": [],
    },
    {
        "id": GATE_QA_VERIFICATION,
        "name": "QA requirements",
        "description": (
            "Every QA requirement materialized for this transition must be "
            "satisfied — passed or explicitly waived."
        ),
        "source_kind": "status_gate",
        "availability": "live",
        "modes": [],
    },
    {
        "id": GATE_CHECK_HARD_BLOCKS,
        "name": "Dependency hard blocks",
        "description": (
            "Every upstream item this one depends on must be finished before "
            "activation."
        ),
        "source_kind": "activation_operation",
        "availability": "live",
        "modes": [],
    },
    {
        "id": GATE_CLAIM_ACTIVATION,
        "name": "Claim activation",
        "description": (
            "Registered path claims activate together with the worktree; a "
            "conflicting live claim refuses activation."
        ),
        "source_kind": "activation_operation",
        "availability": "live",
        "modes": [],
    },
    {
        "id": GATE_WORK_CLAIM_ACTIVATION,
        "name": "Work-claim activation",
        "description": (
            "The executing session takes the exclusive work claim, and a "
            "worktree when the worktrees policy requires one."
        ),
        "source_kind": "activation_operation",
        "availability": "live",
        "modes": [],
    },
    {
        "id": GATE_DOC_CLAIM_ACTIVATION,
        "name": "Execution-document claim",
        "description": (
            "The Blitz atomically claims its single execution document; an "
            "already-owned document refuses activation."
        ),
        "source_kind": "activation_operation",
        "availability": "live",
        "modes": [],
    },
    {
        "id": GATE_CONFLICT_SURVEY,
        "name": "Conflict survey",
        "description": (
            "The agent reads claims, worktrees, and frontier items and aborts "
            "on any detected conflict."
        ),
        "source_kind": "status_gate",
        "availability": "live",
        "modes": [],
    },
    {
        "id": GATE_DOC_COMPLETION,
        "name": "Document completion",
        "description": (
            "The strategy document must record what was completed, what "
            "changed, what remains, the evidence, and the parent "
            "reconciliation."
        ),
        "source_kind": "status_gate",
        "availability": "live",
        "modes": [],
    },
    {
        "id": GATE_DASH_EVIDENCE,
        "name": "Result evidence",
        "description": (
            "The result and verification evidence must be recorded on the "
            "item, plus every check the item's knobs declared — an attached "
            "plan passed, an approval resolved."
        ),
        "source_kind": "status_gate",
        "availability": "live",
        "modes": [],
    },
    {
        "id": GATE_FLOOR_ATTESTATION,
        "name": "Floor attestation",
        "description": (
            "Done is the recorded floor attestation — the agent account "
            "plus observed changes, stamped agent-attested, with no "
            "merge SHA required."
        ),
        "source_kind": "status_gate",
        "availability": "live",
        "modes": [],
    },
    {
        "id": GATE_APPROVAL,
        "name": "Approval",
        "description": (
            "The approval request declared for this transition must be resolved."
        ),
        "source_kind": "status_gate",
        "availability": "live",
        "modes": [],
    },
)


def workflow_gate_catalog() -> list[Dict[str, Any]]:
    """Return a caller-owned copy of the closed gate catalog."""
    return deepcopy(list(_GATE_CATALOG))


__all__ = [
    "GATE_APPROVAL",
    "GATE_ARCHITECTURE_IMPACT",
    "GATE_CHECK_HARD_BLOCKS",
    "GATE_CLAIM_ACTIVATION",
    "GATE_CONFLICT_SURVEY",
    "GATE_DASH_EVIDENCE",
    "GATE_FLOOR_ATTESTATION",
    "GATE_DB_CLAIM_PROSE",
    "GATE_DB_MUTATION",
    "GATE_DOC_CLAIM_ACTIVATION",
    "GATE_DOC_COMPLETION",
    "GATE_PATH_CLAIM_BOUNDARY",
    "GATE_PLAN_SIMULATION",
    "GATE_QA_VERIFICATION",
    "GATE_WORK_CLAIM_ACTIVATION",
    "workflow_gate_catalog",
]
