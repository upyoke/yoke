"""Handler-level coverage for the identity.* admin family.

Handlers ride the ambient connection (``db_helpers.connect``), which the
test session pins to the per-worker canonical-schema DB; emails carry a
per-test unique suffix so runs never collide inside a worker.
"""

from __future__ import annotations

import uuid

import pytest

from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)

from yoke_core.domain.actors import seed_human_actor, set_actor_label
from yoke_core.domain.db_helpers import connect
from yoke_core.domain.handlers.identity_invites import (
    handle_identity_invite_create,
    handle_identity_invite_list,
    handle_identity_invite_revoke,
)
from yoke_core.domain.handlers.identity_links import (
    handle_identity_autojoin_set,
    handle_identity_link_set,
)


@pytest.fixture(autouse=True)
def _seed_auth_catalog():
    """Seed roles/permissions + the default org on the ambient test DB."""
    from yoke_core.domain.actor_permissions import seed_roles_and_permissions
    from yoke_core.domain.org_schema import seed_default_org

    conn = connect()
    try:
        seed_roles_and_permissions(conn)
        seed_default_org(conn)
    finally:
        conn.close()


@pytest.fixture
def unique() -> str:
    return uuid.uuid4().hex[:10]


def _request(function_id: str, payload: dict) -> FunctionCallRequest:
    return FunctionCallRequest(
        function=function_id,
        actor=ActorContext(session_id="handler-test-session"),
        target=TargetRef(kind="global"),
        payload=payload,
    )


def test_invite_create_list_revoke_round_trip(unique):
    email = f"member-{unique}@example.com"
    created = handle_identity_invite_create(
        _request("identity.invite.create", {"email": email, "role": "viewer"}),
    )
    assert created.primary_success, created.error
    invite_id = created.result_payload["invite_id"]
    assert created.result_payload["status"] == "pending"
    assert created.result_payload["role_id"] is not None

    # Duplicate pending invite is a typed payload failure.
    duplicate = handle_identity_invite_create(
        _request("identity.invite.create", {"email": email.upper()}),
    )
    assert not duplicate.primary_success
    assert duplicate.error.code == "payload_invalid"

    listed = handle_identity_invite_list(
        _request("identity.invite.list", {"status": "pending"}),
    )
    assert listed.primary_success
    assert any(
        row["invite_id"] == invite_id for row in listed.result_payload["invites"]
    )

    revoked = handle_identity_invite_revoke(
        _request("identity.invite.revoke", {"invite_id": invite_id}),
    )
    assert revoked.primary_success
    assert revoked.result_payload["status"] == "revoked"

    again = handle_identity_invite_revoke(
        _request("identity.invite.revoke", {"invite_id": invite_id}),
    )
    assert not again.primary_success


def test_invite_create_rejects_non_org_role(unique):
    outcome = handle_identity_invite_create(
        _request(
            "identity.invite.create",
            {"email": f"m-{unique}@example.com", "role": "operator"},
        ),
    )
    assert not outcome.primary_success
    assert outcome.error.code == "payload_invalid"
    assert "org role" in outcome.error.message


def test_link_set_identity_shape_binds_issuer_subject(unique):
    conn = connect()
    try:
        actor_id = seed_human_actor(conn)
        set_actor_label(conn, actor_id, f"linked-{unique}")
    finally:
        conn.close()
    outcome = handle_identity_link_set(
        _request(
            "identity.link.set",
            {
                "actor": f"linked-{unique}",
                "issuer": f"https://issuer-{unique}.example",
                "subject": "sub-1",
            },
        ),
    )
    assert outcome.primary_success, outcome.error
    assert outcome.result_payload["link_kind"] == "external_identity"
    assert outcome.result_payload["actor_id"] == actor_id
    assert outcome.result_payload["link_id"] is not None


def test_link_set_email_shape_writes_pre_link_invite(unique):
    conn = connect()
    try:
        actor_id = seed_human_actor(conn)
    finally:
        conn.close()
    outcome = handle_identity_link_set(
        _request(
            "identity.link.set",
            {"actor": str(actor_id), "email": f"pre-{unique}@example.com"},
        ),
    )
    assert outcome.primary_success, outcome.error
    assert outcome.result_payload["link_kind"] == "email_pre_link"
    invite_id = outcome.result_payload["invite_id"]
    assert invite_id is not None
    conn = connect()
    try:
        row = conn.execute(
            "SELECT actor_id, status FROM actor_invites WHERE id = %s",
            (invite_id,),
        ).fetchone()
    finally:
        conn.close()
    assert int(row[0]) == actor_id
    assert str(row[1]) == "pending"


def test_link_set_requires_exactly_one_shape(unique):
    missing_both = handle_identity_link_set(
        _request("identity.link.set", {"actor": "1"}),
    )
    assert not missing_both.primary_success
    half_identity = handle_identity_link_set(
        _request(
            "identity.link.set",
            {"actor": "1", "issuer": "https://issuer.example"},
        ),
    )
    assert not half_identity.primary_success


def test_autojoin_set_and_clear(unique):
    domain = f"auto-{unique}.example.com"
    set_outcome = handle_identity_autojoin_set(
        _request("identity.autojoin.set", {"domain": f"@{domain.upper()}"}),
    )
    assert set_outcome.primary_success, set_outcome.error
    assert set_outcome.result_payload["domain"] == domain

    clear_outcome = handle_identity_autojoin_set(
        _request("identity.autojoin.set", {"domain": None}),
    )
    assert clear_outcome.primary_success
    assert clear_outcome.result_payload["domain"] is None
