# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

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
