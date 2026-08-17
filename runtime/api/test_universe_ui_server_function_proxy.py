"""Allowlist and read coverage for the local-universe function proxy."""

from __future__ import annotations

from runtime.api.universe_ui_server_test_support import (
    _TOKEN,
    ui_client as ui_client,
)
from yoke_core.ui import server as ui_server


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
        allowed = (
            ui_server.UI_READ_FUNCTION_ALLOWLIST
            | ui_server.UI_MUTATION_FUNCTION_ALLOWLIST
        )
        assert body["error"]["allowed"] == sorted(allowed)

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

    def test_overview_vitals_returns_dense_authoritative_series(
        self,
        ui_client,
        test_db,
    ):
        response = self._call(
            ui_client,
            {
                "function": "overview.vitals.get",
                "payload": {"days": 2},
            },
        )
        assert response.status_code == 200
        envelope = response.json()
        assert envelope["success"] is True, envelope
        result = envelope["result"]
        assert result["days"] == 2
        assert len(result["momentum"]) == 2
        assert {
            "active",
            "pipeline",
            "backlog",
            "blocked",
            "frozen",
            "done",
        } <= set(result["state_counts"])

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
        for field in (
            "id", "flow", "target_tier", "target_environment_id",
            "status", "current_stage",
        ):
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

    def test_sessions_list_is_admitted_and_returns_derived_rows(
        self,
        ui_client,
        test_db,
    ):
        # The Sessions view scopes through the payload (a project id from
        # the roster) and relies on the proxy's global-target default.
        from yoke_core.domain.db_helpers import iso8601_now

        now = iso8601_now()
        test_db.execute(
            "INSERT INTO harness_sessions ("
            "session_id, executor, provider, model, workspace, project_id, "
            "mode, offered_at, last_heartbeat"
            ") VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (
                "s-ui",
                "claude-code",
                "anthropic",
                "test-model",
                "/tmp/workspace",
                1,
                "wait",
                now,
                now,
            ),
        )
        test_db.commit()
        response = self._call(
            ui_client,
            {"function": "sessions.list", "payload": {"project": "1"}},
        )
        assert response.status_code == 200
        envelope = response.json()
        assert envelope["success"] is True
        rows = envelope["result"]["rows"]
        assert [row["session_id"] for row in rows] == ["s-ui"]
        # Liveness arrives derived — the TTL numbers live in the engine,
        # never in the browser.
        assert rows[0]["liveness"] == "active"
        assert rows[0]["claims"] == []
        for field in (
            "session_id",
            "liveness",
            "execution_lane",
            "mode",
            "actor_label",
            "claims",
        ):
            assert field in envelope["result"]["fields"]

    def test_workflows_definition_is_admitted_and_serves_the_definition(
        self,
        ui_client,
        test_db,
    ):
        # The Workflows view scopes through the payload (a project id from
        # the roster) and relies on the proxy's global-target default.
        response = self._call(
            ui_client,
            {"function": "workflows.definition.get", "payload": {}},
        )
        assert response.status_code == 200
        envelope = response.json()
        assert envelope["success"] is True
        result = envelope["result"]
        assert result["family"] == "work-items"
        by_id = {row["id"]: row for row in result["workflows"]}
        assert set(by_id) == {"issue", "epic", "blitz", "dash"}
        assert len(by_id["issue"]["definition"]["stages"]) == 10
        assert len(by_id["epic"]["definition"]["stages"]) == 14
        assert all(
            gate["id"] and gate["name"] and gate["description"]
            for gate in result["gate_catalog"]
        )
        assert result["flows"] == []

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
        # The activation-latch entries carry one documented side effect and
        # are pinned in test_universe_ui_server_mutations instead.
        from yoke_core.domain.handlers.__init_register__ import register_all_handlers
        from yoke_core.domain.yoke_function_actor_identity import is_read_only
        from yoke_core.domain.yoke_function_registry import lookup

        register_all_handlers()
        latch = ui_server.UI_ACTIVATION_LATCH_FUNCTIONS
        for function_id in ui_server.UI_READ_FUNCTION_ALLOWLIST - latch:
            entry = lookup(function_id)
            assert entry is not None, function_id
            assert is_read_only(entry), function_id
