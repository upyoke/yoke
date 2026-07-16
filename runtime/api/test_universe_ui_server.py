"""TestClient coverage for the token-gated local-universe UI server.

Pins the security contract of :mod:`yoke_core.ui.server`: every route
requires the per-run session token (query param exchanged for a cookie),
the function proxy admits only the read-only allowlist, and the page
assets resolve from the packaged ``yoke_core.ui`` static resources.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from yoke_core.ui import server as ui_server


_TOKEN = "test-session-token-value"


@pytest.fixture()
def ui_client():
    with TestClient(ui_server.create_ui_app(_TOKEN)) as client:
        yield client


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


class TestFunctionProxy:
    def _call(self, ui_client, envelope):
        return ui_client.post(
            f"/api/functions/call?token={_TOKEN}",
            json=envelope,
        )

    def test_write_function_id_refused(self, ui_client):
        response = self._call(
            ui_client,
            {"function": "items.structured_field.replace"},
        )
        assert response.status_code == 403
        body = response.json()
        assert body["error"]["code"] == "function_not_allowed"
        assert body["error"]["allowed"] == sorted(ui_server.UI_READ_FUNCTION_ALLOWLIST)

    def test_unknown_function_id_refused(self, ui_client):
        assert (
            self._call(
                ui_client,
                {"function": "no.such.function"},
            ).status_code
            == 403
        )

    def test_malformed_target_is_typed_422(self, ui_client):
        response = self._call(
            ui_client,
            {"function": "organizations.get", "target": {"kind": "bogus"}},
        )
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "target_invalid"

    def test_org_read_end_to_end(self, ui_client, test_db):
        from yoke_core.domain import org_schema

        org_schema.rename_org(test_db, "default", "UI Proof")
        response = self._call(ui_client, {"function": "organizations.get"})
        assert response.status_code == 200
        envelope = response.json()
        assert envelope["success"] is True
        assert envelope["result"]["name"] == "UI Proof"
        assert envelope["result"]["slug"] == "default"
        assert envelope["result"]["created_at"]

    def test_items_read_returns_well_formed_empty_table(
        self,
        ui_client,
        test_db,
    ):
        response = self._call(
            ui_client,
            {
                "function": "items.list.run",
                "payload": {"fields": ["id", "title", "status"]},
            },
        )
        assert response.status_code == 200
        envelope = response.json()
        assert envelope["success"] is True
        assert envelope["result"]["rows"] == []
        assert envelope["result"]["count"] == 0

    def test_projects_list_returns_well_formed_rows(self, ui_client, test_db):
        # Anonymous (cookie-only) identity: local mode makes every project
        # visible, so the seeded corpus comes back as a rows list.
        response = self._call(
            ui_client,
            {
                "function": "projects.list",
                "payload": {"fields": ["id", "slug", "name"]},
            },
        )
        assert response.status_code == 200
        envelope = response.json()
        assert envelope["success"] is True
        rows = envelope["result"]["rows"]
        assert isinstance(rows, list)
        assert any(row.get("slug") == "yoke" for row in rows)

    def test_deployment_runs_list_returns_well_formed_rows(
        self,
        ui_client,
        test_db,
    ):
        # The Runs view scopes through the payload (a project id from the
        # roster) and relies on the proxy's global-target default.
        response = self._call(
            ui_client,
            {"function": "deployment_runs.list", "payload": {}},
        )
        assert response.status_code == 200
        envelope = response.json()
        assert envelope["success"] is True
        assert envelope["result"]["rows"] == []
        for field in ("id", "flow", "target_env", "status", "current_stage"):
            assert field in envelope["result"]["fields"]

        projects = self._call(
            ui_client,
            {
                "function": "projects.list",
                "payload": {"fields": ["id", "slug", "name"]},
            },
        ).json()["result"]["rows"]
        scoped = self._call(
            ui_client,
            {
                "function": "deployment_runs.list",
                "payload": {"project": str(projects[0]["id"])},
            },
        )
        assert scoped.status_code == 200
        assert scoped.json()["success"] is True
        assert scoped.json()["result"]["rows"] == []

    def test_strategy_doc_list_with_project_target_reaches_handler(
        self,
        ui_client,
        test_db,
    ):
        # A project target is required; carry it the way the Strategy view
        # does and confirm the handler returns a well-formed docs list.
        projects = self._call(
            ui_client,
            {
                "function": "projects.list",
                "payload": {"fields": ["id", "slug", "name"]},
            },
        ).json()["result"]["rows"]
        project_id = str(projects[0]["id"])
        response = self._call(
            ui_client,
            {
                "function": "strategy.doc.list",
                "target": {"kind": "global", "project_id": project_id},
                "payload": {},
            },
        )
        assert response.status_code == 200
        envelope = response.json()
        assert envelope["success"] is True
        assert isinstance(envelope["result"]["docs"], list)

    def test_strategy_doc_list_without_project_is_graceful_error(
        self,
        ui_client,
        test_db,
    ):
        # No project target + the browser's empty session: the handler must
        # return a typed error envelope (HTTP 200, success=false), never a
        # 500 that would strand the view at "loading…".
        response = self._call(
            ui_client,
            {"function": "strategy.doc.list", "payload": {}},
        )
        assert response.status_code == 200
        envelope = response.json()
        assert envelope["success"] is False
        assert envelope["error"]["code"] == "project_context_required"

    def test_allowlist_ids_are_registered_claimless_reads(self):
        from yoke_core.domain.handlers.__init_register__ import (
            register_all_handlers,
        )
        from yoke_core.domain.yoke_function_actor_identity import is_read_only
        from yoke_core.domain.yoke_function_registry import lookup

        register_all_handlers()
        for function_id in ui_server.UI_READ_FUNCTION_ALLOWLIST:
            entry = lookup(function_id)
            assert entry is not None, function_id
            assert is_read_only(entry), function_id


class TestPortProbe:
    def test_default_port_is_probed_free_or_refused(self):
        import socket

        # Occupy an ephemeral port, then ask the resolver for exactly it.
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as holder:
            holder.bind(("127.0.0.1", 0))
            holder.listen(1)
            taken = holder.getsockname()[1]
            with pytest.raises(ui_server.UiServerError, match="--port"):
                ui_server.resolve_ui_port(taken)

    def test_explicit_free_port_round_trips(self):
        import socket

        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.bind(("127.0.0.1", 0))
            free_port = probe.getsockname()[1]
        assert ui_server.resolve_ui_port(free_port) == free_port

    def test_out_of_range_port_refused(self):
        with pytest.raises(ui_server.UiServerError, match="between"):
            ui_server.resolve_ui_port(70000)

    def test_port_zero_refused_not_silently_defaulted(self):
        with pytest.raises(ui_server.UiServerError, match="between"):
            ui_server.resolve_ui_port(0)

    def test_private_url_carries_the_token(self):
        url = ui_server.private_url(1234, "s3cret")
        assert url == "http://127.0.0.1:1234/?token=s3cret"

    def test_private_url_accepts_localhost(self):
        url = ui_server.private_url(1234, "s3cret", host="localhost")
        assert url == "http://localhost:1234/?token=s3cret"

    def test_remote_facing_host_refused(self):
        with pytest.raises(ui_server.UiServerError, match="loopback-only"):
            ui_server.resolve_ui_host("0.0.0.0")
