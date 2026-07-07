"""End-to-end coverage for the browser sign-in door.

Drives the real FastAPI app against an in-process stub OIDC provider:
start -> provider redirect -> callback (code exchange + id_token
verification + resolution ladder) -> web-session cookie -> landing page.
"""

from __future__ import annotations

import logging
import urllib.parse

import pytest
from fastapi.testclient import TestClient

from runtime.api.fixtures import pg_testdb
from runtime.api.oidc_provider_test_helpers import StubOidcProvider

# main must import before app_factory: the two modules are mutually
# referential and only resolve cleanly in this order.
import yoke_core.api.main  # noqa: F401  (import-order anchor)
from yoke_core.api import app_factory
from yoke_core.api.http_auth import (
    OIDC_CALLBACK_PATH,
    OIDC_START_PATH,
    WEB_SESSION_COOKIE_NAME,
)
from yoke_core.api.routes.web_sign_in import FLOW_COOKIE_NAME
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
from yoke_core.domain.actors import seed_human_actor
from yoke_core.domain.external_identities import (
    default_org_id,
    resolve_external_identity,
    set_auto_join_domain,
)


_OIDC_ENV_KEYS = (
    "YOKE_OIDC_ISSUER",
    "YOKE_OIDC_CLIENT_ID",
    "YOKE_OIDC_CLIENT_SECRET_FILE",
    "YOKE_OIDC_CLIENT_SECRET",
    "YOKE_OIDC_REDIRECT_URL",
    "YOKE_OIDC_ALLOW_UNVERIFIED_EMAIL",
)


@pytest.fixture(autouse=True)
def _clean_oidc_env(monkeypatch):
    for key in _OIDC_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)


@pytest.fixture()
def provider():
    stub = StubOidcProvider()
    yield stub
    stub.close()


@pytest.fixture()
def db_conn():
    with pg_testdb.test_database() as conn:
        yield conn


@pytest.fixture()
def client(db_conn):
    return TestClient(app_factory.create_app())


@pytest.fixture()
def door_env(provider, monkeypatch, tmp_path):
    secret_file = tmp_path / "oidc-client-secret"
    secret_file.write_text(provider.client_secret + "\n", encoding="utf-8")
    monkeypatch.setenv("YOKE_OIDC_ISSUER", provider.issuer)
    monkeypatch.setenv("YOKE_OIDC_CLIENT_ID", provider.client_id)
    monkeypatch.setenv("YOKE_OIDC_CLIENT_SECRET_FILE", str(secret_file))
    monkeypatch.setenv("YOKE_OIDC_REDIRECT_URL", "http://testserver")


def _start(client) -> dict:
    resp = client.get(OIDC_START_PATH, follow_redirects=False)
    assert resp.status_code == 302
    location = resp.headers["location"]
    return dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(location).query))


def _callback(client, *, code: str, state: str):
    return client.get(
        OIDC_CALLBACK_PATH,
        params={"code": code, "state": state},
        follow_redirects=False,
    )


def _sign_in(
    client,
    provider,
    *,
    email: str = "pat@example.com",
    email_verified=True,
    sub: str = "subject-1",
    **claim_overrides,
):
    query = _start(client)
    claims = provider.standard_claims(sub=sub, nonce=query["nonce"], email=email)
    if email_verified is not None:
        claims["email_verified"] = email_verified
    claims.update(claim_overrides)
    code = provider.issue_code(claims)
    return _callback(client, code=code, state=query["state"])


class TestFullFlow:
    def test_auto_join_flow_lands_signed_in(self, db_conn, client, door_env, provider):
        set_auto_join_domain(
            db_conn, org_id=default_org_id(db_conn), domain="example.com",
        )
        query = _start(client)
        assert query["redirect_uri"] == "http://testserver/v1/auth/oidc/callback"
        assert query["scope"] == "openid email profile"
        assert query["client_id"] == provider.client_id

        claims = provider.standard_claims(
            sub="subject-1", nonce=query["nonce"],
            email="pat@example.com", email_verified=True,
        )
        resp = _callback(
            client, code=provider.issue_code(claims), state=query["state"],
        )
        assert resp.status_code == 303
        assert resp.headers["location"] == "/"
        assert WEB_SESSION_COOKIE_NAME in client.cookies
        # Flow state is single-use: the callback deletes its cookie.
        assert FLOW_COOKIE_NAME not in client.cookies

        landing = client.get("/")
        assert landing.status_code == 200
        assert "pat" in landing.text
        assert "Default Org" in landing.text
        assert "yoke connect" in landing.text
        assert "Engine version" in landing.text

    def test_invite_flow_accepts_invite_and_grants_role(
        self, db_conn, client, door_env, provider,
    ):
        seed_roles_and_permissions(db_conn)
        org_id = default_org_id(db_conn)
        inviter = seed_human_actor(db_conn)
        invite = create_invite(
            db_conn,
            email="new@corp.example",
            org_id=org_id,
            invited_by_actor_id=inviter,
            role_id=role_id_by_name(db_conn, ROLE_ADMIN),
        )
        # Case-insensitive email match is part of the admission contract.
        resp = _sign_in(
            client, provider, email="New@Corp.Example", sub="subject-9",
        )
        assert resp.status_code == 303
        assert get_invite(db_conn, invite.invite_id).status == (
            INVITE_STATUS_ACCEPTED
        )
        actor_id = resolve_external_identity(
            db_conn, issuer=provider.issuer, subject="subject-9",
        )
        assert actor_id is not None
        require_org_permission(
            db_conn, actor_id=actor_id, org_id=org_id,
            permission_key=PERM_ORG_ADMIN,
        )


