"""Identity admission on the per-worker DB with per-test unique email suffixes."""

from __future__ import annotations

import uuid

import pytest

from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)

from yoke_core.domain.actors import seed_human_actor, set_actor_name
from yoke_core.domain.db_helpers import connect
from yoke_core.domain.handlers.identity_invites import (
    handle_identity_invite_create,
    handle_identity_invite_list,
    handle_identity_invite_revoke,
)
from yoke_core.domain.handlers.identity_links import handle_identity_link_set
from yoke_core.domain.handlers.organizations_settings import (
    handle_organization_domain_set,
    handle_organization_settings_catalog,
    handle_organization_settings_get,
    handle_organization_settings_merge,
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
        _CALLER["actor_id"] = str(seed_human_actor(conn))
    finally:
        conn.close()


# The dispatcher-bound calling actor every identity write is attributed to.
_CALLER: dict[str, str] = {}


@pytest.fixture
def unique() -> str:
    return uuid.uuid4().hex[:10]


def _request(
    function_id: str, payload: dict, *, caller: bool = True
) -> FunctionCallRequest:
    return FunctionCallRequest(
        function=function_id,
        actor=ActorContext(
            actor_id=_CALLER["actor_id"] if caller else None,
            session_id="handler-test-session",
        ),
        target=TargetRef(kind="global"),
        payload=payload,
    )


@pytest.mark.parametrize(
    ("handler", "function_id", "payload"),
    [
        (
            handle_identity_invite_create,
            "identity.invite.create",
            {"email": "x@example.com"},
        ),
        (handle_identity_invite_revoke, "identity.invite.revoke", {"invite_id": 1}),
        (
            handle_identity_link_set,
            "identity.link.set",
            {"actor": "1", "email": "x@example.com"},
        ),
        (
            handle_organization_domain_set,
            "organizations.domain.set",
            {"domain": "example.com"},
        ),
    ],
)
def test_identity_writes_without_a_calling_actor_refuse(handler, function_id, payload):
    outcome = handler(_request(function_id, payload, caller=False))
    assert not outcome.primary_success
    assert outcome.error.code == "actor_required"
    assert "yoke setup" in outcome.error.message


@pytest.mark.parametrize("role", ["viewer", None])
def test_invite_create_list_revoke_round_trip(unique, role):
    email = f"member-{unique}@example.com"
    created = handle_identity_invite_create(
        _request("identity.invite.create", {"email": email, "role": role}),
    )
    assert created.primary_success, created.error
    invite_id = created.result_payload["invite_id"]
    assert created.result_payload["status"] == "pending"
    assert (created.result_payload["role_id"] is not None) == (role is not None)

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
    (row,) = [
        r for r in listed.result_payload["invites"] if r["invite_id"] == invite_id
    ]
    assert row["invited_by_actor_id"] == int(_CALLER["actor_id"])
    assert row["role"] == role

    revoked = handle_identity_invite_revoke(
        _request("identity.invite.revoke", {"invite_id": invite_id}),
    )
    assert revoked.primary_success
    assert revoked.result_payload["status"] == "revoked"

    again = handle_identity_invite_revoke(
        _request("identity.invite.revoke", {"invite_id": invite_id}),
    )
    assert not again.primary_success


@pytest.mark.parametrize(
    ("role", "reason"),
    [("owner", "not a person's org role"), ("deployment_ci", "machine-only role")],
)
def test_invite_create_rejects_a_role_a_person_cannot_hold(unique, role, reason):
    outcome = handle_identity_invite_create(
        _request(
            "identity.invite.create",
            {"email": f"m-{unique}@example.com", "role": role},
        ),
    )
    assert not outcome.primary_success
    assert outcome.error.code == "payload_invalid"
    assert reason in outcome.error.message


@pytest.mark.parametrize("hosted", [False, True])
def test_link_set_identity_shape_binds_issuer_subject(unique, monkeypatch, hosted):
    from yoke_core.domain.handlers import identity_invites

    monkeypatch.setattr(
        identity_invites, "hosted_tenant_container_process", lambda: hosted
    )
    conn = connect()
    try:
        actor_id = seed_human_actor(conn)
        set_actor_name(conn, actor_id, f"linked-{unique}")
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
        _request("identity.link.set", {"actor": "1"})
    )
    assert not missing_both.primary_success
    half_identity = handle_identity_link_set(
        _request(
            "identity.link.set",
            {"actor": "1", "issuer": "https://issuer.example"},
        ),
    )
    assert not half_identity.primary_success


