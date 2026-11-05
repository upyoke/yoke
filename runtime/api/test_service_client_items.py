# ruff: noqa: F811
"""Tests for service_client item-query commands."""

from __future__ import annotations

from runtime.api.service_client_item_query_test_support import test_db  # noqa: F401


import json


from runtime.api.fixtures.file_test_db import connect_test_db
from runtime.api.test_service_client import _run_client as _run_subprocess
from runtime.api.service_client_in_process_test_support import run_client as _run_client


class TestApproveCheck:
    """Regression tests for approve-check (approval semantics via domain layer)."""

    def test_valid_approval_returns_next_stage(self, test_db):
        result = _run_subprocess(
            ["approve-check", "test-flow", "approve-deploy"], db_path=test_db["db_path"]
        )
        assert result.returncode == 0
        data = json.loads(result.stdout.strip())
        assert data["approved"] is True
        assert data["next_stage"] == "prod-deploy"
        assert data["current_stage"] == "approve-deploy"
        assert data["flow_id"] == "test-flow"

    def test_non_approval_stage_rejected(self, test_db):
        result = _run_subprocess(
            ["approve-check", "test-flow", "merged"], db_path=test_db["db_path"]
        )
        assert result.returncode == 1
        assert "not a human-approval stage" in result.stderr

    def test_unknown_stage_rejected(self, test_db):
        result = _run_client(
            ["approve-check", "test-flow", "nonexistent-stage"],
            db_path=test_db["db_path"],
        )
        assert result.returncode == 1
        assert "does not match any stage" in result.stderr

    def test_unknown_flow_rejected(self, test_db):
        result = _run_client(
            ["approve-check", "nonexistent-flow", "approve-deploy"],
            db_path=test_db["db_path"],
        )
        assert result.returncode == 1
        assert "not found" in result.stderr

    def test_usage_error_returns_2(self):
        result = _run_client(["approve-check"])
        assert result.returncode == 2

    def test_last_stage_approval_returns_complete(self, test_db):
        """Approving the last human-approval stage (if it were last) returns 'complete'."""
        conn = connect_test_db(test_db["db_path"])
        stages = json.dumps(
            [
                {"name": "merged", "step_runner": "auto"},
                {"name": "approve-final", "step_runner": "human-approval"},
            ]
        )
        conn.execute(
            """INSERT INTO deployment_flows (id, project_id, name, stages, created_at)
               VALUES ('final-flow', 1, 'FinalFlow', %s, '2026-04-20T00:00:00Z')""",
            (stages,),
        )
        conn.commit()
        conn.close()

        result = _run_client(
            ["approve-check", "final-flow", "approve-final"], db_path=test_db["db_path"]
        )
        assert result.returncode == 0
        data = json.loads(result.stdout.strip())
        assert data["approved"] is True
        assert data["next_stage"] == "complete"


class TestActiveQueue:
    """Regression tests for active-queue (query path via domain layer)."""

    def test_excludes_done_cancelled_frozen(self, test_db):
        result = _run_subprocess(
            ["active-queue", "--fields", "id,title,status"], db_path=test_db["db_path"]
        )
        assert result.returncode == 0
        lines = [line for line in result.stdout.strip().split("\n") if line]
        # Public refs for active rows are included; terminal/frozen refs are excluded.
        ids = [line.split("|")[0] for line in lines]
        assert "YOK-1" in ids, "Active item should be in queue"
        assert "EXT-1" in ids, "ExternalWebapp active item should be in queue"
        assert "YOK-2" not in ids, "Done item should be excluded"
        assert "YOK-3" not in ids, "Cancelled item should be excluded"
        assert "YOK-4" not in ids, "Frozen item should be excluded"

    def test_project_filter(self, test_db):
        result = _run_client(
            ["active-queue", "--project", "externalwebapp", "--fields", "id,title"],
            db_path=test_db["db_path"],
        )
        assert result.returncode == 0
        lines = [line for line in result.stdout.strip().split("\n") if line]
        assert len(lines) == 1
        assert "ExternalWebapp active" in lines[0]

    def test_empty_queue(self, test_db):
        result = _run_client(
            ["active-queue", "--project", "nonexistent", "--fields", "id"],
            db_path=test_db["db_path"],
        )
        assert result.returncode == 0
        assert result.stdout.strip() == ""

    def test_default_fields(self, test_db):
        result = _run_client(["active-queue"], db_path=test_db["db_path"])
        assert result.returncode == 0
        lines = [line for line in result.stdout.strip().split("\n") if line]
        assert len(lines) > 0
        # Default fields: id,title,status,priority,workflow_id,project
        assert len(lines[0].split("|")) == 6


class TestUsage:
    def test_help(self):
        result = _run_subprocess(["help"])
        assert result.returncode == 0
        assert "approve-check" in result.stdout
        assert "active-queue" in result.stdout
        assert "update-item" in result.stdout
        assert "apply-approval" in result.stdout

    def test_unknown_command(self):
        result = _run_subprocess(["nonexistent"])
        assert result.returncode == 2
        assert "Unknown command" in result.stderr


class TestItemProgressStaleView:
    """Regression for ``cmd_item_progress`` against a drifted ``item_progress_view``.

    Pre-rename installs created the view with a ``blocked_reason`` alias the
    reader no longer selects, so the CLI raised ``no such column:
    pipeline_blocked_reason``. The canonical writer
    ``create_or_replace_item_progress_view`` rebuilds the view from the
    fresh-schema definition; this test proves the read path recovers.
    """

    _STALE_VIEW_SQL = (
        "CREATE VIEW item_progress_view AS "
        "SELECT i.id AS item_id, i.status, "
        "NULL AS flow_name, NULL AS run_id, NULL AS current_stage, "
        "NULL AS target_environment, NULL AS stage_progress, "
        "NULL AS done_description, NULL AS qa_summary, "
        "NULL AS blocked_reason, NULL AS smoke_qa_status "
        "FROM items i"
    )

    def _install_stale_view(self, db_path: str) -> None:
        conn = connect_test_db(db_path)
        try:
            conn.execute("DROP VIEW IF EXISTS item_progress_view")
            conn.execute(self._STALE_VIEW_SQL)
            conn.commit()
        finally:
            conn.close()

    def test_item_progress_fails_against_stale_view(self, test_db):
        self._install_stale_view(test_db["db_path"])
        result = _run_subprocess(["item-progress", "YOK-1"], db_path=test_db["db_path"])
        assert result.returncode != 0
        assert "pipeline_blocked_reason" in result.stderr

    def test_item_progress_works_after_view_refresh(self, test_db):
        from yoke_core.domain.flow_init import create_or_replace_item_progress_view

        self._install_stale_view(test_db["db_path"])
        conn = connect_test_db(test_db["db_path"])
        try:
            create_or_replace_item_progress_view(conn)
        finally:
            conn.close()
        result = _run_subprocess(["item-progress", "YOK-1"], db_path=test_db["db_path"])
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() != ""
