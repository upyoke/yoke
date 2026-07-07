"""ExecuteUpdate sub-scenarios: priority, nonexistent items, shell-fallback fields, project migration.

Covers the non-status field write paths: simple priority updates, error
handling for unknown items / unknown fields, the shell-fallback writers
(``type``, ``deploy_stage``), and the project-field path that triggers a
GitHub issue migration before the DB write.
"""

from __future__ import annotations

import io
import os
from unittest import mock

from runtime.api.backlog_mutations_test_helpers import (
    _conn,
    _item_field,
    _patch_externals,
    _seed_item,
    tmp_db,  # noqa: F401 — re-exported fixture
)
from yoke_core.domain import backlog, db_backend


def _p(conn) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _set_project_repos(db_path: str) -> None:
    conn = _conn(db_path)
    p = _p(conn)
    try:
        for slug, repo in (
            ("yoke", "testowner/yoke-repo"),
            ("buzz", "testowner/buzz-repo"),
        ):
            conn.execute(
                f"UPDATE projects SET github_repo = {p} WHERE slug = {p}",
                (repo, slug),
            )
        conn.commit()
    finally:
        conn.close()


class TestExecuteUpdate:
    """ExecuteUpdate sub-scenarios: non-status fields and project migration."""

    def test_update_priority(self, tmp_db):
        _seed_item(tmp_db, id=10, priority="medium")
        out = io.StringIO()
        with _patch_externals() as patched, \
             mock.patch.dict(os.environ, {"YOKE_DB": tmp_db}):
            result = backlog.execute_update(
                item_id=10,
                field="priority",
                value="high",
                rebuild_board=False,
                out=out,
            )
        assert result["success"] is True
        assert _item_field(tmp_db, 10, "priority") == "high"
        patched["_rebuild_board"].assert_not_called()

    def test_update_nonexistent_item(self, tmp_db):
        out = io.StringIO()
        with _patch_externals(), \
             mock.patch.dict(os.environ, {"YOKE_DB": tmp_db}):
            result = backlog.execute_update(
                item_id=999,
                field="status",
                value="implementing",
                out=out,
            )
        assert result["success"] is False

    def test_shell_fallback_type(self, tmp_db):
        _seed_item(tmp_db, id=10, type="issue")
        out = io.StringIO()
        with _patch_externals(), \
             mock.patch.dict(os.environ, {"YOKE_DB": tmp_db}):
            result = backlog.execute_update(
                item_id=10,
                field="type",
                value="epic",
                out=out,
            )
        assert result["success"] is True
        assert _item_field(tmp_db, 10, "type") == "epic"

    def test_shell_fallback_deploy_stage(self, tmp_db):
        _seed_item(tmp_db, id=10)
        out = io.StringIO()
        with _patch_externals(), \
             mock.patch.dict(os.environ, {"YOKE_DB": tmp_db}):
            result = backlog.execute_update(
                item_id=10,
                field="deploy_stage",
                value="build",
                out=out,
            )
        assert result["success"] is True
        assert _item_field(tmp_db, 10, "deploy_stage") == "build"

    def test_unsupported_field_rejected(self, tmp_db):
        _seed_item(tmp_db, id=10)
        out = io.StringIO()
        with _patch_externals(), \
             mock.patch.dict(os.environ, {"YOKE_DB": tmp_db}):
            result = backlog.execute_update(
                item_id=10,
                field="nonexistent_field",
                value="whatever",
                out=out,
            )
        assert result["success"] is False

    def test_project_update_migrates_issue_before_write(self, tmp_db):
        _seed_item(tmp_db, id=10, project="yoke", github_issue="#42")
        _set_project_repos(tmp_db)

        out = io.StringIO()
        with _patch_externals(), \
             mock.patch.dict(os.environ, {"YOKE_DB": tmp_db}), \
             mock.patch("yoke_core.domain.backlog_github_sync.migrate_issue_to_repo", return_value=0) as migrate:
            result = backlog.execute_update(
                item_id=10,
                field="project",
                value="buzz",
                out=out,
            )

        assert result["success"] is True
        assert _item_field(tmp_db, 10, "project") == "buzz"
        migrate.assert_called_once_with(
            "10",
            "42",
            "testowner/yoke-repo",
            "testowner/buzz-repo",
            "buzz",
            conn=mock.ANY,
            stdout=out,
            stderr=out,
        )

    def test_project_update_aborts_when_issue_migration_fails(self, tmp_db):
        _seed_item(tmp_db, id=10, project="yoke", github_issue="#42")
        _set_project_repos(tmp_db)

        out = io.StringIO()
        with _patch_externals(), \
             mock.patch.dict(os.environ, {"YOKE_DB": tmp_db}), \
             mock.patch("yoke_core.domain.backlog_github_sync.migrate_issue_to_repo", return_value=1):
            result = backlog.execute_update(
                item_id=10,
                field="project",
                value="buzz",
                out=out,
            )

        assert result["success"] is False
        assert "Project field NOT updated" in result["error"]
        assert _item_field(tmp_db, 10, "project") == "yoke"
