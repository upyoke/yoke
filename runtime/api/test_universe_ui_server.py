"""Session-token coverage for the local-universe UI server.

Pins the security contract of :mod:`yoke_core.ui.server`: every route
requires the per-run session token, exchanged from a query parameter for
a cookie before the page assets can load."""

from __future__ import annotations

import pytest

from runtime.api.universe_ui_server_test_support import (
    _TOKEN,
    ui_client as ui_client,
)
from yoke_core.ui import server as ui_server


class TestSessionTokenGate:
    def test_app_shell_refuses_without_token(self, ui_client):
        response = ui_client.get("/")
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "session_token_required"

    def test_wrong_token_refused(self, ui_client):
        assert ui_client.get("/?token=wrong").status_code == 401

    def test_non_ascii_token_refused_with_401(self, ui_client):
        # %C3%A9 decodes to a non-ASCII candidate; str-form
        # secrets.compare_digest would raise TypeError (a 500), so the
        # gate must compare bytes and land on the clean refusal.
        response = ui_client.get("/?token=caf%C3%A9")
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "session_token_required"

    def test_assets_and_api_refuse_without_token(self, ui_client):
        assert ui_client.get("/assets/app.js").status_code == 401
        response = ui_client.post(
            "/api/functions/call",
            json={"function": "organizations.get"},
        )
        assert response.status_code == 401

    def test_token_exchange_sets_cookie_and_redirects_to_bare_url(
        self,
        ui_client,
    ):
        # The 303 to bare "/" drops the tokened URL out of browser
        # history; the cookie it sets authenticates the follow-up.
        response = ui_client.get(f"/?token={_TOKEN}", follow_redirects=False)
        assert response.status_code == 303
        assert response.headers["location"] == "/"
        assert ui_server.SESSION_COOKIE_NAME in response.cookies

    def test_cookie_authenticates_shell_and_assets_after_exchange(
        self,
        ui_client,
    ):
        response = ui_client.get(f"/?token={_TOKEN}")  # follows the 303
        assert response.status_code == 200
        assert 'id="universe-root"' in response.text
        # The bare cookie-authenticated shell serves directly — no
        # further redirect.
        direct = ui_client.get("/", follow_redirects=False)
        assert direct.status_code == 200
        assert 'id="universe-root"' in direct.text
        # Subresource requests ride the cookie — no token re-threading.
        assert ui_client.get("/assets/app.js").status_code == 200

    def test_empty_token_never_matches(self):
        with pytest.raises(ui_server.UiServerError):
            ui_server.create_ui_app("")
