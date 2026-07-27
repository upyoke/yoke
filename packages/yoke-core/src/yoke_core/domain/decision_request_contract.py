"""Closed decision-request and in-app notification vocabulary."""

from __future__ import annotations

from dataclasses import dataclass


DEPLOYMENT_STAGE_APPROVAL = "deployment_stage_approval"
QA_NEEDS_REVIEW = "qa_needs_review"
LIFECYCLE_TRANSITION_APPROVAL = "lifecycle_transition_approval"
MACHINE_APPROVAL = "machine_approval"
STRATEGY_REVISION_REVIEW = "strategy_revision_review"

DECISION_REQUEST_KINDS = (
    DEPLOYMENT_STAGE_APPROVAL,
    QA_NEEDS_REVIEW,
    LIFECYCLE_TRANSITION_APPROVAL,
    MACHINE_APPROVAL,
    STRATEGY_REVISION_REVIEW,
)

DECISION_RESOLVED = "decision_request_resolved"
DEPLOYMENT_RUN_COMPLETED = "deployment_run_completed"
ITEM_BLOCK_STATE_CHANGED = "item_block_state_changed"

IN_APP_NOTIFICATION_KINDS = (
    DECISION_RESOLVED,
    DEPLOYMENT_RUN_COMPLETED,
    ITEM_BLOCK_STATE_CHANGED,
)


@dataclass(frozen=True)
class DecisionKind:
    blocking: bool
    actions: tuple[str, ...]
    role_scope: str
    allowed_roles: tuple[str, ...]
    subject_type: str


DECISION_KINDS = {
    DEPLOYMENT_STAGE_APPROVAL: DecisionKind(
        True, ("approve", "reject"), "project", ("owner", "operator"),
        "deployment_stage",
    ),
    QA_NEEDS_REVIEW: DecisionKind(
        True, ("approve", "reject", "waive"), "project",
        ("owner", "operator"), "qa_requirement",
    ),
    LIFECYCLE_TRANSITION_APPROVAL: DecisionKind(
        True, ("approve", "reject"), "project",
        ("owner", "operator", "admin"), "item_transition",
    ),
    MACHINE_APPROVAL: DecisionKind(
        True, ("approve", "deny"), "org", ("admin",), "machine_auth_request",
    ),
    STRATEGY_REVISION_REVIEW: DecisionKind(
        False, ("approve", "request_changes"), "project",
        ("owner", "operator"), "strategy_doc_revision",
    ),
}

REQUEST_CREATED_EVENT = "DecisionRequestCreated"
REQUEST_RESOLVED_EVENT = "DecisionRequestResolved"
REQUEST_WITHDRAWN_EVENT = "DecisionRequestWithdrawn"
NOTIFICATION_READ_EVENT = "InboxNotificationRead"
ITEM_BLOCKED_EVENT = "ItemBlocked"
ITEM_UNBLOCKED_EVENT = "ItemUnblocked"

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
    (
        NOTIFICATION_READ_EVENT, "lifecycle", "inbox_notification",
        "An addressed in-app notification was marked read.",
    ),
    (
        ITEM_BLOCKED_EVENT, "lifecycle", "item_dependency",
        "An item entered dependency-blocked coordination state.",
    ),
    (
        ITEM_UNBLOCKED_EVENT, "lifecycle", "item_dependency",
        "An item left dependency-blocked coordination state.",
    ),
)


__all__ = [
    "DECISION_EVENT_ROWS",
    "DECISION_KINDS",
    "DECISION_REQUEST_KINDS",
    "DECISION_RESOLVED",
    "DEPLOYMENT_RUN_COMPLETED",
    "IN_APP_NOTIFICATION_KINDS",
    "ITEM_BLOCK_STATE_CHANGED",
    "ITEM_BLOCKED_EVENT",
    "ITEM_UNBLOCKED_EVENT",
    "NOTIFICATION_READ_EVENT",
    "REQUEST_CREATED_EVENT",
    "REQUEST_RESOLVED_EVENT",
    "REQUEST_WITHDRAWN_EVENT",
]
