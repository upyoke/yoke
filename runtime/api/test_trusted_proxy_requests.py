"""Real request consumers use Uvicorn's scheme/client trust boundary."""

import hashlib

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from uvicorn import Config

from runtime.api.fixtures import pg_testdb
from yoke_contracts.browser_sign_in import BROWSER_SIGN_IN_REDEEM_PATH
from yoke_contracts.machine_authorization import START_PATH, POLL_PATH
from yoke_core.api import server_entrypoint
from yoke_core.api.trusted_proxy import TrustedProxyHeadersMiddleware
from yoke_core.api.web_session_auth import cross_origin_refusal
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

    @app.get("/origin-check")
    def origin_check(request: Request):
        return cross_origin_refusal(request) or {"client": request.client.host}

    settings = server_entrypoint.resolve_settings(
        [], env={"YOKE_API_TRUSTED_PROXIES": trusted}
    )
    config = Config(
        TrustedProxyHeadersMiddleware(app, settings.trusted_proxies),
        proxy_headers=False,
        log_config=None,
    )
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


@pytest.mark.parametrize("trusted", [PROXY, "192.0.2.0/24", PROXY + ",::1", ""])
@pytest.mark.parametrize("peer", [PROXY, UNTRUSTED, CLIENT])
@pytest.mark.parametrize("forwarded_client", [CLIENT, PROXY, ""])
def test_forwarded_host_trust_uses_original_peer(peer, trusted, forwarded_client):
    external_host = "browser.example.test"
    headers = {
        **forwarded(forwarded_client),
        "X-Forwarded-Host": external_host,
        "Origin": f"https://{external_host}",
    }
    # CLIENT cannot attest itself by naming PROXY in X-Forwarded-For;
    # PROXY stays trusted when Uvicorn replaces its client with CLIENT.
    trusted_peer = bool(trusted) and (
        peer == PROXY or (trusted == "192.0.2.0/24" and peer == UNTRUSTED)
    )
    with serving_client(peer, trusted=trusted) as client:
        response = client.get("/origin-check", headers=headers)
        assert response.status_code == (200 if trusted_peer else 403), response.text
        headers["Origin"] = f"https://{HOST}"
        response = client.get("/origin-check", headers=headers)
        assert response.status_code == (403 if trusted_peer else 200), response.text


def test_trusted_proxy_can_preserve_host_without_forwarded_host():
    with serving_client(PROXY) as client:
        response = client.get("/origin-check", headers=forwarded())
    assert response.status_code == 200
    assert response.json()["client"] == CLIENT


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


@pytest.mark.parametrize("peer,expected", [(PROXY, 200), (UNTRUSTED, 403)])
def test_token_redemption_origin_uses_only_trusted_forwarded_host(
    database, peer, expected
):
    actor = seed_human_actor(database, "forwarded-browser-host")
    code = mint_browser_sign_in_link(database, actor_id=actor)
    headers = {
        **forwarded(),
        "X-Forwarded-Host": "browser.example.test",
        "Origin": "https://browser.example.test",
    }
    with serving_client(peer) as client:
        response = client.post(
            BROWSER_SIGN_IN_REDEEM_PATH, json={"code": code}, headers=headers
        )
    assert response.status_code == expected, response.text
    if expected == 200:
        assert "Secure" in response.headers["set-cookie"]
    else:
        assert response.json()["error"]["code"] == "cross_origin_refused"


# An admitted attribution read with no cookie answers attribution_absent (400);
# admission refusals answer 403 or 429 before the route reads anything.
ADMITTED = 400


@pytest.mark.parametrize("peer,expected", [(PROXY, ADMITTED), (UNTRUSTED, 403)])
def test_collector_origin_uses_only_trusted_forwarded_host(database, peer, expected):
    with serving_client(peer, scheme="https") as client:
        key = client.get("/api/events/config").json()["publishableKey"]
        response = client.get(
            "/api/events/attribution",
            headers={
                **forwarded(),
                "X-Forwarded-Host": "browser.example.test",
                "Origin": "https://browser.example.test",
                "X-Events-Key": key,
            },
        )
    assert response.status_code == expected, response.text
    if expected == 403:
        assert response.json()["error"] == "origin_not_allowed"
    else:
        assert response.json()["error"] == "attribution_absent"


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
            client.get("/api/events/attribution", headers=headers).status_code
            == ADMITTED
        )
        assert client.get("/api/events/attribution", headers=headers).status_code == 429
        headers.update(forwarded(OTHER_CLIENT))
        assert (
            client.get("/api/events/attribution", headers=headers).status_code
            == ADMITTED
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
            client.get("/api/events/attribution", headers=headers).status_code
            == ADMITTED
        )
        headers.update(forwarded(OTHER_CLIENT))
        assert client.get("/api/events/attribution", headers=headers).status_code == 429
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