class TestFlowTamper:
    def test_state_mismatch_rejected(self, db_conn, client, door_env, provider):
        query = _start(client)
        code = provider.issue_code(
            provider.standard_claims(nonce=query["nonce"], email="a@b.example")
        )
        resp = _callback(client, code=code, state="not-the-minted-state")
        assert resp.status_code == 400
        assert WEB_SESSION_COOKIE_NAME not in client.cookies

    def test_callback_from_browser_that_never_started_rejected(
        self, db_conn, client, door_env, provider,
    ):
        query = _start(client)
        code = provider.issue_code(
            provider.standard_claims(nonce=query["nonce"], email="a@b.example")
        )
        other_browser = TestClient(app_factory.create_app())
        resp = _callback(other_browser, code=code, state=query["state"])
        assert resp.status_code == 400
        assert WEB_SESSION_COOKIE_NAME not in other_browser.cookies

    def test_nonce_mismatch_rejected(self, db_conn, client, door_env, provider):
        query = _start(client)
        code = provider.issue_code(
            provider.standard_claims(
                nonce="minted-elsewhere", email="a@b.example",
            )
        )
        resp = _callback(client, code=code, state=query["state"])
        assert resp.status_code == 401
        assert WEB_SESSION_COOKIE_NAME not in client.cookies

    @pytest.mark.parametrize(
        "skew",
        [
            {"aud": "some-other-client"},
            {"iss": "https://somewhere-else.example"},
            {"exp": 1},
        ],
    )
    def test_claim_skew_rejected(self, db_conn, client, door_env, provider, skew):
        resp = _sign_in(client, provider, **skew)
        assert resp.status_code == 401
        assert WEB_SESSION_COOKIE_NAME not in client.cookies


class TestAdmissionRefusals:
    def test_unverified_email_refused(self, db_conn, client, door_env, provider):
        set_auto_join_domain(
            db_conn, org_id=default_org_id(db_conn), domain="example.com",
        )
        resp = _sign_in(client, provider, email_verified=False)
        assert resp.status_code == 403
        assert WEB_SESSION_COOKIE_NAME not in client.cookies

    def test_no_admission_match_shows_operator_facing_reason(
        self, db_conn, client, door_env, provider,
    ):
        resp = _sign_in(client, provider)
        assert resp.status_code == 403
        assert "no pending invite" in resp.text


class TestDisabledDoor:
    def test_start_and_callback_answer_helpfully(self, db_conn, client):
        resp = client.get(OIDC_START_PATH)
        assert resp.status_code == 409
        assert resp.json()["error"]["code"] == "oidc_not_configured"
        assert "docs/self-host.md" in resp.json()["error"]["message"]
        assert client.get(OIDC_CALLBACK_PATH).status_code == 409

    def test_landing_offers_no_sign_in_link(self, db_conn, client):
        resp = client.get("/")
        assert resp.status_code == 200
        assert OIDC_START_PATH not in resp.text
        assert "yoke connect" in resp.text

    def test_partial_config_names_missing_vars(self, db_conn, client, monkeypatch):
        monkeypatch.setenv("YOKE_OIDC_ISSUER", "https://issuer.example")
        resp = client.get(OIDC_START_PATH)
        assert resp.status_code == 409
        body = resp.json()["error"]
        assert body["code"] == "oidc_misconfigured"
        assert "YOKE_OIDC_CLIENT_ID" in body["message"]


class TestCookieAuthorizationBoundary:
    def _signed_in_client(self, db_conn, client, provider):
        set_auto_join_domain(
            db_conn, org_id=default_org_id(db_conn), domain="example.com",
        )
        assert _sign_in(client, provider).status_code == 303
        return client

    def test_cookie_never_authorizes_writes(
        self, db_conn, client, door_env, provider,
    ):
        signed_in = self._signed_in_client(db_conn, client, provider)
        for method, target in (
            ("POST", "/v1/functions/call"),
            ("POST", "/v1/items"),
            ("POST", "/v1/items/1/approve"),
        ):
            resp = signed_in.request(method, target, json={})
            assert resp.status_code == 401, (method, target)
            assert resp.json()["error"]["code"] == "authentication_required"

    def test_cookie_failures_indistinguishable_from_absence(
        self, db_conn, client, door_env, provider,
    ):
        no_cookie = TestClient(app_factory.create_app())
        baseline = no_cookie.get("/")
        assert baseline.status_code == 200

        garbage = TestClient(app_factory.create_app())
        garbage.cookies.set(
            WEB_SESSION_COOKIE_NAME, "not-a-minted-token", domain="testserver",
        )
        assert garbage.get("/").text == baseline.text

        signed_in = self._signed_in_client(db_conn, client, provider)
        db_conn.execute("UPDATE web_sessions SET revoked_at = created_at")
        db_conn.commit()
        assert signed_in.get("/").text == baseline.text

    def test_secrets_never_reach_logs(
        self, db_conn, client, door_env, provider, caplog,
    ):
        with caplog.at_level(logging.DEBUG):
            self._signed_in_client(db_conn, client, provider)
            client.get("/")
        assert provider.client_secret not in caplog.text
        raw_session_token = client.cookies.get(WEB_SESSION_COOKIE_NAME)
        assert raw_session_token
        assert raw_session_token not in caplog.text
