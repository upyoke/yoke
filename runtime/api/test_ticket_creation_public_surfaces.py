"""Regression coverage for the idea-intake guard on public create surfaces.

`yoke_core.domain.ticket_intake_provenance.enforce_public_create_allowed`
gates every public persistent create surface and the validator
`create-item` so direct production calls outside sanctioned idea intake
fail with a recovery hint that names ``/yoke idea``. The same guard
allows dry-run flows, ``--idea-intake`` / ``provenance="idea"`` calls,
and helper-level test-isolated DB targets to flow through unchanged.

The tests below exercise the four outcomes against the public
surfaces (``execute_create``, ``backlog-cli add`` CLI shim,
``create-item`` validator, REST route) plus the helper's own unit behavior.
"""

from __future__ import annotations

import io
import os
from unittest import mock

import pytest

from runtime.api.backlog_mutations_test_helpers import (
    _patch_externals,
    tmp_db,  # noqa: F401 — re-exported fixture
)
from yoke_core.domain import backlog
from yoke_core.domain import db_backend
from yoke_core.domain.ticket_intake_provenance import (
    BYPASS_MESSAGE,
    IDEA_INTAKE_ENV,
    enforce_public_create_allowed,
    is_idea_intake,
    is_test_isolation,
)


# ---------------------------------------------------------------------------
# Helper unit behavior
# ---------------------------------------------------------------------------


