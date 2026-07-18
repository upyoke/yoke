"""Tests for service_client item-query commands."""

from __future__ import annotations

import json

import pytest

from runtime.api.fixtures.file_test_db import (
    apply_inline_ddl,
    connect_test_db,
    init_test_db,
)
from runtime.api.test_service_client import _run_client

_ITEMS_DDL = """
CREATE TABLE projects (
    id INTEGER PRIMARY KEY, slug TEXT NOT NULL UNIQUE, name TEXT NOT NULL,
    public_item_prefix TEXT NOT NULL DEFAULT 'YOK'
);
CREATE TABLE items (
    id INTEGER PRIMARY KEY, title TEXT NOT NULL, type TEXT NOT NULL DEFAULT 'issue',
    status TEXT NOT NULL DEFAULT 'idea', priority TEXT NOT NULL DEFAULT 'medium',
    flow TEXT DEFAULT 'accelerated', rework_count INTEGER DEFAULT 0,
    frozen INTEGER DEFAULT 0, blocked INTEGER DEFAULT 0, blocked_reason TEXT,
    github_issue TEXT, deployed_to TEXT, worktree TEXT, merged_at TEXT,
    created_at TEXT NOT NULL, updated_at TEXT NOT NULL, source TEXT NOT NULL DEFAULT '2',
    project_id INTEGER NOT NULL REFERENCES projects(id),
    project_sequence INTEGER NOT NULL,
    deployment_flow TEXT, deploy_stage TEXT,
    UNIQUE(project_id, project_sequence)
);
CREATE TABLE deployment_flows (
    id TEXT PRIMARY KEY, project_id INTEGER NOT NULL REFERENCES projects(id), name TEXT NOT NULL, description TEXT,
    stages TEXT NOT NULL, on_failure TEXT DEFAULT 'halt', created_at TEXT NOT NULL,
    target_env TEXT DEFAULT NULL, done_description TEXT DEFAULT NULL,
    UNIQUE(project_id, name)
);
"""

_SEED_ITEMS = [
    (1, "Active item", "implementing", "high", 1, 1, 0),
    (2, "Done item", "done", "medium", 1, 2, 0),
    (3, "Cancelled item", "cancelled", "low", 1, 3, 0),
    (4, "Frozen item", "idea", "medium", 1, 4, 1),
    (5, "ExternalWebapp active", "implementing", "medium", 2, 1, 0),
]


def _seed_items_and_flow() -> None:
    """``apply_schema`` strategy: minimal schema + fixture rows."""
    from yoke_core.domain import db_backend

    apply_inline_ddl(_ITEMS_DDL)
    conn = db_backend.connect()
    try:
        stages_json = json.dumps([
            {"name": "merged", "executor": "auto"},
            {"name": "approve-deploy", "executor": "human-approval"},
            {"name": "prod-deploy", "executor": "github-actions-workflow"},
            {"name": "complete", "executor": "auto"},
        ])
        conn.execute(
            "INSERT INTO projects (id, slug, name, public_item_prefix) "
            "VALUES (1, 'yoke', 'Yoke', 'YOK'), (2, 'externalwebapp', 'ExternalWebapp', 'EXT')"
        )
        conn.execute(
            """INSERT INTO deployment_flows (id, project_id, name, stages, created_at)
               VALUES ('test-flow', 1, 'TestFlow', %s, %s)""",
            (stages_json, "2026-04-20T00:00:00Z"),
        )
        for item_id, title, status, priority, project_id, project_sequence, frozen in _SEED_ITEMS:
            conn.execute(
                """INSERT INTO items (id, title, type, status, priority, project_id,
                                      project_sequence,
                                      created_at, updated_at, source, frozen)
                   VALUES (%s, %s, 'issue', %s, %s, %s, %s, '2026-01-01', '2026-01-01', 'user', %s)""",
                (item_id, title, status, priority, project_id, project_sequence, frozen),
            )
        conn.commit()
    finally:
        conn.close()


@pytest.fixture()
def test_db(tmp_path):
    """Backend-aware fixture seeding the deployment flow + items."""
    with init_test_db(tmp_path, apply_schema=_seed_items_and_flow) as db_path:
        yield {"db_path": db_path}


