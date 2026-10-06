"""Signed cookie acquisition travels through the real OIDC actor-creation door."""

import json

import pytest
from fastapi.testclient import TestClient

from runtime.api import test_web_sign_in_door as door
from yoke_core.api import app_factory, frontend_events_config
from yoke_core.domain.external_identities import resolve_external_identity
from yoke_core.domain.frontend_events_schema import create_frontend_event_tables
from yoke_core.domain.schema_init_actor_path_claim_tables import (
    create_actor_identity_tables,
)

db_conn = door.db_conn
provider = door.provider
door_env = door.door_env


@pytest.mark.parametrize("capture_available", [True, False])
def test_actor_creation_keeps_verified_acquisition_without_depending_on_events(
    db_conn, provider, door_env, monkeypatch, capture_available
):
    origin = "https://testserver"
    client = TestClient(app_factory.create_app(), base_url=origin)
    create_frontend_event_tables(db_conn)
    create_actor_identity_tables(db_conn)
    db_conn.commit()
    door._enable_domain_admission(db_conn, domain="example.com")
    config = client.get("/api/events/config")
    assert config.status_code == 200, config.text
    key = config.json()["publishableKey"]
    capture = client.post(
        "/api/events/attribution",
        headers={"Origin": origin, "X-Events-Key": key},
        json={
            "url": origin + "/?utm_source=newsletter&utm_medium=email&token=private",
            "referrer": "",
        },
    )
    assert capture.status_code == 200
    if not capture_available:

        def unavailable(*args):
            raise RuntimeError("disposable capture unavailable")

        monkeypatch.setattr(frontend_events_config, "verified_attribution", unavailable)
    assert door._sign_in(client, provider).status_code == 303
    actor_id = resolve_external_identity(
        db_conn, issuer=provider.issuer, subject="subject-1"
    )
    raw = db_conn.execute(
        "SELECT attribution FROM actors WHERE id=%s", (actor_id,)
    ).fetchone()[0]
    if capture_available:
        record = json.loads(raw)
        assert record == capture.json()
        assert "private" not in raw
        assert record["first_touch"]["acquisition_channel"] == "email"
    else:
        assert raw is None
    assert (
        db_conn.execute(
            "SELECT COUNT(*) FROM events WHERE source_type='frontend'"
        ).fetchone()[0]
        == 0
    )
