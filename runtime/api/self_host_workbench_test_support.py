# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

import json

import pytest

from fastapi.testclient import TestClient

from runtime.api.fixtures import pg_testdb

import yoke_core.api.main  # noqa: F401  (import-order anchor)

from yoke_contracts.ui_browser_origin import ui_browser_origin_active

from yoke_core.api import app_factory, browser_function_call

from yoke_core.api.trusted_proxy import TrustedProxyHeadersMiddleware

from yoke_core.api.web_session_auth import WEB_SESSION_COOKIE_NAME

from yoke_core.domain.actors import seed_human_actor

from yoke_core.domain.handlers.__init_register__ import register_all_handlers

from yoke_core.domain.web_sessions import mint_web_session

from yoke_core.ui.workbench_shell import HOST_IDENTITY_MARKER

_SERVER_ORIGIN = "http://testserver"

_CALL_PATH = "/v1/functions/call"


def _call(client, function: str, payload: dict, **headers):
    return client.post(
        _CALL_PATH,
        json={
            "function": function,
            "version": "v1",
            "actor": {"actor_id": "999999", "session_id": "spoofed-session"},
            "target": {"kind": "global"},
            "payload": payload,
        },
        headers={"Origin": _SERVER_ORIGIN, **headers},
    )


@pytest.fixture(autouse=True)
def _no_oidc(monkeypatch):
    for key in (
        "YOKE_OIDC_ISSUER",
        "YOKE_OIDC_CLIENT_ID",
        "YOKE_OIDC_CLIENT_SECRET_FILE",
        "YOKE_OIDC_CLIENT_SECRET",
        "YOKE_OIDC_REDIRECT_URL",
    ):
        monkeypatch.delenv(key, raising=False)


@pytest.fixture()
def db_conn():
    with pg_testdb.test_database() as conn:
        yield conn


@pytest.fixture()
def actor_id(db_conn):
    actor = seed_human_actor(db_conn, "pat")
    db_conn.commit()
    return actor


@pytest.fixture()
def browser(db_conn, actor_id):
    session = mint_web_session(db_conn, actor_id=actor_id)
    db_conn.commit()
    return TestClient(
        app_factory.create_app(),
        cookies={WEB_SESSION_COOKIE_NAME: session.raw_token},
    )