class TestApproveCheck:
    """Regression tests for approve-check (AC-1: approval semantics via domain layer)."""

    def test_valid_approval_returns_next_stage(self, test_db):
        result = _run_client(["approve-check", "test-flow", "approve-deploy"], db_path=test_db["db_path"])
        assert result.returncode == 0
        data = json.loads(result.stdout.strip())
        assert data["approved"] is True
        assert data["next_stage"] == "prod-deploy"
        assert data["current_stage"] == "approve-deploy"
        assert data["flow_id"] == "test-flow"

    def test_non_approval_stage_rejected(self, test_db):
        result = _run_client(["approve-check", "test-flow", "merged"], db_path=test_db["db_path"])
        assert result.returncode == 1
        assert "not a human-approval stage" in result.stderr

    def test_unknown_stage_rejected(self, test_db):
        result = _run_client(["approve-check", "test-flow", "nonexistent-stage"], db_path=test_db["db_path"])
        assert result.returncode == 1
        assert "does not match any stage" in result.stderr

    def test_unknown_flow_rejected(self, test_db):
        result = _run_client(["approve-check", "nonexistent-flow", "approve-deploy"], db_path=test_db["db_path"])
        assert result.returncode == 1
        assert "not found" in result.stderr

    def test_usage_error_returns_2(self):
        result = _run_client(["approve-check"])
        assert result.returncode == 2

    def test_last_stage_approval_returns_complete(self, test_db):
        """Approving the last human-approval stage (if it were last) returns 'complete'."""
        conn = connect_test_db(test_db["db_path"])
        stages = json.dumps([
            {"name": "merged", "executor": "auto"},
            {"name": "approve-final", "executor": "human-approval"},
        ])
        conn.execute(
            """INSERT INTO deployment_flows (id, project_id, name, stages, created_at)
               VALUES ('final-flow', 1, 'FinalFlow', %s, '2026-04-20T00:00:00Z')""",
            (stages,),
        )
        conn.commit()
        conn.close()

        result = _run_client(["approve-check", "final-flow", "approve-final"], db_path=test_db["db_path"])
        assert result.returncode == 0
        data = json.loads(result.stdout.strip())
        assert data["approved"] is True
        assert data["next_stage"] == "complete"


class TestActiveQueue:
    """Regression tests for active-queue (AC-2: query path via domain layer)."""

    def test_excludes_done_cancelled_frozen(self, test_db):
        result = _run_client(["active-queue", "--fields", "id,title,status"], db_path=test_db["db_path"])
        assert result.returncode == 0
        lines = [l for l in result.stdout.strip().split("\n") if l]
        # Items 1 (active), 5 (active/externalwebapp) included; 2 (done), 3 (cancelled), 4 (frozen) excluded.
        ids = [line.split("|")[0] for line in lines]
        assert "1" in ids, "Active item should be in queue"
        assert "5" in ids, "ExternalWebapp active item should be in queue"
        assert "2" not in ids, "Done item should be excluded"
        assert "3" not in ids, "Cancelled item should be excluded"
        assert "4" not in ids, "Frozen item should be excluded"

    def test_project_filter(self, test_db):
        result = _run_client(["active-queue", "--project", "externalwebapp", "--fields", "id,title"], db_path=test_db["db_path"])
        assert result.returncode == 0
        lines = [l for l in result.stdout.strip().split("\n") if l]
        assert len(lines) == 1
        assert "ExternalWebapp active" in lines[0]

    def test_empty_queue(self, test_db):
        result = _run_client(["active-queue", "--project", "nonexistent", "--fields", "id"], db_path=test_db["db_path"])
        assert result.returncode == 0
        assert result.stdout.strip() == ""

    def test_default_fields(self, test_db):
        result = _run_client(["active-queue"], db_path=test_db["db_path"])
        assert result.returncode == 0
        lines = [l for l in result.stdout.strip().split("\n") if l]
        assert len(lines) > 0
        # Default fields: id,title,status,priority,type,project
        assert len(lines[0].split("|")) == 6


