"""Backlog create/update validation against the deployment_flows registry."""

from __future__ import annotations

import io
import os
from unittest import mock

from runtime.api.backlog_mutations_test_helpers import (
    _conn,
    _item_field,
    _patch_externals,
    insert_item,
    tmp_db,  # noqa: F401 — re-exported fixture
)
from yoke_core.domain import backlog
from yoke_core.domain import db_backend
from yoke_core.domain.ticket_intake_provenance import IDEA_INTAKE_ENV
from runtime.api.fixtures.file_test_db import connect_test_db


def _p(conn) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _seed_flows(db_path: str) -> None:
    conn = connect_test_db(db_path)
    try:
        p = _p(conn)
        flow_sql = (
            "INSERT INTO deployment_flows (id, project_id, name, stages, created_at) "
            f"VALUES ({p}, {p}, {p}, '[]', '2026-05-07T00:00:00Z')"
        )
        for row in [
            ("yoke-internal", 1, "YokeInternal"),
            ("yoke-hosted-production", 1, "YokeHostedProduction"),
            ("externalwebapp-internal", 2, "ExternalWebappInternal"),
        ]:
            conn.execute(flow_sql, row)
        conn.commit()
    finally:
        conn.close()


class TestExecuteCreateDeploymentFlowValidation:
    def test_create_rejects_unregistered_flow(self, tmp_db):
        _seed_flows(tmp_db)
        out = io.StringIO()
        with _patch_externals(), mock.patch.dict(os.environ, {"YOKE_DB": tmp_db, IDEA_INTAKE_ENV: "1"}):
            result = backlog.execute_create(
                title="Bad flow",
                item_type="issue",
                project="yoke",
                deployment_flow="garbage",
                out=out,
            )
        assert result["success"] is False
        assert "garbage" in result["error"]
        assert "is not registered" in result["error"]
        assert "yoke-internal" in result["error"]

    def test_create_rejects_literal_none_string(self, tmp_db):
        _seed_flows(tmp_db)
        out = io.StringIO()
        with _patch_externals(), mock.patch.dict(os.environ, {"YOKE_DB": tmp_db, IDEA_INTAKE_ENV: "1"}):
            result = backlog.execute_create(
                title="Literal none",
                item_type="issue",
                project="yoke",
                deployment_flow="none",
                out=out,
            )
        assert result["success"] is False
        assert "'none'" in result["error"]

    def test_create_accepts_registered_flow(self, tmp_db):
        _seed_flows(tmp_db)
        out = io.StringIO()
        with _patch_externals(), mock.patch.dict(os.environ, {"YOKE_DB": tmp_db, IDEA_INTAKE_ENV: "1"}):
            result = backlog.execute_create(
                title="Good flow",
                item_type="issue",
                project="yoke",
                deployment_flow="yoke-internal",
                out=out,
            )
        assert result["success"] is True

    def test_create_empty_string_is_silent(self, tmp_db):
        """Empty deployment_flow is treated as unset; no rejection."""
        _seed_flows(tmp_db)
        out = io.StringIO()
        with _patch_externals(), mock.patch.dict(os.environ, {"YOKE_DB": tmp_db, IDEA_INTAKE_ENV: "1"}):
            result = backlog.execute_create(
                title="Empty flow",
                item_type="issue",
                project="yoke",
                deployment_flow="",
                out=out,
            )
        assert result["success"] is True

    def test_create_no_flow_arg_is_silent(self, tmp_db):
        """Omitting deployment_flow continues to work as before."""
        _seed_flows(tmp_db)
        out = io.StringIO()
        with _patch_externals(), mock.patch.dict(os.environ, {"YOKE_DB": tmp_db, IDEA_INTAKE_ENV: "1"}):
            result = backlog.execute_create(
                title="No flow arg",
                item_type="issue",
                project="yoke",
                out=out,
            )
        assert result["success"] is True

    def test_create_null_sentinel_is_normalized_to_unset(self, tmp_db):
        _seed_flows(tmp_db)
        out = io.StringIO()
        with _patch_externals(), mock.patch.dict(os.environ, {"YOKE_DB": tmp_db, IDEA_INTAKE_ENV: "1"}):
            result = backlog.execute_create(
                title="Null sentinel flow",
                item_type="issue",
                project="yoke",
                deployment_flow="null",
                out=out,
            )
        assert result["success"] is True
        assert _item_field(tmp_db, result["item_id"], "deployment_flow") is None


class TestExecuteUpdateDeploymentFlowValidation:
    def test_update_rejects_unregistered_flow(self, tmp_db):
        _seed_flows(tmp_db)
        with connect_test_db(tmp_db) as conn:
            insert_item(conn, id=42, deployment_flow=None)
        out = io.StringIO()
        with _patch_externals(), mock.patch.dict(os.environ, {"YOKE_DB": tmp_db}):
            result = backlog.execute_update(
                item_id=42,
                field="deployment_flow",
                value="garbage",
                out=out,
            )
        assert result["success"] is False
        assert result["error_code"] == "VALIDATION_ERROR"
        assert "garbage" in result["error"]
        assert "is not registered" in result["error"]

    def test_update_rejects_literal_none_string(self, tmp_db):
        _seed_flows(tmp_db)
        with connect_test_db(tmp_db) as conn:
            insert_item(conn, id=43, deployment_flow=None)
        out = io.StringIO()
        with _patch_externals(), mock.patch.dict(os.environ, {"YOKE_DB": tmp_db}):
            result = backlog.execute_update(
                item_id=43,
                field="deployment_flow",
                value="none",
                out=out,
            )
        assert result["success"] is False
        assert "'none'" in result["error"]

    def test_update_accepts_registered_flow(self, tmp_db):
        _seed_flows(tmp_db)
        with connect_test_db(tmp_db) as conn:
            insert_item(conn, id=44, project="yoke", deployment_flow=None)
        out = io.StringIO()
        with _patch_externals(), mock.patch.dict(os.environ, {"YOKE_DB": tmp_db}):
            result = backlog.execute_update(
                item_id=44,
                field="deployment_flow",
                value="yoke-internal",
                out=out,
            )
        assert result["success"] is True

    def test_update_null_sentinel_clears_flow(self, tmp_db):
        _seed_flows(tmp_db)
        conn = _conn(tmp_db)
        try:
            insert_item(conn, id=46, project="yoke", deployment_flow="yoke-internal")
        finally:
            conn.close()
        out = io.StringIO()
        with _patch_externals(), mock.patch.dict(os.environ, {"YOKE_DB": tmp_db}):
            result = backlog.execute_update(
                item_id=46,
                field="deployment_flow",
                value="null",
                out=out,
                no_github=True,
            )
        assert result["success"] is True
        assert _item_field(tmp_db, 46, "deployment_flow") is None

    def test_update_alternatives_filtered_by_item_project(self, tmp_db):
        """When the item has a project, alternatives in the error are filtered to that project."""
        _seed_flows(tmp_db)
        with connect_test_db(tmp_db) as conn:
            insert_item(conn, id=45, project="yoke", deployment_flow=None)
        out = io.StringIO()
        with _patch_externals(), mock.patch.dict(os.environ, {"YOKE_DB": tmp_db}):
            result = backlog.execute_update(
                item_id=45,
                field="deployment_flow",
                value="garbage",
                out=out,
            )
        assert result["success"] is False
        # Project-filtered alternatives only — externalwebapp-internal must not surface.
        assert "yoke-internal" in result["error"]
        assert "externalwebapp-internal" not in result["error"]
