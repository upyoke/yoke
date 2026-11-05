"""Closed decision-request vocabulary.

Gate kinds release deployment stages, QA, item transitions or merges.
Operator questions ask for advice and never release any gate.
"""

from __future__ import annotations

from dataclasses import dataclass


DEPLOYMENT_STAGE_APPROVAL = "deployment_stage_approval"
QA_NEEDS_REVIEW = "qa_needs_review"
LIFECYCLE_TRANSITION_APPROVAL = "lifecycle_transition_approval"
RETIRED_DECISION_KINDS = ("machine_approval",)
MERGE_CANDIDATE_REVIEW = "merge_candidate_review"
OPERATOR_QUESTION = "operator_question"

# Storage retains retired kinds so historical rows stay valid. Creation and
# actions are limited to the active DECISION_KINDS contract below.
DECISION_REQUEST_KINDS = (
    DEPLOYMENT_STAGE_APPROVAL,
    QA_NEEDS_REVIEW,
    LIFECYCLE_TRANSITION_APPROVAL,
    *RETIRED_DECISION_KINDS,
    MERGE_CANDIDATE_REVIEW,
    OPERATOR_QUESTION,
)


@dataclass(frozen=True)
class DecisionKind:
    actions: tuple[str, ...]
    role_scope: str
    allowed_roles: tuple[str, ...]
    subject_type: str


DECISION_KINDS = {
    OPERATOR_QUESTION: DecisionKind(
        (), "project", ("owner", "operator"), "session_question"
    ),
    DEPLOYMENT_STAGE_APPROVAL: DecisionKind(
        ("approve", "reject"),
        "project",
        ("owner", "operator", "admin"),
        "deployment_stage",
    ),
    QA_NEEDS_REVIEW: DecisionKind(
        ("approve", "reject", "waive"),
        "project",
        ("owner", "operator"),
        "qa_requirement",
    ),
    LIFECYCLE_TRANSITION_APPROVAL: DecisionKind(
        ("approve", "reject"),
        "project",
        ("owner", "operator", "admin"),
        "item_transition",
    ),
    # Bound to one commit, not to the item: the subject is the exact head a
    # landing would carry, so a review answers the code that is about to
    # merge and nothing else.
    MERGE_CANDIDATE_REVIEW: DecisionKind(
        ("approve", "reject"),
        "project",
        ("owner", "operator", "admin"),
        "item_merge_candidate",
    ),
}

REQUEST_CREATED_EVENT = "DecisionRequestCreated"
DECISION_RECORDED_EVENT = "DecisionRecorded"
REQUEST_RESOLVED_EVENT = "DecisionRequestResolved"
REQUEST_WITHDRAWN_EVENT = "DecisionRequestWithdrawn"

__all__ = [
    "DECISION_RECORDED_EVENT",
    "DECISION_KINDS",
    "DECISION_REQUEST_KINDS",
    "DEPLOYMENT_STAGE_APPROVAL",
    "LIFECYCLE_TRANSITION_APPROVAL",
    "RETIRED_DECISION_KINDS",
    "MERGE_CANDIDATE_REVIEW",
    "QA_NEEDS_REVIEW",
    "REQUEST_CREATED_EVENT",
    "REQUEST_RESOLVED_EVENT",
    "REQUEST_WITHDRAWN_EVENT",
]
