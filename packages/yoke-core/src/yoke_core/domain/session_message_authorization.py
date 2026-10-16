"""Per-recipient authorization and product-owned message limits."""

from __future__ import annotations

from yoke_contracts.fleet_policy import (
    BROADCAST_REQUIRES_CONFIRMATION,
    MAX_BODY_BYTES,
    MAX_WAKE_ATTEMPTS,
    MESSAGE_EXPIRY_HOURS,
    STALE_ALIVE_PROBE_SECONDS,
    WAKE_ACK_GRACE_SECONDS,
    WAKE_AFTER_IDLE_SECONDS,
)

from dataclasses import dataclass
from typing import Any, Iterable

from yoke_core.domain.actor_permissions import (
    PERM_ITEMS_READ,
    PERM_ITEMS_WRITE,
    PERM_ORG_ADMIN,
    permission_decision,
    require_org_permission,
)
from yoke_core.domain.session_action_authority import authorize_session_action
from yoke_core.domain.session_message_types import (
    ResolvedRecipient,
    SessionMessageError,
)


@dataclass(frozen=True)
class MessageScopePolicy:
    project_id: int | None
    org_id: int
    expiry_hours: int
    wake_after_idle_seconds: int
    max_body_bytes: int
    wake_ack_grace_seconds: int
    stale_alive_probe_seconds: int
    max_wake_attempts: int
    broadcast_requires_confirmation: bool


def _org_id(conn: Any, project_id: int) -> int:
    row = conn.execute(
        "SELECT org_id FROM projects WHERE id=%s"
        if not _sqlite(conn)
        else "SELECT org_id FROM projects WHERE id=?",
        (project_id,),
    ).fetchone()
    if row is None:
        raise SessionMessageError(
            "project_not_found", f"project id {project_id} does not exist"
        )
    return int(row[0])


def _sqlite(conn: Any) -> bool:
    from yoke_core.domain import db_backend

    return not db_backend.connection_is_postgres(conn)


def scope_policy(
    conn: Any, *, project_id: int | None = None, org_id: int | None = None
) -> MessageScopePolicy:
    if (project_id is None) == (org_id is None):
        raise ValueError("Message policy requires exactly one project or org scope")
    if project_id is not None:
        org_id = _org_id(conn, project_id)
    elif (
        conn.execute(
            "SELECT 1 FROM organizations WHERE id=?"
            if _sqlite(conn)
            else "SELECT 1 FROM organizations WHERE id=%s",
            (org_id,),
        ).fetchone()
        is None
    ):
        raise SessionMessageError(
            "org_not_found", f"organization id {org_id} does not exist"
        )

    return MessageScopePolicy(
        project_id=project_id,
        org_id=org_id,
        expiry_hours=MESSAGE_EXPIRY_HOURS,
        wake_after_idle_seconds=WAKE_AFTER_IDLE_SECONDS,
        max_body_bytes=MAX_BODY_BYTES,
        wake_ack_grace_seconds=WAKE_ACK_GRACE_SECONDS,
        stale_alive_probe_seconds=STALE_ALIVE_PROBE_SECONDS,
        max_wake_attempts=MAX_WAKE_ATTEMPTS,
        broadcast_requires_confirmation=BROADCAST_REQUIRES_CONFIRMATION,
    )


def authorize_recipients(
    conn: Any,
    *,
    actor_id: int,
    recipients: Iterable[ResolvedRecipient],
    permission_key: str = PERM_ITEMS_WRITE,
    additional_project_ids: Iterable[int] = (),
) -> dict[int, MessageScopePolicy]:
    """Authorize every project a message reaches, and return their policies.

    ``additional_project_ids`` covers a message that is addressed to a
    project without currently resolving to a session there: a role-addressed
    message parks in its scope, and it still has to be authorized and sized
    by that project's policy rather than by nobody's.

    A message resolves its audience by anchor, so the dispatcher cannot
    name the targets ahead of the handler. This is therefore where the
    shared session-action authority is applied for messaging — the same
    decision and the same refusal wording a directly targeted wake or
    termination gets, once per project the audience actually reached.
    """
    project_ids = sorted(
        {
            project_id
            for recipient in recipients
            for project_id in recipient.authorized_project_ids
        }
        | {int(project_id) for project_id in additional_project_ids}
    )
    policies: dict[int, MessageScopePolicy] = {}
    refusals: list[str] = []
    for project_id in project_ids:
        if permission_key == PERM_ITEMS_WRITE:
            decision = authorize_session_action(
                conn,
                actor_id=actor_id,
                function_id="session_control.message.send",
                project_id=project_id,
            )
            allowed, refusal = decision.allowed, decision.message
        else:
            allowed = permission_decision(
                conn,
                actor_id=actor_id,
                project_id=project_id,
                permission_key=permission_key,
            ).allowed
            refusal = (
                f"actor {actor_id} lacks {permission_key!r} on project id {project_id}"
            )
        if not allowed:
            refusals.append(refusal)
        policies[project_id] = scope_policy(conn, project_id=project_id)
    if refusals:
        raise SessionMessageError("unauthorized_target", " ".join(refusals))
    return policies


def authorize_universe(
    conn: Any,
    *,
    actor_id: int,
    policies: Iterable[MessageScopePolicy],
) -> None:
    for org_id in sorted({policy.org_id for policy in policies}):
        try:
            require_org_permission(
                conn,
                actor_id=actor_id,
                org_id=org_id,
                permission_key=PERM_ORG_ADMIN,
            )
        except PermissionError as exc:
            raise SessionMessageError("unauthorized_broadcast", str(exc)) from exc


def can_read_project(conn: Any, *, actor_id: int, project_id: int) -> bool:
    return permission_decision(
        conn,
        actor_id=actor_id,
        project_id=project_id,
        permission_key=PERM_ITEMS_READ,
    ).allowed


__all__ = [
    "MessageScopePolicy",
    "authorize_recipients",
    "authorize_universe",
    "can_read_project",
    "scope_policy",
]
