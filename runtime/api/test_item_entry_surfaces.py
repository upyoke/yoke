"""Coverage for typed workflow entry surfaces on item creation."""

from __future__ import annotations

import io
import os
from unittest import mock

import pytest

from runtime.api.api_items_test_helpers import (
    make_client_fixture,
    make_test_db_fixture,
)
from runtime.api.backlog_mutations_test_helpers import (
    _patch_externals,
    tmp_db,  # noqa: F401 - pytest fixture re-export
)
from yoke_core.domain import backlog, db_backend
from yoke_core.domain.item_entry_surface import (
    ITEM_ENTRY_SURFACE_ENV,
    MISSING_ENTRY_SURFACE_MESSAGE,
    enforce_item_entry_allowed,
    is_test_isolation,
    resolve_entry_surface,
)
from yoke_core.domain.workflow_runtime import builtin_workflow_runtime


@pytest.fixture()
def api_db():
    yield from make_test_db_fixture()


@pytest.fixture()
def client(api_db):
    yield from make_client_fixture()


class TestEntrySurfaceGate:
    def test_dry_run_allows_missing_surface(self, monkeypatch):
        monkeypatch.delenv(ITEM_ENTRY_SURFACE_ENV, raising=False)
        error = enforce_item_entry_allowed(
            workflow=builtin_workflow_runtime("issue"),
            dry_run=True,
        )
        assert error is None

    def test_allowed_explicit_surface(self, monkeypatch):
        monkeypatch.delenv(ITEM_ENTRY_SURFACE_ENV, raising=False)
        error = enforce_item_entry_allowed(
            workflow=builtin_workflow_runtime("issue"),
            entry_surface="harness_skill",
        )
        assert error is None

    def test_environment_surface_is_normalized(self, monkeypatch):
        monkeypatch.setenv(ITEM_ENTRY_SURFACE_ENV, " HARNESS_SKILL ")
        assert resolve_entry_surface() == "harness_skill"

    def test_workflow_rejects_disallowed_surface(self):
        error = enforce_item_entry_allowed(
            workflow=builtin_workflow_runtime("issue"),
            entry_surface="web_form",
        )
        assert error is not None
        assert "does not allow" in error

    def test_missing_surface_fails_closed(self, monkeypatch):
        monkeypatch.delenv(ITEM_ENTRY_SURFACE_ENV, raising=False)
        error = enforce_item_entry_allowed(
            workflow=builtin_workflow_runtime("issue"),
        )
        assert error == MISSING_ENTRY_SURFACE_MESSAGE

    def test_test_isolation_uses_active_postgres_authority(
        self, tmp_path, monkeypatch,
    ):
        token = str(tmp_path / "compatibility-token.db")
        monkeypatch.setenv(
            db_backend.PG_DSN_ENV,
            "host=/tmp/sock user=yoketest dbname=yoke_test_entry_surface",
        )
        assert is_test_isolation(token) is True
        monkeypatch.setenv(
            db_backend.PG_DSN_ENV,
            "host=/tmp/sock user=yoke dbname=yoke_prod",
        )
        assert is_test_isolation(token) is False
        assert is_test_isolation(None) is False


class TestExecuteCreateEntrySurface:
    def test_dry_run_works_without_surface(self, tmp_db, monkeypatch):
        monkeypatch.delenv(ITEM_ENTRY_SURFACE_ENV, raising=False)
        out = io.StringIO()
        with _patch_externals() as patched, mock.patch.dict(
            os.environ, {"YOKE_DB": tmp_db},
        ):
            result = backlog.execute_create(
                title="Dry run only",
                workflow="issue",
                dry_run=True,
                out=out,
            )
        assert result["success"] is True
        assert result.get("dry_run") is True
        patched["_rebuild_board"].assert_not_called()

    def test_explicit_surface_allows_create(self, tmp_db, monkeypatch):
        monkeypatch.delenv(ITEM_ENTRY_SURFACE_ENV, raising=False)
        with _patch_externals(), mock.patch.dict(
            os.environ, {"YOKE_DB": tmp_db},
        ):
            result = backlog.execute_create(
                title="Harness-created item",
                workflow="issue",
                entry_surface="harness_skill",
            )
        assert result["success"] is True

    def test_environment_surface_allows_create(self, tmp_db):
        with _patch_externals(), mock.patch.dict(
            os.environ,
            {
                "YOKE_DB": tmp_db,
                ITEM_ENTRY_SURFACE_ENV: "harness_skill",
            },
        ):
            result = backlog.execute_create(
                title="Environment-routed item",
                workflow="issue",
            )
        assert result["success"] is True

    def test_missing_surface_blocks_when_test_bypass_is_disabled(
        self, tmp_db, monkeypatch,
    ):
        monkeypatch.delenv(ITEM_ENTRY_SURFACE_ENV, raising=False)
        monkeypatch.setattr(
            "yoke_core.domain.item_entry_surface.is_test_isolation",
            lambda _db_path: False,
        )
        with _patch_externals(), mock.patch.dict(
            os.environ, {"YOKE_DB": tmp_db},
        ):
            result = backlog.execute_create(
                title="Unrouted item",
                workflow="issue",
            )
        assert result["success"] is False
        assert result["error"] == MISSING_ENTRY_SURFACE_MESSAGE


class TestCreateAdapters:
    def test_cli_forwards_workflow_and_surface(self, monkeypatch):
        from yoke_core.api import service_client_backlog_create as adapter
        from yoke_core.domain import backlog as backlog_module

        captured = {}

        def _record(**kwargs):
            captured.update(kwargs)
            return {"success": True, "item_id": 1}

        monkeypatch.setattr(backlog_module, "execute_create", _record)
        rc = adapter.cmd_execute_create_cli([
            "--entry-surface",
            "harness_skill",
            "Harness title",
            "issue",
        ])
        assert rc == 0
        assert captured["workflow"] == "issue"
        assert captured["entry_surface"] == "harness_skill"

    def test_cli_default_forwards_no_surface(self, monkeypatch):
        from yoke_core.api import service_client_backlog_create as adapter
        from yoke_core.domain import backlog as backlog_module

        captured = {}

        def _record(**kwargs):
            captured.update(kwargs)
            return {"success": True, "item_id": 1}

        monkeypatch.setattr(backlog_module, "execute_create", _record)
        assert adapter.cmd_execute_create_cli(["Default title"]) == 0
        assert captured["workflow"] is None
        assert captured["entry_surface"] is None

    def test_web_form_rejects_issue_workflow(self, client):
        response = client.post(
            "/v1/items",
            json={"title": "Web issue", "workflow": "issue"},
        )
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "ENTRY_SURFACE_DENIED"

    def test_web_form_allows_dash_workflow(self, client):
        response = client.post(
            "/v1/items",
            json={"title": "Web dash", "workflow": "dash"},
        )
        assert response.status_code == 201
        assert response.json()["workflow_id"] == "dash"
