"""What the engine collector stamps: emitter fields, environment, and viewer."""

import json

from fastapi.testclient import TestClient

from runtime.api.test_frontend_events import client, database, event, headers
from yoke_core.api.observability_otel import environment_name
from yoke_core.domain.actors import seed_human_actor

database = database
client = client
LOCAL = "http://127.0.0.1:8689"


def test_rows_keep_emitter_service_and_project_and_carry_serving_environment(
    client, database
):
    payload = event()
    response = client.post(
        "/api/events", json={"events": [payload]}, headers=headers(client)
    )
    assert response.status_code == 200, response.text
    with database() as conn:
        service, environment, project_id, raw = conn.execute(
            "SELECT service, environment, project_id, envelope FROM events "
            "WHERE event_id=%s",
            (payload["event_id"],),
        ).fetchone()
    stored = json.loads(raw) if isinstance(raw, str) else raw
    assert (service, environment, project_id) == ("web", environment_name(), None)
    assert stored["project"] == "yoke" and stored["environment"] == environment


def test_token_admitted_local_page_views_carry_the_local_operator(
    database, monkeypatch
):
    from yoke_core.ui import server

    monkeypatch.setattr(server, "serving_connection", lambda: ("validation", None))
    with database() as conn:
        operator = seed_human_actor(conn, "local operator")
    monkeypatch.setattr(server, "_local_operator_actor_id", lambda: operator)
    local = TestClient(server.create_ui_app("door", port=8689), base_url=LOCAL)
    admitted = headers(local, LOCAL)
    anonymous = {**event(), "page_url": LOCAL + "/items"}
    assert (
        local.post(
            "/api/events", json={"events": [anonymous]}, headers=admitted
        ).status_code
        == 200
    )
    local.cookies.set(server.session_cookie_name(8689), "door")
    viewed = {**event(), "page_url": LOCAL + "/items"}
    assert (
        local.post(
            "/api/events", json={"events": [viewed]}, headers=admitted
        ).status_code
        == 200
    )
    with database() as conn:
        stamped = dict(
            conn.execute(
                "SELECT event_id, actor_id FROM events WHERE event_id IN (%s, %s)",
                (anonymous["event_id"], viewed["event_id"]),
            ).fetchall()
        )
    assert stamped == {anonymous["event_id"]: None, viewed["event_id"]: operator}