def test_organization_domain_set_and_clear(unique):
    domain = f"auto-{unique}.example.com"
    set_outcome = handle_organization_domain_set(
        _request("organizations.domain.set", {"domain": f"@{domain.upper()}"}),
    )
    assert set_outcome.primary_success, set_outcome.error
    assert set_outcome.result_payload["domain"] == domain

    clear_outcome = handle_organization_domain_set(
        _request("organizations.domain.set", {"domain": None}),
    )
    assert clear_outcome.primary_success
    assert clear_outcome.result_payload["domain"] is None


def test_organization_settings_default_merge_and_projection():
    defaulted = handle_organization_settings_get(
        _request(
            "organizations.settings.get",
            {"path": "membership.auto_join_domain_verified"},
        ),
    )
    assert defaulted.primary_success, defaulted.error
    assert defaulted.result_payload["value"] is False
    assert defaulted.result_payload["defaulted"] is True

    merged = handle_organization_settings_merge(
        _request(
            "organizations.settings.merge",
            {"assignments": {"membership.auto_join_domain_verified": True}},
        ),
    )
    assert merged.primary_success, merged.error
    assert merged.result_payload["changed_paths"] == [
        "membership.auto_join_domain_verified"
    ]

    projected = handle_organization_settings_get(
        _request(
            "organizations.settings.get",
            {"path": "membership.auto_join_domain_verified"},
        ),
    )
    assert projected.result_payload["value"] is True
    assert projected.result_payload["defaulted"] is False


def test_organization_settings_reject_unknown_or_invalid_assignments():
    unknown = handle_organization_settings_merge(
        _request(
            "organizations.settings.merge",
            {"assignments": {"fleet.invented": True}},
        ),
    )
    assert not unknown.primary_success
    assert unknown.error.code == "validation_error"

    invalid = handle_organization_settings_merge(
        _request(
            "organizations.settings.merge",
            {"assignments": {"membership.auto_join_domain_verified": "invalid"}},
        ),
    )
    assert not invalid.primary_success
    assert invalid.error.code == "validation_error"


def test_organization_settings_catalog_projects_closed_membership_contract():
    merged = handle_organization_settings_merge(
        _request(
            "organizations.settings.merge",
            {"assignments": {"membership.auto_join_domain_verified": True}},
        ),
    )
    assert merged.primary_success, merged.error
    outcome = handle_organization_settings_catalog(
        _request("organizations.settings.catalog", {}),
    )

    assert outcome.primary_success, outcome.error
    settings = {row["path"]: row for row in outcome.result_payload["settings"]}
    poll = settings["membership.auto_join_domain_verified"]
    assert poll["value"] is True
    assert poll["default"] is False
    assert poll["defaulted"] is False
    assert poll["value_type"] == "bool"
    assert poll["minimum"] is None
    assert "meaning" in poll


@pytest.mark.parametrize(
    ("handler", "function_id", "payload"),
    [
        (
            handle_identity_invite_create,
            "identity.invite.create",
            {"email": "pat@example.com"},
        ),
        (
            handle_identity_link_set,
            "identity.link.set",
            {"actor": "1", "email": "pat@example.com"},
        ),
        (handle_identity_invite_list, "identity.invite.list", {}),
        (handle_identity_invite_revoke, "identity.invite.revoke", {"invite_id": 1}),
    ],
)
def test_hosted_tenant_refuses_invites_platform_owns(
    monkeypatch, handler, function_id, payload
):
    from yoke_core.domain.handlers import identity_invites

    monkeypatch.setattr(
        identity_invites, "hosted_tenant_container_process", lambda: True
    )
    conn = connect()
    try:
        before = conn.execute("SELECT COUNT(*) FROM actor_invites").fetchone()[0]
        outcome = handler(_request(function_id, payload))
        after = conn.execute("SELECT COUNT(*) FROM actor_invites").fetchone()[0]
    finally:
        conn.close()
    assert after == before
    assert outcome.primary_success is False
    assert outcome.error.code == identity_invites.HOSTED_INVITES_PLATFORM_OWNED
    assert "yoke setup --connect" in outcome.error.message
