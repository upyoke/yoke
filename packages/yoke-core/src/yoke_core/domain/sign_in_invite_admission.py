"""Admit an invited person atomically while the owner's authority is locked."""

from yoke_contracts.refusal_recovery import compose_refusal
from yoke_core.domain import db_backend
from yoke_core.domain.actor_invites import (
    INVITE_STATUS_PENDING,
    InviteNotPending,
    get_invite,
    mark_invite_accepted,
)
from yoke_core.domain.actor_state import require_actor_active
from yoke_core.domain.actors import seed_human_actor
from yoke_core.domain.db_savepoint import savepoint
from yoke_core.domain.external_identities import link_external_identity
from yoke_core.domain.external_identity_events import (
    EVENT_ACTOR_INVITE_ACCEPTED,
    EVENT_EXTERNAL_IDENTITY_LINKED,
    emit_identity_event,
)
from yoke_core.domain.invite_owner_protection import require_invite_owner_change
from yoke_core.domain.sign_in_invite_role import grant_invite_role


def admit_invited_actor(
    conn,
    invite,
    *,
    issuer,
    subject,
    email,
    name,
    attribution=None,
    commit=True,
):
    if not db_backend.connection_is_postgres(conn) and not conn.in_transaction:
        conn.execute("BEGIN")
    with savepoint(conn, "invited_actor_admission", owns=commit):
        require_invite_owner_change(
            conn,
            invite.invited_by_actor_id,
            invite.actor_id,
            invite.org_id,
            invite.role_id,
        )
        invite = get_invite(conn, invite.invite_id)
        if invite.status != INVITE_STATUS_PENDING:
            raise InviteNotPending(
                compose_refusal(
                    "invite_not_pending: the invitation is no longer available",
                    recovery="Ask your inviter for a new invitation",
                )
            )
        actor_id = invite.actor_id
        if actor_id is None:
            actor_id = seed_human_actor(
                conn, name, attribution=attribution, commit=False
            )
        else:
            require_actor_active(conn, actor_id, lock=True)
        link_external_identity(
            conn,
            actor_id=actor_id,
            issuer=issuer,
            subject=subject,
            email=email,
            commit=False,
        )
        grant_invite_role(conn, invite, actor_id, commit=False)
        mark_invite_accepted(
            conn,
            invite_id=invite.invite_id,
            accepted_by_actor_id=actor_id,
            commit=False,
        )
    if commit:
        conn.commit()
        emit_identity_event(
            EVENT_EXTERNAL_IDENTITY_LINKED,
            context={
                "actor_id": actor_id,
                "issuer": issuer,
                "email": email,
                "created_by_actor_id": None,
            },
        )
        emit_identity_event(
            EVENT_ACTOR_INVITE_ACCEPTED,
            severity="STATUS",
            context={
                "invite_id": invite.invite_id,
                "email": invite.email,
                "org_id": invite.org_id,
                "role_id": invite.role_id,
                "accepted_by_actor_id": actor_id,
            },
        )
    return actor_id