class TestEnforcePublicCreateAllowed:
    def test_dry_run_bypasses(self, monkeypatch):
        monkeypatch.delenv(IDEA_INTAKE_ENV, raising=False)
        assert enforce_public_create_allowed(dry_run=True) is None

    def test_provenance_idea_bypasses(self, monkeypatch):
        monkeypatch.delenv(IDEA_INTAKE_ENV, raising=False)
        assert enforce_public_create_allowed(provenance="idea") is None
        assert enforce_public_create_allowed(provenance="IDEA") is None

    def test_env_var_bypasses(self, monkeypatch):
        monkeypatch.setenv(IDEA_INTAKE_ENV, "1")
        assert enforce_public_create_allowed() is None
        monkeypatch.setenv(IDEA_INTAKE_ENV, "true")
        assert enforce_public_create_allowed() is None

    def test_test_isolated_db_bypasses(self, tmp_path, monkeypatch):
        monkeypatch.delenv(IDEA_INTAKE_ENV, raising=False)
        monkeypatch.setenv(
            db_backend.PG_DSN_ENV,
            "host=/tmp/sock user=yoketest dbname=yoke_test_ticket_guard",
        )
        test_db = tmp_path / "isolated.db"
        assert enforce_public_create_allowed(db_path=str(test_db)) is None

    def test_non_test_postgres_authority_blocks_path_token(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.delenv(IDEA_INTAKE_ENV, raising=False)
        monkeypatch.setenv(
            db_backend.PG_DSN_ENV,
            "host=/tmp/sock user=yoke dbname=yoke_prod",
        )
        path_token = str(tmp_path / "legacy-token.db")
        assert is_test_isolation(path_token) is False
        assert (
            enforce_public_create_allowed(db_path=path_token)
            == BYPASS_MESSAGE
        )

    def test_unsanctioned_production_call_blocks(self, monkeypatch):
        monkeypatch.delenv(IDEA_INTAKE_ENV, raising=False)
        msg = enforce_public_create_allowed(
            provenance=None,
            dry_run=False,
            db_path=None,  # treated as canonical when no db hint
        )
        assert msg == BYPASS_MESSAGE
        # Recovery hint must name /yoke idea explicitly.
        assert "/yoke idea" in msg

    def test_unrecognized_provenance_blocks(self, monkeypatch):
        monkeypatch.delenv(IDEA_INTAKE_ENV, raising=False)
        assert enforce_public_create_allowed(provenance="ad-hoc") == BYPASS_MESSAGE

    def test_is_idea_intake_rejects_falsy_env(self, monkeypatch):
        monkeypatch.setenv(IDEA_INTAKE_ENV, "0")
        assert is_idea_intake() is False
        monkeypatch.setenv(IDEA_INTAKE_ENV, "")
        assert is_idea_intake() is False

    def test_is_test_isolation_falls_back_to_db_path(self, tmp_path):
        with mock.patch.dict(
            os.environ,
            {
                db_backend.PG_DSN_ENV: (
                    "host=/tmp/sock user=yoketest "
                    "dbname=yoke_test_ticket_guard"
                )
            },
        ):
            assert is_test_isolation(str(tmp_path / "x.db")) is True
        with mock.patch.dict(
            os.environ,
            {
                db_backend.PG_DSN_ENV: (
                    "host=/tmp/sock user=yoke dbname=yoke_prod"
                )
            },
        ):
            assert is_test_isolation(str(tmp_path / "x.db")) is False
        assert is_test_isolation(None) is False


# ---------------------------------------------------------------------------
# execute_create — the persistent create writer
# ---------------------------------------------------------------------------


class TestExecuteCreateGuard:
    def test_dry_run_works_without_provenance(self, tmp_db, monkeypatch):
        monkeypatch.delenv(IDEA_INTAKE_ENV, raising=False)
        out = io.StringIO()
        with _patch_externals() as patched, \
             mock.patch.dict(os.environ, {"YOKE_DB": tmp_db}):
            result = backlog.execute_create(
                title="Dry run only",
                item_type="issue",
                dry_run=True,
                out=out,
            )
        assert result["success"] is True
        assert result.get("dry_run") is True
        patched["_rebuild_board"].assert_not_called()

    def test_idea_provenance_allows(self, tmp_db, monkeypatch):
        monkeypatch.delenv(IDEA_INTAKE_ENV, raising=False)
        out = io.StringIO()
        with _patch_externals(), \
             mock.patch.dict(os.environ, {"YOKE_DB": tmp_db}):
            result = backlog.execute_create(
                title="Sanctioned intake",
                item_type="issue",
                provenance="idea",
                out=out,
            )
        assert result["success"] is True

    def test_env_var_allows(self, tmp_db, monkeypatch):
        monkeypatch.setenv(IDEA_INTAKE_ENV, "1")
        out = io.StringIO()
        with _patch_externals(), \
             mock.patch.dict(os.environ, {"YOKE_DB": tmp_db, IDEA_INTAKE_ENV: "1"}):
            result = backlog.execute_create(
                title="Env-flagged intake",
                item_type="issue",
                out=out,
            )
        assert result["success"] is True

    def test_direct_call_against_non_test_authority_blocks(
        self, tmp_path, monkeypatch
    ):
        """The guard rejects a non-idea-intake create on non-test authority.

        Patching ``_resolve_write_db_path`` to return a compatibility token
        proves the token itself is not authority: the gate blocks because the
        active Postgres DSN is not a disposable ``yoke_test_*`` target.
        """
        monkeypatch.delenv(IDEA_INTAKE_ENV, raising=False)
        monkeypatch.setenv(
            db_backend.PG_DSN_ENV,
            "host=/tmp/sock user=yoke dbname=yoke_prod",
        )
        path_token = str(tmp_path / "legacy-token.db")
        out = io.StringIO()
        with mock.patch(
            "yoke_core.domain.backlog_create_op._resolve_write_db_path",
            return_value=path_token,
        ), mock.patch(
            "yoke_core.domain.backlog_create_op._assert_write_db_ready",
            return_value=None,
        ):
            result = backlog.execute_create(
                title="Naive direct create",
                item_type="issue",
                out=out,
            )
        assert result["success"] is False
        assert "/yoke idea" in result["error"]


# ---------------------------------------------------------------------------
# CLI shim (backlog-cli add → cmd_execute_create_cli)
# ---------------------------------------------------------------------------


class TestExecuteCreateCli:
    def test_idea_intake_flag_forwards_provenance(self, monkeypatch):
        from yoke_core.domain import backlog as _backlog
        from yoke_core.api import service_client_backlog_create as scbc

        captured = {}

        def _record(**kwargs):
            captured.update(kwargs)
            return {"success": True, "item_id": 1}

        monkeypatch.setattr(_backlog, "execute_create", _record)
        rc = scbc.cmd_execute_create_cli(
            ["--idea-intake", "Sanctioned title", "issue"],
        )
        assert rc == 0
        assert captured["provenance"] == "idea"

    def test_default_forwards_none_provenance(self, monkeypatch):
        from yoke_core.domain import backlog as _backlog
        from yoke_core.api import service_client_backlog_create as scbc

        captured = {}

        def _record(**kwargs):
            captured.update(kwargs)
            return {"success": True, "item_id": 1}

        monkeypatch.setattr(_backlog, "execute_create", _record)
        rc = scbc.cmd_execute_create_cli(["Default title", "issue"])
        assert rc == 0
        assert captured.get("provenance") is None


# ---------------------------------------------------------------------------
# REST route
# ---------------------------------------------------------------------------


class TestItemsWriteRouteGuard:
    def test_direct_post_against_control_plane_db_blocks(self, tmp_path, monkeypatch):
        from fastapi.testclient import TestClient

        import yoke_core.api.main as main, yoke_core.api.app_factory as app_factory
        from yoke_core.api.http_auth import HttpAuthContext

        monkeypatch.delenv(IDEA_INTAKE_ENV, raising=False)
        monkeypatch.setenv(
            db_backend.PG_DSN_ENV,
            "host=/tmp/sock user=yoke dbname=yoke_prod",
        )
        path_token = str(tmp_path / "legacy-token.db")
        monkeypatch.setattr(main, "get_db_path", lambda: path_token)
        auth = HttpAuthContext(1, 1, "test-authenticated-route-guard")
        monkeypatch.setattr(app_factory, "authenticate_request", lambda _request: auth)

        resp = TestClient(main.app).post(
            chr(47) + "v1/items",
            json={"title": "Naive REST create", "type": "issue"},
        )

        assert resp.status_code == 403
        payload = resp.json()
        assert payload["error"]["code"] == "IDEA_INTAKE_REQUIRED"
        assert "yoke idea" in payload["error"]["message"]


# ---------------------------------------------------------------------------
# create-item validator
# ---------------------------------------------------------------------------


class TestCreateItemValidator:
    def test_unsanctioned_call_blocks(self, tmp_path, monkeypatch, capsys):
        """Validator refuses direct production calls."""
        from yoke_core.api import service_client_delivery_item_mutation as scd

        monkeypatch.setenv(
            db_backend.PG_DSN_ENV,
            "host=/tmp/sock user=yoke dbname=yoke_prod",
        )
        path_token = str(tmp_path / "legacy-token.db")
        monkeypatch.setattr(scd, "_get_db_path", lambda: path_token)
        monkeypatch.delenv(IDEA_INTAKE_ENV, raising=False)

        rc = scd.cmd_create_item(["--title", "Naive", "--type", "issue"])
        assert rc == 1
        out = capsys.readouterr().out
        assert "/yoke idea" in out
        assert "IDEA_INTAKE_REQUIRED" in out

    def test_idea_intake_flag_passes(self, tmp_path, monkeypatch, capsys):
        """Validator runs through to ``mutations.prepare_create`` when the
        ``--idea-intake`` flag is present.
        """
        from yoke_core.api import service_client_delivery_item_mutation as scd

        # Point _get_db_path at a tmp DB so the gate fails closed on the
        # provenance check, not the test-isolation bypass.
        test_db = str(tmp_path / "validator.db")
        monkeypatch.setattr(scd, "_get_db_path", lambda: test_db)
        # Stub the validator's downstream dependencies — the gate is what
        # we're exercising here, not the mutation layer.
        monkeypatch.setattr(
            scd,
            "_get_db_readonly",
            lambda: type("_Conn", (), {"close": lambda self: None})(),
        )

        class _Result:
            success = True
            field_writes = {"title": "X"}
            events = []
            error = None
            error_code = None

        monkeypatch.setattr(scd.mutations, "prepare_create", lambda **kw: _Result())
        monkeypatch.setattr(
            scd,
            "_mutation_result_to_dict",
            lambda r: {"success": True, "field_writes": r.field_writes},
        )
        from yoke_core.domain import deployment_flow_validator as dfv
        monkeypatch.setattr(
            dfv, "normalize_deployment_flow_value", lambda v: v,
        )
        monkeypatch.setattr(
            dfv,
            "validate_and_lookup_flow_project",
            lambda conn, flow, project: (None, None),
        )

        rc = scd.cmd_create_item(
            ["--title", "Sanctioned", "--type", "issue", "--idea-intake"],
        )
        out = capsys.readouterr().out
        assert rc == 0, out
        assert "IDEA_INTAKE_REQUIRED" not in out
