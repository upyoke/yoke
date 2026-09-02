"""Closed decision-request vocabulary.

Every kind here gates something: a person's answer is what releases a
deployment stage, a QA verdict, an item transition, or a machine's access.
There is no non-gating kind, so a request row needs no flag saying whether
it blocks -- being a request is what blocking means.
"""

from __future__ import annotations

from dataclasses import dataclass


DEPLOYMENT_STAGE_APPROVAL = "deployment_stage_approval"
QA_NEEDS_REVIEW = "qa_needs_review"
LIFECYCLE_TRANSITION_APPROVAL = "lifecycle_transition_approval"
MACHINE_APPROVAL = "machine_approval"

DECISION_REQUEST_KINDS = (
    DEPLOYMENT_STAGE_APPROVAL,
    QA_NEEDS_REVIEW,
    LIFECYCLE_TRANSITION_APPROVAL,
    MACHINE_APPROVAL,
)


@dataclass(frozen=True)
class DecisionKind:
    actions: tuple[str, ...]
    role_scope: str
    allowed_roles: tuple[str, ...]
    subject_type: str


DECISION_KINDS = {
    DEPLOYMENT_STAGE_APPROVAL: DecisionKind(
        ("approve", "reject"), "project", ("owner", "operator"),
        "deployment_stage",
    ),
    QA_NEEDS_REVIEW: DecisionKind(
        ("approve", "reject", "waive"), "project",
        ("owner", "operator"), "qa_requirement",
    ),
    LIFECYCLE_TRANSITION_APPROVAL: DecisionKind(
        ("approve", "reject"), "project",
        ("owner", "operator", "admin"), "item_transition",
    ),
    MACHINE_APPROVAL: DecisionKind(
        ("approve", "deny"), "org", ("admin",), "machine_auth_request",
    ),
}

REQUEST_CREATED_EVENT = "DecisionRequestCreated"
REQUEST_RESOLVED_EVENT = "DecisionRequestResolved"
REQUEST_WITHDRAWN_EVENT = "DecisionRequestWithdrawn"

DECISION_EVENT_ROWS = (
    (
        REQUEST_CREATED_EVENT, "lifecycle", "decision_request",
        "A typed human decision request was created for a governed subject.",
    ),
    (
        REQUEST_RESOLVED_EVENT, "lifecycle", "decision_request",
        "An authorized actor resolved a typed human decision request.",
    ),
    (
        REQUEST_WITHDRAWN_EVENT, "lifecycle", "decision_request",
        "A pending decision request was withdrawn because its subject ended.",
    ),
)


__all__ = [
    "DECISION_EVENT_ROWS",
    "DECISION_KINDS",
    "DECISION_REQUEST_KINDS",
    "DEPLOYMENT_STAGE_APPROVAL",
    "LIFECYCLE_TRANSITION_APPROVAL",
    "MACHINE_APPROVAL",
    "QA_NEEDS_REVIEW",
    "REQUEST_CREATED_EVENT",
    "REQUEST_RESOLVED_EVENT",
    "REQUEST_WITHDRAWN_EVENT",
]
