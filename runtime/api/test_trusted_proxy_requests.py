"""Real request consumers use Uvicorn's scheme/client trust boundary."""

import hashlib

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from uvicorn import Config

from runtime.api.fixtures import pg_testdb
from yoke_contracts.browser_sign_in import BROWSER_SIGN_IN_REDEEM_PATH
from yoke_contracts.machine_authorization import START_PATH, POLL_PATH
from yoke_core.api import server_entrypoint
from yoke_core.api.routes import (
    frontend_events,
    machine_authorization,
    token_browser_sign_in,
)
from yoke_core.domain import frontend_events_storage, machine_authorization_limits
from yoke_core.domain.actors import seed_human_actor
from yoke_core.domain.browser_sign_in_links import mint_browser_sign_in_link
from yoke_core.domain.external_identity_schema import create_external_identity_tables
from yoke_core.domain.frontend_events_schema import create_frontend_event_tables

PROXY = "192.0.2.10"
UNTRUSTED = "192.0.2.20"
CLIENT = "198.51.100.7"
OTHER_CLIENT = "198.51.100.8"
HOST = "workbench.example.test"


@pytest.fixture
def database(monkeypatch):
    monkeypatch.setattr(token_browser_sign_in, "resolve_oidc_config", lambda: None)
    with pg_testdb.test_database() as conn:
        create_external_identity_tables(conn)
        create_frontend_event_tables(conn)
        conn.commit()  # HTTP workers open independent connections.
        yield conn


def serving_client(peer, *, scheme="http", trusted=PROXY):
    app = FastAPI()
    app.include_router(token_browser_sign_in.router, prefix="/v1")
    app.include_router(frontend_events.router)
    app.include_router(machine_authorization.router)
    settings = server_entrypoint.resolve_settings(
        [], env={"YOKE_API_TRUSTED_PROXIES": trusted}
    )
    config = Config(app, forwarded_allow_ips=settings.trusted_proxies, log_config=None)
    config.load()
    return TestClient(
        config.loaded_app, base_url=f"{scheme}://{HOST}", client=(peer, 43210)
    )


def forwarded(client=CLIENT):
    return {
        "X-Forwarded-Proto": "https",
        "X-Forwarded-For": client,
        "Origin": f"https://{HOST}",
    }


@pytest.mark.parametrize("peer,secure", [(PROXY, True), (UNTRUSTED, False)])
def test_token_cookie_uses_only_trusted_forwarded_scheme(database, peer, secure):
    actor = seed_human_actor(database, "proxy-browser")
    code = mint_browser_sign_in_link(database, actor_id=actor)
    with serving_client(peer) as client:
        response = client.post(
            BROWSER_SIGN_IN_REDEEM_PATH, json={"code": code}, headers=forwarded()
        )
    assert response.status_code == 200, response.text
    assert ("Secure" in response.headers["set-cookie"]) is secure


@pytest.mark.parametrize("peer,expected", [(PROXY, 200), (UNTRUSTED, 400)])
def test_collector_requires_actual_or_trusted_https(database, peer, expected):
    with serving_client(peer) as client:
        response = client.get("/api/events/config", headers=forwarded())
    assert response.status_code == expected, response.text
    if expected == 400:
        assert response.json()["error"] == "collector_https_required"
        assert "YOKE_API_TRUSTED_PROXIES" in response.json()["recovery"]
    else:
        assert response.json()["publishableKey"]


@pytest.mark.parametrize("trusted", [PROXY, "192.0.2.0/24", PROXY + ",::1"])
def test_collector_budgets_forwarded_clients_independently(
    database, monkeypatch, trusted
):
    monkeypatch.setattr(frontend_events_storage, "RATE_REQUESTS", 1)
    with serving_client(PROXY, trusted=trusted) as client:
        key = client.get("/api/events/config", headers=forwarded()).json()[
            "publishableKey"
        ]
        headers = {**forwarded(), "X-Events-Key": key}
        assert (
            client.delete("/api/events/attribution", headers=headers).status_code == 200
        )
        assert (
            client.delete("/api/events/attribution", headers=headers).status_code == 429
        )
        headers.update(forwarded(OTHER_CLIENT))
        assert (
            client.delete("/api/events/attribution", headers=headers).status_code == 200
        )
    assert (
        database.execute("SELECT count(*) FROM frontend_event_rate_limits").fetchone()[
            0
        ]
        == 2
    )


def test_untrusted_forwarded_clients_share_transport_budget(database, monkeypatch):
    monkeypatch.setattr(frontend_events_storage, "RATE_REQUESTS", 1)
    with serving_client(UNTRUSTED, scheme="https") as client:
        key = client.get("/api/events/config").json()["publishableKey"]
        headers = {**forwarded(), "X-Events-Key": key}
        assert (
            client.delete("/api/events/attribution", headers=headers).status_code == 200
        )
        headers.update(forwarded(OTHER_CLIENT))
        assert (
            client.delete("/api/events/attribution", headers=headers).status_code == 429
        )
    assert (
        database.execute("SELECT count(*) FROM frontend_event_rate_limits").fetchone()[
            0
        ]
        == 1
    )


@pytest.mark.parametrize("peer", [PROXY, UNTRUSTED])
@pytest.mark.parametrize(
    "path,operation,setting",
    [(START_PATH, "start", "START_REQUESTS"), (POLL_PATH, "poll", "POLL_REQUESTS")],
)
def test_machine_budgets_use_trusted_clients_or_transport_peer(
    database, monkeypatch, peer, path, operation, setting
):
    monkeypatch.setattr(machine_authorization_limits, setting, 1)
    with serving_client(peer) as client:
        # Invalid bodies still consume admission, without needing an OIDC provider.
        assert client.post(path, json={}, headers=forwarded()).status_code == 400
        assert client.post(path, json={}, headers=forwarded()).status_code == 429
        response = client.post(path, json={}, headers=forwarded(OTHER_CLIENT))
    assert response.status_code == (400 if peer == PROXY else 429), response.text
    rows = database.execute(
        "SELECT client_key FROM machine_authorization_rate_limits WHERE operation=%s",
        (operation,),
    ).fetchall()
    expected = {CLIENT, OTHER_CLIENT} if peer == PROXY else {UNTRUSTED}
    assert {row[0] for row in rows} == {
        hashlib.sha256(ip.encode()).hexdigest() for ip in expected
    }
