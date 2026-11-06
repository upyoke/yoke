"""An owner refusal cannot leave an actor, identity link or accepted invite."""

from runtime.api.domain.sign_in_resolution_test_support import conn as conn
from yoke_core.domain import sign_in_invite_admission
from yoke_core.domain.actor_invites import create_invite, get_invite
from yoke_core.domain.actor_owner_protection import seed_bootstrap_owner
from yoke_core.domain.actor_permissions import role_id_by_name
from yoke_core.domain.actor_role import ActorRoleRefused
from yoke_core.domain.actors import seed_human_actor
from yoke_core.domain.external_identities import (
    default_org_id,
    resolve_external_identity,
)
from yoke_core.domain.sign_in_resolution import (
    REFUSAL_INVITE_ROLE_REFUSED,
    resolve_sign_in,
)


def test_owner_refusal_rolls_back_the_whole_admission(conn, monkeypatch):
    inviter = seed_human_actor(conn, "Owner")
    org_id = default_org_id(conn)
    seed_bootstrap_owner(conn, inviter, org_id)
    conn.commit()
    invite = create_invite(
        conn,
        email="person@example.test",
        org_id=org_id,
        invited_by_actor_id=inviter,
        role_id=role_id_by_name(conn, "owner"),
    )
    before = conn.execute("SELECT COUNT(*) FROM actors").fetchone()[0]

    def refuse(*args, **kwargs):
        raise ActorRoleRefused(
            "owner_protected", "owner_protected: ask an owner to retry"
        )

    monkeypatch.setattr(sign_in_invite_admission, "grant_invite_role", refuse)
    result = resolve_sign_in(
        conn,
        {
            "issuer": "https://identity.example.test",
            "subject": "person",
            "email": "person@example.test",
            "email_verified": True,
            "name": "Person",
        },
    )
    assert result.refusal_reason == REFUSAL_INVITE_ROLE_REFUSED
    assert "owner_protected" in result.detail
    assert conn.execute("SELECT COUNT(*) FROM actors").fetchone()[0] == before
    assert (
        resolve_external_identity(
            conn,
            issuer="https://identity.example.test",
            subject="person",
        )
        is None
    )
    assert get_invite(conn, invite.invite_id).status == "pending"
