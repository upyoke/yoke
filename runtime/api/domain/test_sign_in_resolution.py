"""Ladder coverage for verified-claims -> actor sign-in resolution."""

from __future__ import annotations

from typing import Any, Iterator

import pytest

from runtime.api.fixtures import pg_testdb

from yoke_core.domain.actor_invites import (
    INVITE_STATUS_ACCEPTED,
    create_invite,
    get_invite,
)
from yoke_core.domain.actor_permissions import (
    PERM_ORG_ADMIN,
    ROLE_ADMIN,
    require_org_permission,
    role_id_by_name,
    seed_roles_and_permissions,
)
from yoke_core.domain.actors import seed_human_actor, set_actor_label
from yoke_core.domain.auth_schema import create_auth_tables
from yoke_core.domain.external_identities import (
    default_org_id,
    link_external_identity,
    resolve_external_identity,
    set_auto_join_domain,
)
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
from yoke_core.domain.sign_in_resolution import (
    OUTCOME_AUTO_JOINED,
    OUTCOME_INVITE_ACCEPTED,
    OUTCOME_LINKED_IDENTITY,
    OUTCOME_REFUSED,
    REFUSAL_EMAIL_UNVERIFIED,
    REFUSAL_MISSING_EMAIL_CLAIM,
    REFUSAL_MISSING_REQUIRED_CLAIMS,
    REFUSAL_NO_ADMISSION_MATCH,
    resolve_sign_in,
)


_ISSUER = "https://issuer.example"


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


def _claims(**overrides: Any) -> dict:
    base = {
        "issuer": _ISSUER,
        "subject": "sub-1",
        "email": "casey@example.com",
        "email_verified": True,
        "name": "Casey",
    }
    base.update(overrides)
    return base


def _admin(conn) -> int:
    actor_id = seed_human_actor(conn)
    set_actor_label(conn, actor_id, f"inviter-{actor_id}")
    return actor_id


def test_rung_one_linked_identity_wins(conn):
    actor_id = seed_human_actor(conn)
    link_external_identity(
        conn, actor_id=actor_id, issuer=_ISSUER, subject="sub-1",
    )
    result = resolve_sign_in(conn, _claims())
    assert result.succeeded
    assert result.outcome == OUTCOME_LINKED_IDENTITY
    assert result.actor_id == actor_id


def test_rung_two_invite_creates_actor_links_identity_and_grants_role(conn):
    inviter = _admin(conn)
    org_id = default_org_id(conn)
    admin_role_id = role_id_by_name(conn, ROLE_ADMIN)
    invite = create_invite(
        conn,
        email="Casey@Example.COM",  # case differs from the claim email
        org_id=org_id,
        invited_by_actor_id=inviter,
        role_id=admin_role_id,
    )
    result = resolve_sign_in(conn, _claims())
    assert result.outcome == OUTCOME_INVITE_ACCEPTED
    assert result.actor_id is not None
    # Identity is linked to the new actor.
    assert resolve_external_identity(
        conn, issuer=_ISSUER, subject="sub-1",
    ) == result.actor_id
    # Invite flipped to accepted and recorded who accepted it.
    accepted = get_invite(conn, invite.invite_id)
    assert accepted.status == INVITE_STATUS_ACCEPTED
    assert accepted.accepted_by_actor_id == result.actor_id
    # The invite's org role landed.
    assert require_org_permission(
        conn,
        actor_id=result.actor_id,
        org_id=org_id,
        permission_key=PERM_ORG_ADMIN,
    ).allowed
    # Label came from the email local part.
    label_row = conn.execute(
        "SELECT label FROM actor_labels WHERE actor_id = %s",
        (result.actor_id,),
    ).fetchone()
    assert label_row[0] == "casey"


def test_rung_two_pre_link_invite_binds_existing_actor(conn):
    inviter = _admin(conn)
    target = seed_human_actor(conn)
    org_id = default_org_id(conn)
    create_invite(
        conn,
        email="casey@example.com",
        org_id=org_id,
        invited_by_actor_id=inviter,
        actor_id=target,
    )
    before = conn.execute("SELECT COUNT(*) FROM actors").fetchone()[0]
    result = resolve_sign_in(conn, _claims())
    after = conn.execute("SELECT COUNT(*) FROM actors").fetchone()[0]
    assert result.outcome == OUTCOME_INVITE_ACCEPTED
    assert result.actor_id == target
    assert int(after) == int(before)  # no new actor created


