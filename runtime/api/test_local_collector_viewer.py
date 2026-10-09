"""The Local view's collector stamps its operator only on token-admitted views."""

from fastapi.testclient import TestClient

from runtime.api.test_frontend_events import database, event, headers
from yoke_core.domain.actors import seed_human_actor

database = database
LOCAL = "http://127.0.0.1:8689"


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
