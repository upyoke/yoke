"""Invite lifecycle coverage: create, list, revoke, duplicate guards."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any, Iterator

import pytest
from yoke_contracts.timestamps import temporal_wire

from runtime.api.fixtures import pg_testdb

from yoke_core.domain.actor_invites import (
    DuplicatePendingInvite,
    INVITE_STATUS_ACCEPTED,
    INVITE_STATUS_PENDING,
    INVITE_STATUS_REVOKED,
    InviteError,
    InviteNotFound,
    InviteNotPending,
    create_invite,
    get_invite,
    list_invites,
    mark_invite_accepted,
    pending_invite_for_email,
    revoke_invite,
    serialize_invites,
)
from yoke_core.domain.actor_permissions import seed_roles_and_permissions
from yoke_core.domain.actors import seed_human_actor
from yoke_core.domain.auth_schema import create_auth_tables
from yoke_core.domain.external_identities import default_org_id
from yoke_core.domain.external_identity_schema import (
    create_external_identity_tables,
)
from yoke_core.domain.org_schema import seed_default_org
from yoke_core.domain.project_seed_test_helpers import seed_project_identities
from yoke_core.domain.schema_init_actor_path_claim_tables import (
    create_actor_path_claim_tables,
)
from yoke_core.domain.schema_init_path_tables import create_path_registry_tables
from yoke_core.domain.schema_init_tables import create_core_tables
from yoke_core.domain.sign_in_invite_role import grant_invite_role, invite_role_refusal


@pytest.fixture
def conn() -> Iterator[Any]:
    name = pg_testdb.create_test_database()
    c = pg_testdb.connect_test_database(name)
    try:
        create_core_tables(c)
        seed_project_identities(c)
        create_path_registry_tables(c)
        create_actor_path_claim_tables(c)
        create_auth_tables(c)
        create_external_identity_tables(c)
        seed_roles_and_permissions(c)
        seed_default_org(c)
        c.commit()
        yield c
    finally:
        c.close()
        pg_testdb.drop_test_database(name)


def test_create_list_revoke_lifecycle(conn):
    inviter = seed_human_actor(conn)
    org_id = default_org_id(conn)
    invite = create_invite(
        conn,
        email="dev@example.com",
        org_id=org_id,
        invited_by_actor_id=inviter,
    )
    assert invite.status == INVITE_STATUS_PENDING
    assert invite.invited_by_actor_id == inviter

    pending = list_invites(conn, status=INVITE_STATUS_PENDING)
    assert [i.invite_id for i in pending] == [invite.invite_id]

    revoked = revoke_invite(
        conn,
        invite_id=invite.invite_id,
        revoked_by_actor_id=inviter,
    )
    assert revoked.status == INVITE_STATUS_REVOKED
    assert list_invites(conn, status=INVITE_STATUS_PENDING) == []
    # Revoking again is refused: the invite is no longer pending.
    with pytest.raises(InviteNotPending):
        revoke_invite(conn, invite_id=invite.invite_id)


def test_duplicate_pending_invite_is_rejected_case_insensitively(conn):
    inviter = seed_human_actor(conn)
    org_id = default_org_id(conn)
    create_invite(
        conn,
        email="Dev@Example.com",
        org_id=org_id,
        invited_by_actor_id=inviter,
    )
    with pytest.raises(DuplicatePendingInvite):
        create_invite(
            conn,
            email="dev@example.com",
            org_id=org_id,
            invited_by_actor_id=inviter,
        )


def test_revoked_invite_can_be_reissued(conn):
    inviter = seed_human_actor(conn)
    org_id = default_org_id(conn)
    first = create_invite(
        conn,
        email="dev@example.com",
        org_id=org_id,
        invited_by_actor_id=inviter,
    )
    revoke_invite(conn, invite_id=first.invite_id)
    second = create_invite(
        conn,
        email="dev@example.com",
        org_id=org_id,
        invited_by_actor_id=inviter,
    )
    assert second.invite_id != first.invite_id
    assert second.status == INVITE_STATUS_PENDING


def test_pending_invite_for_email_matches_case_insensitively(conn):
    inviter = seed_human_actor(conn)
    org_id = default_org_id(conn)
    invite = create_invite(
        conn,
        email="Dev@Example.com",
        org_id=org_id,
        invited_by_actor_id=inviter,
    )
    found = pending_invite_for_email(conn, email="DEV@EXAMPLE.COM")
    assert found is not None and found.invite_id == invite.invite_id
    assert pending_invite_for_email(conn, email="other@example.com") is None


def test_accept_requires_pending_and_records_acceptor(conn):
    inviter = seed_human_actor(conn)
    member = seed_human_actor(conn)
    org_id = default_org_id(conn)
    invite = create_invite(
        conn,
        email="dev@example.com",
        org_id=org_id,
        invited_by_actor_id=inviter,
    )
    accepted = mark_invite_accepted(
        conn,
        invite_id=invite.invite_id,
        accepted_by_actor_id=member,
    )
    assert accepted.accepted_by_actor_id == member
    assert accepted.accepted_at is not None
    with pytest.raises(InviteNotPending):
        mark_invite_accepted(
            conn,
            invite_id=invite.invite_id,
            accepted_by_actor_id=member,
        )


def test_an_invite_with_no_recorded_inviter_reads_lists_and_accepts(conn):
    org_id = default_org_id(conn)
    viewer = conn.execute("SELECT id FROM roles WHERE name = 'viewer'").fetchone()[0]
    invite = create_invite(
        conn,
        email="dev@example.com",
        org_id=org_id,
        invited_by_actor_id=seed_human_actor(conn),
        role_id=viewer,
    )
    conn.execute(
        "UPDATE actor_invites SET invited_by_actor_id = NULL WHERE id = %s",
        (invite.invite_id,),
    )
    invite = get_invite(conn, invite.invite_id)
    assert invite.invited_by_actor_id is None
    listed = list_invites(conn, status=INVITE_STATUS_PENDING)
    assert [(i.invite_id, i.invited_by_actor_id) for i in listed] == [
        (invite.invite_id, None)
    ]

    member = seed_human_actor(conn, name="dev")
    assert invite_role_refusal(conn, invite) is None
    grant_invite_role(conn, invite, member)
    mark_invite_accepted(conn, invite_id=invite.invite_id, accepted_by_actor_id=member)
    assert get_invite(conn, invite.invite_id).status == INVITE_STATUS_ACCEPTED
    granter = conn.execute(
        "SELECT granted_by_actor_id FROM actor_org_roles WHERE actor_id = %s",
        (member,),
    ).fetchone()
    assert granter == (None,)


def test_bad_email_and_missing_invite_are_typed_errors(conn):
    inviter = seed_human_actor(conn)
    org_id = default_org_id(conn)
    with pytest.raises(InviteError):
        create_invite(
            conn,
            email="not-an-email",
            org_id=org_id,
            invited_by_actor_id=inviter,
        )
    with pytest.raises(InviteNotFound):
        revoke_invite(conn, invite_id=99999)


@pytest.mark.parametrize("role", ["viewer", None])
@pytest.mark.parametrize("name", ["  Avery  ", "", None])
def test_public_rows_preserve_fields_and_resolve_catalog_names(conn, role, name):
    inviter = seed_human_actor(conn, "Avery")
    role_id = conn.execute("SELECT id FROM roles WHERE name = %s", (role,)).fetchone()
    invite = create_invite(
        conn,
        email="dev@example.com",
        org_id=default_org_id(conn),
        invited_by_actor_id=inviter,
        role_id=role_id[0] if role_id else None,
    )
    if name is None:
        conn.execute(
            "UPDATE actor_invites SET invited_by_actor_id = NULL WHERE id = %s",
            (invite.invite_id,),
        )
    else:
        conn.execute("UPDATE actors SET name = %s WHERE id = %s", (name, inviter))
    stored = get_invite(conn, invite.invite_id)
    expected = temporal_wire(asdict(stored))
    expected.update(role=role, invited_by_name=(name or "").strip() or None)
    assert serialize_invites(conn, [stored]) == [expected]
    assert serialize_invites(conn, []) == []
