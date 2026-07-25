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
GATE_APPROVAL = "approval"

_GATE_CATALOG: Tuple[Dict[str, Any], ...] = (
    {
        "id": GATE_DB_CLAIM_PROSE,
        "name": "DB claim consistency",
        "description": (
            "The item's declared DB claim must agree with the database work "
            "described by the item."
        ),
        "source_kind": "status_gate",
        "availability": "live",
        "modes": [],
    },
    {
        "id": GATE_DB_MUTATION,
        "name": "Governed DB mutation",
        "description": (
            "A governed database change must satisfy the policy check for "
            "this lifecycle point."
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
            "The declared architecture impact must honor the project's "
            "authoritative architecture model."
        ),
        "source_kind": "status_gate",
        "availability": "live",
        "modes": [],
    },
    {
        "id": GATE_PATH_CLAIM_BOUNDARY,
        "name": "Path-claim boundary",
        "description": (
            "Changed files must stay inside the item's registered path claims."
        ),
        "source_kind": "status_gate",
        "availability": "live",
        "modes": [],
    },
    {
        "id": GATE_PLAN_SIMULATION,
        "name": "Plan simulation",
        "description": (
            "The plan must pass the simulator's cross-task execution trace."
        ),
        "source_kind": "status_gate",
        "availability": "live",
        "modes": [],
    },
    {
        "id": GATE_QA_VERIFICATION,
        "name": "QA requirements",
        "description": (
            "Every QA requirement for the transition must pass or be "
            "explicitly waived."
        ),
        "source_kind": "status_gate",
        "availability": "live",
        "modes": [],
    },
    {
        "id": GATE_CHECK_HARD_BLOCKS,
        "name": "Dependency hard blocks",
        "description": (
            "Every upstream item dependency must be finished before activation."
        ),
        "source_kind": "activation_operation",
        "availability": "live",
        "modes": [],
    },
    {
        "id": GATE_CLAIM_ACTIVATION,
        "name": "Claim activation",
        "description": (
            "Registered path claims activate with the worktree and conflicts "
            "refuse activation."
        ),
        "source_kind": "activation_operation",
        "availability": "live",
        "modes": [],
    },
    {
        "id": GATE_WORK_CLAIM_ACTIVATION,
        "name": "Work-claim activation",
        "description": (
            "The executing session takes the exclusive work claim and a "
            "worktree."
        ),
        "source_kind": "activation_operation",
        "availability": "registry",
        "modes": [],
    },
    {
        "id": GATE_DOC_CLAIM_ACTIVATION,
        "name": "Execution-document claim",
        "description": (
            "The item atomically claims its execution document and refuses "
            "activation when another item owns it."
        ),
        "source_kind": "activation_operation",
        "availability": "registry",
        "modes": [],
    },
    {
        "id": GATE_CONFLICT_SURVEY,
        "name": "Conflict survey",
        "description": (
            "The executor surveys claims, worktrees, and frontier items and "
            "aborts on a detected conflict."
        ),
        "source_kind": "status_gate",
        "availability": "planned",
        "modes": [],
    },
    {
        "id": GATE_DOC_COMPLETION,
        "name": "Document completion",
        "description": (
            "The execution document must record outcome, remaining work, "
            "evidence, and parent reconciliation."
        ),
        "source_kind": "status_gate",
        "availability": "planned",
        "modes": [],
    },
    {
        "id": GATE_DASH_EVIDENCE,
        "name": "Result evidence",
        "description": (
            "The result, verification evidence, and every item-declared check "
            "must be recorded."
        ),
        "source_kind": "status_gate",
        "availability": "planned",
        "modes": [],
    },
    {
        "id": GATE_APPROVAL,
        "name": "Approval",
        "description": (
            "The approval request declared for this transition must be resolved."
        ),
        "source_kind": "status_gate",
        "availability": "planned",
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