def test_rung_three_auto_join_domain_creates_actor_without_role(conn):
    org_id = default_org_id(conn)
    set_auto_join_domain(conn, org_id=org_id, domain="@Example.com")
    result = resolve_sign_in(conn, _claims())
    assert result.outcome == OUTCOME_AUTO_JOINED
    assert result.actor_id is not None
    org_roles = conn.execute(
        "SELECT COUNT(*) FROM actor_org_roles WHERE actor_id = %s",
        (result.actor_id,),
    ).fetchone()[0]
    assert int(org_roles) == 0
    assert resolve_external_identity(
        conn, issuer=_ISSUER, subject="sub-1",
    ) == result.actor_id


def test_rung_four_refuses_with_reason(conn):
    result = resolve_sign_in(conn, _claims())
    assert result.outcome == OUTCOME_REFUSED
    assert result.actor_id is None
    assert result.refusal_reason == REFUSAL_NO_ADMISSION_MATCH
    assert "invite" in result.detail


def test_unverified_email_never_matches_invite_or_domain(conn):
    inviter = _admin(conn)
    org_id = default_org_id(conn)
    create_invite(
        conn, email="casey@example.com", org_id=org_id,
        invited_by_actor_id=inviter,
    )
    set_auto_join_domain(conn, org_id=org_id, domain="example.com")
    result = resolve_sign_in(conn, _claims(email_verified=False))
    assert result.outcome == OUTCOME_REFUSED
    assert result.refusal_reason == REFUSAL_EMAIL_UNVERIFIED


def test_omitted_email_verified_claim_is_strict_by_default(conn):
    org_id = default_org_id(conn)
    set_auto_join_domain(conn, org_id=org_id, domain="example.com")
    claims = _claims()
    del claims["email_verified"]
    result = resolve_sign_in(conn, claims)
    assert result.outcome == OUTCOME_REFUSED
    assert result.refusal_reason == REFUSAL_EMAIL_UNVERIFIED
    # Operator opt-in trusts the omitted claim.
    opted_in = resolve_sign_in(conn, claims, allow_unverified_email=True)
    assert opted_in.outcome == OUTCOME_AUTO_JOINED
    # But an explicit false is never trusted, opt-in or not.
    explicit_false = resolve_sign_in(
        conn,
        _claims(subject="sub-2", email_verified=False),
        allow_unverified_email=True,
    )
    assert explicit_false.outcome == OUTCOME_REFUSED


def test_string_typed_email_verified_is_read_by_value_not_truthiness(conn):
    # SAML->OIDC bridges serialize email_verified as the STRINGS "true"/
    # "false". A naive bool("false") is truthy and would admit an
    # unverified email; the claim must be read by value.
    org_id = default_org_id(conn)
    set_auto_join_domain(conn, org_id=org_id, domain="example.com")
    refused = resolve_sign_in(
        conn, _claims(subject="sub-str-false", email_verified="false"),
    )
    assert refused.outcome == OUTCOME_REFUSED
    assert refused.refusal_reason == REFUSAL_EMAIL_UNVERIFIED
    admitted = resolve_sign_in(
        conn, _claims(subject="sub-str-true", email_verified="true"),
    )
    assert admitted.outcome == OUTCOME_AUTO_JOINED


def test_missing_email_claim_refuses_with_its_own_reason(conn):
    result = resolve_sign_in(conn, _claims(email=""))
    assert result.outcome == OUTCOME_REFUSED
    assert result.refusal_reason == REFUSAL_MISSING_EMAIL_CLAIM


def test_missing_issuer_or_subject_refuses(conn):
    result = resolve_sign_in(conn, _claims(subject=""))
    assert result.outcome == OUTCOME_REFUSED
    assert result.refusal_reason == REFUSAL_MISSING_REQUIRED_CLAIMS


def test_label_collision_appends_numeric_suffix(conn):
    taken = seed_human_actor(conn)
    set_actor_label(conn, taken, "casey")
    org_id = default_org_id(conn)
    set_auto_join_domain(conn, org_id=org_id, domain="example.com")
    result = resolve_sign_in(conn, _claims())
    assert result.outcome == OUTCOME_AUTO_JOINED
    label_row = conn.execute(
        "SELECT label FROM actor_labels WHERE actor_id = %s",
        (result.actor_id,),
    ).fetchone()
    assert label_row[0] == "casey-2"
