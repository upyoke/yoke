"""Decision-request adapter for a hosted machine authorization."""

from __future__ import annotations

from typing import Any, Mapping, Optional

from yoke_core.domain.decision_request_contract import MACHINE_APPROVAL
from yoke_core.domain.decision_requests import (
    RoleAuthority,
    create_decision_request,
    list_subject_requests,
)


MACHINE_AUTH_SUBJECT = "machine_auth_request"


def ensure_machine_approval(
    conn: Any,
    *,
    auth_request_id: str,
    org_id: int,
    context: Mapping[str, Any],
    originator_actor_id: Optional[int] = None,
    session_id: str = "",
) -> tuple[dict[str, Any], bool]:
    """Create or reuse the org-admin decision for one machine auth request."""
    history = list_subject_requests(
        conn, MACHINE_AUTH_SUBJECT, auth_request_id,
    )
    if history and history[0]["status"] in {"pending", "resolved"}:
        return history[0], False
    return create_decision_request(
        conn,
        kind=MACHINE_APPROVAL,
        subject_type=MACHINE_AUTH_SUBJECT,
        subject_key=auth_request_id,
        org_id=int(org_id),
        originator_actor_id=originator_actor_id,
        role_authorities=[
            RoleAuthority("org", int(org_id), "admin"),
        ],
        subject_context=dict(context),
        session_id=session_id,
    )


def machine_approval_decision(
    conn: Any, *, auth_request_id: str,
) -> Optional[str]:
    """Return ``approve``/``deny``, or ``None`` while waiting."""
    history = list_subject_requests(
        conn, MACHINE_AUTH_SUBJECT, auth_request_id,
    )
    if not history or history[0]["status"] != "resolved":
        return None
    action = history[0].get("resolution_action")
    return str(action) if action else None


__all__ = [
    "MACHINE_AUTH_SUBJECT",
    "ensure_machine_approval",
    "machine_approval_decision",
]
