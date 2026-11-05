# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

from runtime.api.self_host_workbench_test_support import db_conn as db_conn

import logging

import urllib.parse

import pytest

from fastapi.testclient import TestClient

from runtime.api.fixtures import pg_testdb

from yoke_core.api.oidc_stub_provider import StubOidcProvider

import yoke_core.api.main  # noqa: F401  (import-order anchor)

from yoke_core.api import app_factory

from yoke_core.api.http_auth import OIDC_CALLBACK_PATH, OIDC_START_PATH

from yoke_core.api.routes.web_sign_in import FLOW_COOKIE_NAME

from yoke_core.api.web_session_auth import WEB_SESSION_COOKIE_NAME

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
    set_organization_domain,
)

from yoke_core.domain.organization_settings import merge_organization_settings

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


def _enable_domain_admission(conn, *, domain: str) -> None:
    org_id = default_org_id(conn)
    set_organization_domain(conn, org_id=org_id, domain=domain)
    merge_organization_settings(
        conn,
        org_id,
        {"membership.auto_join_domain_verified": True},
    )