class TestValidateStatus:
    def test_valid_statuses(self):
        for status in ["idea", "refined-idea", "implementing", "reviewing-implementation",
                       "implemented", "release", "cancelled"]:
            result = _run_client(["validate-status", status])
            assert result.returncode == 0, f"{status} should be valid"
            assert result.stdout.strip() == "valid"

    def test_invalid_statuses(self):
        for status in ["qa", "merged", "in_release", "bogus", ""]:
            result = _run_client(["validate-status", status])
            assert result.returncode == 1, f"'{status}' should be invalid"


class TestValidateTransition:
    """Tests for validate-transition forward progression checks."""

    def test_forward_transitions(self):
        forward_pairs = [
            ("idea", "refining-idea"),
            ("refining-idea", "refined-idea"),
            # Issue-workflow-type transitions
            ("refined-idea", "implementing"),
            ("implementing", "reviewing-implementation"),
            ("reviewing-implementation", "reviewed-implementation"),
            ("reviewed-implementation", "polishing-implementation"),
            ("polishing-implementation", "implemented"),
            # Epic-workflow-type transitions
            ("refined-idea", "planning"),
            ("planning", "planned"),
            ("implemented", "release"),
            ("release", "done"),
        ]
        for from_s, to_s in forward_pairs:
            result = _run_client(["validate-transition", from_s, to_s])
            assert result.returncode == 0, f"{from_s}->{to_s} should be forward"

    def test_backward_transitions(self):
        backward_pairs = [
            ("done", "idea"),
            ("implementing", "refined-idea"),
            ("reviewed-implementation", "implementing"),
            ("planned", "idea"),
            ("release", "implementing"),
        ]
        for from_s, to_s in backward_pairs:
            result = _run_client(["validate-transition", from_s, to_s])
            assert result.returncode == 1, f"{from_s}->{to_s} should not be forward"

    def test_exceptional_status_not_in_progression(self):
        result = _run_client(["validate-transition", "implementing", "blocked"])
        assert result.returncode == 1, "blocked is exceptional, not in progression"

    def test_item_type_issue_forward(self):
        result = _run_client(["validate-transition", "refined-idea", "implementing", "--item-type", "issue"])
        assert result.returncode == 0, "refined-idea->implementing is forward for issues"

    def test_item_type_issue_rejects_epic_only_status(self):
        # planning is in the epic progression but not the issue progression
        result = _run_client(["validate-transition", "refined-idea", "planning", "--item-type", "issue"])
        assert result.returncode == 1, "planning is not in the issue progression"

    def test_item_type_epic_accepts_planning(self):
        result = _run_client(["validate-transition", "refined-idea", "planning", "--item-type", "epic"])
        assert result.returncode == 0, "refined-idea->planning is forward for epics"

    def test_item_type_omitted_preserves_default(self):
        # Without --item-type, should use epic/default progression (planning is valid)
        result = _run_client(["validate-transition", "refined-idea", "planning"])
        assert result.returncode == 0, "default (no flag) should accept planning"

    def test_item_type_flag_actually_forwarded(self):
        """Prove the CLI forwards item_type by using a case where issue and epic differ."""
        from unittest.mock import patch
        from yoke_core.domain import lifecycle
        from yoke_core.api import service_client

        calls = []
        original = lifecycle.is_forward_transition

        def spy(from_s, to_s, *, item_type=None):
            calls.append(item_type)
            return original(from_s, to_s, item_type=item_type)

        with patch.object(lifecycle, "is_forward_transition", side_effect=spy):
            service_client.cmd_validate_transition(["idea", "refining-idea", "--item-type", "issue"])
        assert calls == ["issue"], f"Expected item_type='issue' forwarded, got {calls}"

    def test_unknown_argument_returns_2(self):
        result = _run_client(["validate-transition", "idea", "refining-idea", "--bad-flag"])
        assert result.returncode == 2


class TestUsage:
    def test_help(self):
        result = _run_client(["help"])
        assert result.returncode == 0
        assert "approve-check" in result.stdout
        assert "active-queue" in result.stdout
        assert "create-item" in result.stdout
        assert "update-item" in result.stdout
        assert "apply-approval" in result.stdout

    def test_unknown_command(self):
        result = _run_client(["nonexistent"])
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
        "NULL AS target_env, NULL AS stage_progress, "
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
        result = _run_client(["item-progress", "1"], db_path=test_db["db_path"])
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
        result = _run_client(["item-progress", "1"], db_path=test_db["db_path"])
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() != ""
