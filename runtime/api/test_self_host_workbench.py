"""The Yoke server serves the workbench and lets a signed-in browser write.

Drives the real FastAPI app: the workbench shell at the site root and its
deep paths, the public asset roster and served-build identity, and
``POST /v1/functions/call`` authorized by the web-session cookie under the
same-origin rule.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from runtime.api.fixtures import pg_testdb

# main must import before app_factory: the two modules are mutually
# referential and only resolve cleanly in this order.
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


def _host_packet(html: str) -> dict:
    start = html.index(HOST_IDENTITY_MARKER) + len(HOST_IDENTITY_MARKER)
    end = html.index(HOST_IDENTITY_MARKER, start)
    return json.loads(html[start:end])


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


class TestWorkbenchPages:
    @pytest.mark.parametrize("path", ["/", "/sessions", "/deployments/runs"])
    def test_signed_in_browser_gets_the_shell_for_its_actor(
        self,
        browser,
        actor_id,
        monkeypatch,
        path,
    ):
        monkeypatch.setenv("YOKE_BUILD_SHA", "0123456789abcdef")
        resp = browser.get(path)
        assert resp.status_code == 200
        assert "mountUniverseApp" in resp.text
        packet = _host_packet(resp.text)
        assert packet["currentActor"] == {"id": str(actor_id), "kind": "human"}
        assert packet["runtimeIdentity"]["portabilityMode"] == "selfhost"
        assert packet["runtimeIdentity"]["build"] == "0123456789abcdef"
        assert packet["environmentLabel"] == "self-hosted universe"
        assert packet["capabilities"]["data"]["portability"]["mode"] == "self-host"
        assert packet["functionCallEndpoint"] == _CALL_PATH

    def test_signed_out_visitor_gets_the_sign_in_page(self, db_conn):
        resp = TestClient(app_factory.create_app()).get("/sessions")
        assert resp.status_code == 200
        assert HOST_IDENTITY_MARKER not in resp.text
        assert "yoke ui up" in resp.text
        assert "yoke connect" in resp.text

    def test_misconfigured_sign_in_names_the_reason(self, db_conn, monkeypatch):
        monkeypatch.setenv("YOKE_OIDC_ISSUER", "https://issuer.example")
        resp = TestClient(app_factory.create_app()).get("/")
        assert resp.status_code == 503
        assert "YOKE_OIDC_CLIENT_ID" in resp.text

    def test_unknown_root_path_is_not_found(self, browser):
        assert browser.get("/no-such-view").status_code == 404

    def test_assets_and_served_build_are_public(self, db_conn, monkeypatch):
        monkeypatch.setenv("YOKE_BUILD_SHA", "fedcba9876543210")
        anonymous = TestClient(app_factory.create_app())
        app_js = anonymous.get("/assets/app.js")
        assert app_js.status_code == 200
        assert "javascript" in app_js.headers["content-type"]
        assert anonymous.get("/assets/not-in-roster.js").status_code == 404
        build = anonymous.get("/served-build")
        assert build.status_code == 200
        assert build.text == "fedcba9876543210"


class TestBrowserFunctionCalls:
    @pytest.mark.parametrize(
        "payload", ["invalid", 1, ["invalid"], [["open", True]], [], "", 0, False, None]
    )
    def test_non_object_payload_is_refused_before_dispatch(
        self, browser, monkeypatch, payload
    ):
        def unexpected_dispatch(*args, **kwargs):
            pytest.fail("a malformed browser payload must not reach the dispatcher")

        monkeypatch.setattr(browser_function_call, "dispatch", unexpected_dispatch)
        resp = _call(browser, "ui_preferences.nav_group.set", payload)
        assert resp.status_code == 422
        body = resp.json()
        assert body["success"] is False
        assert body["function"] == "ui_preferences.nav_group.set"
        assert body["error"]["code"] == "envelope_invalid"
        assert "payload must be a JSON object" in body["error"]["message"]
        assert "payload: {}" in body["error"]["message"]

    def test_write_lands_as_the_session_actor(self, browser):
        written = _call(
            browser,
            "ui_preferences.nav_group.set",
            {"group_id": "diagnostics", "open": True},
        )
        assert written.status_code == 200, written.text
        assert written.json()["success"] is True
        listed = _call(browser, "ui_preferences.nav_group.list", {})
        assert listed.json()["result"]["groups"] == {"diagnostics": True}

    def test_dispatch_binds_actor_and_browser_origin(
        self,
        browser,
        actor_id,
        monkeypatch,
    ):
        seen = {}
        real_dispatch = browser_function_call.dispatch

        def recording_dispatch(envelope, ambient_session_id=None):
            seen["envelope"] = envelope
            seen["ambient"] = ambient_session_id
            seen["browser_origin"] = ui_browser_origin_active()
            return real_dispatch(envelope, ambient_session_id=ambient_session_id)

        monkeypatch.setattr(browser_function_call, "dispatch", recording_dispatch)
        _call(browser, "ui_preferences.nav_group.list", {})
        assert seen["envelope"]["actor"] == {
            "actor_id": str(actor_id),
            "session_id": "",
        }
        assert seen["ambient"] == ""
        assert seen["browser_origin"] is True

    @pytest.mark.parametrize(
        "headers",
        [
            {"Origin": "https://attacker.example"},
            {"Origin": "null"},
            {"Sec-Fetch-Site": "cross-site"},
        ],
    )
    def test_cross_origin_call_is_refused_by_name(self, browser, headers):
        resp = _call(browser, "ui_preferences.nav_group.list", {}, **headers)
        assert resp.status_code == 403
        error = resp.json()["error"]
        assert error["code"] == "cross_origin_refused"
        assert "Authorization: Bearer" in error["message"]

    def test_unattested_forwarded_host_cannot_choose_the_server_origin(self, browser):
        resp = _call(
            browser,
            "ui_preferences.nav_group.list",
            {},
            Origin="https://yoke.example.com",
            **{"X-Forwarded-Host": "yoke.example.com"},
        )
        assert resp.status_code == 403, resp.text
        assert resp.json()["error"]["code"] == "cross_origin_refused"

    def test_declared_proxy_can_supply_the_browser_function_origin(self, browser):
        proxy_browser = TestClient(
            TrustedProxyHeadersMiddleware(browser.app, "192.0.2.0/24"),
            client=("192.0.2.10", 54321),
            cookies=browser.cookies,
        )
        resp = _call(
            proxy_browser,
            "ui_preferences.nav_group.list",
            {},
            Origin="https://yoke.example.com",
            **{
                "X-Forwarded-Host": "yoke.example.com",
                "X-Forwarded-For": "198.51.100.7",
            },
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["success"] is True

    def test_unknown_session_cookie_is_refused_by_name(self, db_conn):
        client = TestClient(
            app_factory.create_app(),
            cookies={WEB_SESSION_COOKIE_NAME: "not-minted"},
        )
        resp = _call(client, "ui_preferences.nav_group.list", {})
        assert resp.status_code == 401
        assert resp.json()["error"]["code"] == "web_session_invalid"

    def test_bearer_header_takes_the_bearer_path(self, browser):
        resp = _call(
            browser,
            "ui_preferences.nav_group.list",
            {},
            Authorization="Bearer not-a-real-token",
        )
        assert resp.status_code == 401
        assert resp.json()["error"]["code"] != "web_session_invalid"

    def test_cookie_authorizes_only_the_function_call_route(self, browser):
        resp = browser.post("/v1/items", json={}, headers={"Origin": _SERVER_ORIGIN})
        assert resp.status_code == 401
        assert resp.json()["error"]["code"] == "authentication_required"

    @pytest.mark.parametrize(
        ("function", "code"),
        [
            ("projects.github_binding.lifecycle", "permission_denied"),
            ("session_control.relay.liveness", "machine_credential_required"),
        ],
    )
    def test_credential_bound_functions_are_refused(self, browser, function, code):
        # The server registers every handler at startup; this client skips
        # the lifespan, so register them as the serving process would.
        register_all_handlers()
        resp = _call(browser, function, {})
        assert resp.json()["error"]["code"] == code
        assert "browser session" in resp.json()["error"]["message"]
