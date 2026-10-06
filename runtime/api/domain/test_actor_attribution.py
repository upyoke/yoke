"""Signed-in acquisition belongs to actors even when telemetry is absent."""

import json

from runtime.api.domain.test_sign_in_resolution import conn as actor_database
from yoke_core.domain.actor_invites import create_invite
from yoke_core.domain.actors import seed_human_actor
from yoke_core.domain.external_identities import default_org_id
from yoke_core.domain.sign_in_resolution import resolve_sign_in

conn = actor_database


def test_new_signed_in_actor_keeps_verified_acquisition_snapshot(conn):
    admin = seed_human_actor(conn, "Admin")
    create_invite(
        conn,
        org_id=default_org_id(conn),
        email="new@example.com",
        invited_by_actor_id=admin,
    )
    record = {
        "visitor_id": "visitor",
        "first_touch": {"acquisition_channel": "organic_search"},
        "last_touch": {"acquisition_channel": "email"},
    }
    claims = {
        "iss": "https://issuer.example",
        "sub": "new-subject",
        "email": "new@example.com",
        "email_verified": True,
    }
    result = resolve_sign_in(conn, claims, attribution=record)
    assert result.succeeded
    stored = conn.execute(
        "SELECT attribution FROM actors WHERE id=%s", (result.actor_id,)
    ).fetchone()[0]
    assert json.loads(stored) == record
    resolve_sign_in(conn, claims, attribution={**record, "visitor_id": "later"})
    assert (
        conn.execute(
            "SELECT attribution FROM actors WHERE id=%s", (result.actor_id,)
        ).fetchone()[0]
        == stored
    )


def test_actor_created_without_attribution_cookie_has_no_attribution(conn):
    actor = seed_human_actor(conn, "Local")
    assert (
        conn.execute("SELECT attribution FROM actors WHERE id=%s", (actor,)).fetchone()[
            0
        ]
        is None
    )
