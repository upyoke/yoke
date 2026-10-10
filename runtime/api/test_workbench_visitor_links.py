"""Web sign-in links browser visitor ids to actors; sign-out rotates the id."""

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from runtime.api import test_web_sign_in_door as door
from yoke_core.api import app_factory
from yoke_core.api.http_auth import SIGN_OUT_PATH
from yoke_core.api.web_session_auth import WEB_SESSION_COOKIE_NAME
from yoke_core.domain.actor_visitor_links import (
    ALREADY_LINKED,
    LINKED_TO_OTHER_ACTOR,
    record_visitor_link,
)
from yoke_core.domain.actors import seed_human_actor
from yoke_core.domain.external_identities import resolve_external_identity
from yoke_core.domain.frontend_events_schema import create_frontend_event_tables
from yoke_core.domain.schema_init_actor_path_claim_tables import (
    create_actor_identity_tables,
)

db_conn = door.db_conn
provider = door.provider
door_env = door.door_env
ORIGIN = "https://testserver"

#: The documented query-time join from page views to their actor.
PAGE_VIEWS_FOR_ACTOR = (
    "SELECT e.event_id FROM events e JOIN actor_visitor_links l "
    "ON l.visitor_id = (e.envelope::jsonb ->> 'visitor_id') "
    "WHERE e.source_type = 'frontend' AND l.actor_id = %s"
)


@pytest.fixture
def collector(db_conn):
    create_frontend_event_tables(db_conn)
    create_actor_identity_tables(db_conn)
    door._enable_domain_admission(db_conn, domain="example.com")
    db_conn.commit()


def browser():
    return TestClient(app_factory.create_app(), base_url=ORIGIN)


def capture(client):
    key = client.get("/api/events/config").json()["publishableKey"]
    headers = {"Origin": ORIGIN, "X-Events-Key": key}
    response = client.post(
        "/api/events/attribution",
        headers=headers,
        json={"url": ORIGIN + "/?utm_source=newsletter", "referrer": ""},
    )
    assert response.status_code == 200, response.text
    return response.json()["visitor_id"], headers


def page_view(client, headers, visitor_id):
    payload = {
        "event_id": str(uuid4()),
        "event_name": "PageViewed",
        "event_kind": "analytics",
        "event_type": "page_view",
        "event_time": "2026-01-01T00:00:00Z",
        "session_id": str(uuid4()),
        "source_type": "frontend",
        "service": "web",
        "project": "yoke",
        "visitor_id": visitor_id,
        "page_url": ORIGIN + "/items",
    }
    response = client.post("/api/events", json={"events": [payload]}, headers=headers)
    assert response.status_code == 200, response.text
    return payload["event_id"]


def links(conn, actor_id):
    return {
        row[0]
        for row in conn.execute(
            "SELECT visitor_id FROM actor_visitor_links WHERE actor_id=%s", (actor_id,)
        ).fetchall()
    }


def test_each_browser_sign_in_links_its_visitor_and_joins_earlier_page_views(
    db_conn, provider, door_env, collector
):
    first, second = browser(), browser()
    first_visitor, first_headers = capture(first)
    anonymous_view = page_view(first, first_headers, first_visitor)
    second_visitor, _ = capture(second)
    assert door._sign_in(first, provider).status_code == 303
    assert door._sign_in(second, provider).status_code == 303
    actor_id = resolve_external_identity(
        db_conn, issuer=provider.issuer, subject="subject-1"
    )
    assert links(db_conn, actor_id) == {first_visitor, second_visitor}
    signed_in_view = page_view(first, first_headers, first_visitor)
    stamped = db_conn.execute(
        "SELECT event_id, actor_id FROM events WHERE source_type='frontend'"
    ).fetchall()
    assert dict(stamped) == {anonymous_view: None, signed_in_view: actor_id}
    joined = {row[0] for row in db_conn.execute(PAGE_VIEWS_FOR_ACTOR, (actor_id,))}
    assert joined == {anonymous_view, signed_in_view}


def test_visitor_linked_to_one_actor_is_refused_for_another_by_name(db_conn):
    holder = seed_human_actor(db_conn, "holder")
    other = seed_human_actor(db_conn, "other")
    visitor = str(uuid4())
    assert not record_visitor_link(db_conn, visitor_id=visitor, actor_id=holder).refused
    again = record_visitor_link(db_conn, visitor_id=visitor, actor_id=holder)
    assert again.outcome == ALREADY_LINKED
    refused = record_visitor_link(db_conn, visitor_id=visitor, actor_id=other)
    assert refused.outcome == LINKED_TO_OTHER_ACTOR
    assert refused.linked_actor_id == holder
    row = db_conn.execute(
        "SELECT actor_id, refused_actor_id, refused_at FROM actor_visitor_links "
        "WHERE visitor_id=%s",
        (visitor,),
    ).fetchone()
    assert row[0] == holder and row[1] == other and row[2]


def test_sign_out_revokes_session_and_next_capture_mints_a_new_visitor(
    db_conn, provider, door_env, collector
):
    client = browser()
    visitor, _ = capture(client)
    assert door._sign_in(client, provider).status_code == 303
    assert client.cookies.get(WEB_SESSION_COOKIE_NAME)
    refused = client.post(SIGN_OUT_PATH, headers={"Origin": "https://attacker.test"})
    assert refused.status_code == 403
    response = client.post(SIGN_OUT_PATH, headers={"Origin": ORIGIN})
    assert response.status_code == 200, response.text
    cleared = response.headers.get_list("set-cookie")
    assert any(c.startswith(WEB_SESSION_COOKIE_NAME + "=") for c in cleared)
    assert any("events_attribution" in c and "Max-Age=0" in c for c in cleared)
    assert db_conn.execute("SELECT revoked_at FROM web_sessions").fetchone()[0]
    rotated, _ = capture(client)
    assert rotated != visitor
