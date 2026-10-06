"""API-token browser admission, exercised through the serving HTTP boundary."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
from datetime import timedelta
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from runtime.api.fixtures import pg_testdb
import yoke_core.api.main  # noqa: F401 - app factory import-order anchor
from yoke_contracts.browser_sign_in import (
    BROWSER_SIGN_IN_PATH,
    BROWSER_SIGN_IN_REDEEM_PATH,
)
from yoke_core.api import app_factory
from yoke_core.api.routes import token_browser_sign_in as routes
from yoke_core.api.web_session_auth import WEB_SESSION_COOKIE_NAME
from yoke_core.domain import browser_sign_in_links as links, db_helpers
from yoke_core.domain.actors import seed_human_actor
from yoke_core.domain.api_tokens import mint_token
from yoke_core.domain.external_identity_schema import create_external_identity_tables
from yoke_core.ui.workbench_shell import HOST_IDENTITY_MARKER


@pytest.fixture()
def context(monkeypatch):
    monkeypatch.setattr(routes, "resolve_oidc_config", lambda: None)
    with pg_testdb.test_database() as conn:
        create_external_identity_tables(conn)
        actor_id = seed_human_actor(conn, "pat")
        token = mint_token(conn, actor_id=actor_id, name="test-client")
        yield (
            conn,
            actor_id,
            token,
            TestClient(app_factory.create_app(), base_url="https://testserver"),
        )


def _mint(client, token):
    response = client.post(
        BROWSER_SIGN_IN_PATH, headers={"Authorization": f"Bearer {token.raw_token}"}
    )
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"
    payload = response.json()
    assert payload["auth_method"] == "token"
    assert payload["expires_in"] == links.BROWSER_SIGN_IN_TTL_S
    return payload["sign_in_path"].partition("#")[2]


def _redeem(client, code, **headers):
    return client.post(
        BROWSER_SIGN_IN_REDEEM_PATH,
        json={"code": code},
        headers={"Origin": "https://testserver", **headers},
    )


def test_link_opens_normal_workbench_session_for_token_actor(context):
    conn, actor_id, token, client = context
    code = _mint(client, token)
    selector, _, secret = code.partition(".")
    row = conn.execute(
        "SELECT code_hash, actor_id FROM browser_sign_in_links WHERE selector=%s",
        (selector,),
    ).fetchone()
    assert row[0] != secret and row[0] != code
    assert row[1] == actor_id
    page = client.get(BROWSER_SIGN_IN_REDEEM_PATH)
    assert "location.hash.slice(1)" in page.text
    assert "history.replaceState" in page.text
    assert page.headers["referrer-policy"] == "no-referrer"
    response = _redeem(client, code)
    assert response.status_code == 200, response.text
    cookie = response.headers["set-cookie"]
    assert "Secure" in cookie and "HttpOnly" in cookie and "SameSite=lax" in cookie
    assert client.cookies.get(WEB_SESSION_COOKIE_NAME)
    workbench = client.get("/sessions")
    assert "mountUniverseApp" in workbench.text
    packet_text = workbench.text.split(HOST_IDENTITY_MARKER)[1]
    assert json.loads(packet_text)["currentActor"]["id"] == str(actor_id)


def test_replay_refuses_and_preserves_first_session(context):
    conn, _, token, client = context
    code = _mint(client, token)
    assert _redeem(client, code).status_code == 200
    response = _redeem(client, code)
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "browser_sign_in_used"
    assert "yoke ui up" in response.json()["error"]["message"]
    assert conn.execute("SELECT count(*) FROM web_sessions").fetchone()[0] == 1


def test_expiry_refuses_at_deadline_without_minting(context, monkeypatch):
    conn, _, token, client = context
    start = links._now()
    monkeypatch.setattr(links, "_now", lambda: start)
    code = _mint(client, token)
    monkeypatch.setattr(
        links, "_now", lambda: start + timedelta(seconds=links.BROWSER_SIGN_IN_TTL_S)
    )
    response = _redeem(client, code)
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "browser_sign_in_expired"
    assert "yoke ui up" in response.json()["error"]["message"]
    assert conn.execute("SELECT count(*) FROM web_sessions").fetchone()[0] == 0


@pytest.mark.parametrize(
    "headers",
    [
        {"Origin": "https://attacker.example"},
        {"Origin": "null"},
        {"Sec-Fetch-Site": "cross-site"},
    ],
)
def test_cross_origin_redemption_cannot_consume_link(context, headers):
    _, _, token, client = context
    code = _mint(client, token)
    response = _redeem(client, code, **headers)
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "cross_origin_refused"
    assert _redeem(client, code).status_code == 200


def test_unknown_and_tampered_links_refuse(context, monkeypatch):
    _, _, token, client = context
    code = _mint(client, token)
    seen = []
    compare = links.hmac.compare_digest
    monkeypatch.setattr(
        links.hmac, "compare_digest", lambda a, b: seen.append((a, b)) or compare(a, b)
    )
    for bad in ("unknown.invalid", code[:-1] + ("A" if code[-1] != "A" else "B"), ""):
        response = _redeem(client, bad)
        assert response.json()["error"]["code"] == "browser_sign_in_invalid"
    assert len(seen) == 2
    assert _redeem(client, code).status_code == 200


def test_actor_disabled_after_exchange_cannot_redeem(context):
    conn, actor_id, token, client = context
    code = _mint(client, token)
    conn.execute("UPDATE actors SET status='disabled' WHERE id=%s", (actor_id,))
    conn.commit()
    response = _redeem(client, code)
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "actor_disabled"
    assert conn.execute("SELECT count(*) FROM web_sessions").fetchone()[0] == 0


def test_exchange_requires_bearer_not_browser_cookie(context):
    _, _, token, client = context
    assert client.get(BROWSER_SIGN_IN_PATH).json() == {"auth_method": "token"}
    assert client.post(BROWSER_SIGN_IN_PATH).status_code == 401
    assert (
        client.post(
            BROWSER_SIGN_IN_PATH, headers={"Authorization": "Bearer invalid"}
        ).status_code
        == 401
    )
    assert _redeem(client, _mint(client, token)).status_code == 200
    assert client.cookies.get(WEB_SESSION_COOKIE_NAME)
    assert client.post(BROWSER_SIGN_IN_PATH).status_code == 401


@pytest.mark.parametrize(
    "path", ["/v1/items", BROWSER_SIGN_IN_PATH + "/other", BROWSER_SIGN_IN_PATH + "/"]
)
def test_method_discovery_does_not_admit_other_get_paths(context, path):
    _, _, _, client = context
    assert client.get(path).status_code == 401


@pytest.mark.parametrize("method", ["HEAD", "PUT", "DELETE", "PATCH"])
def test_method_discovery_does_not_admit_other_methods(context, method):
    _, _, _, client = context
    assert client.request(method, BROWSER_SIGN_IN_PATH).status_code == 401


def test_oidc_opens_root_and_blocks_token_door(context, monkeypatch):
    conn, _, token, client = context
    code = _mint(client, token)
    monkeypatch.setattr(routes, "resolve_oidc_config", lambda: SimpleNamespace())
    assert client.get(BROWSER_SIGN_IN_PATH).json() == {"auth_method": "oidc"}
    response = client.post(
        BROWSER_SIGN_IN_PATH, headers={"Authorization": f"Bearer {token.raw_token}"}
    )
    assert response.json() == {"auth_method": "oidc", "sign_in_path": "/"}
    assert client.get(BROWSER_SIGN_IN_REDEEM_PATH).status_code == 409
    assert (
        _redeem(client, code).json()["error"]["code"] == "browser_sign_in_oidc_required"
    )
    assert conn.execute("SELECT count(*) FROM web_sessions").fetchone()[0] == 0


def test_misconfigured_oidc_does_not_fall_through(context, monkeypatch):
    from yoke_core.api.oidc_config import OidcConfigError

    _, _, token, client = context

    def broken_config():
        raise OidcConfigError("YOKE_OIDC_CLIENT_ID is missing")

    monkeypatch.setattr(routes, "resolve_oidc_config", broken_config)
    response = client.post(
        BROWSER_SIGN_IN_PATH, headers={"Authorization": f"Bearer {token.raw_token}"}
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "oidc_misconfigured"


def test_concurrent_workers_mint_only_one_session(context):
    conn, actor_id, token, client = context
    code = _mint(client, token)
    # Release the fixture's read transaction before two independent workers race.
    conn.commit()

    def redeem():
        with db_helpers.connect() as worker:
            try:
                return links.redeem_browser_sign_in_link(worker, code).actor_id
            except links.BrowserSignInError as exc:
                return exc.code

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: redeem(), range(2)))
    assert actor_id in results and "browser_sign_in_used" in results
    assert conn.execute("SELECT count(*) FROM web_sessions").fetchone()[0] == 1
