"""Tests for the Python-owned epic task GitHub sync helpers.

Covers per-task helpers: ``sync_task_label``, ``sync_task_body``, and
``sync_progress_notes``. Backfill helpers, dependency-list parsing, and
the high-level ``sync_epic_tasks`` orchestrator live in
``runtime/api/test_epic_task_sync_backfill.py``.

These tests mock the typed REST surfaces (``github_rest.*`` and
``backlog_github_label_sync_rest.*``) directly. Yoke does NOT use the
``gh`` CLI; every GitHub interaction in production goes through the
typed REST stack.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from yoke_contracts.github_app_installation_permissions import (
    GITHUB_ISSUES_WRITE_PERMISSION_LEVELS,
)
from runtime.api.conftest import insert_epic_task, insert_item
from yoke_core.domain import epic_task_sync
from yoke_core.domain.project_github_auth import (
    ProjectGithubAuth,
)
from runtime.api.fixtures.file_test_db import (
    apply_fixture_schema_ddl,
    connect_test_db,
    init_test_db,
)


_LABEL_REST = "yoke_core.domain.backlog_github_label_sync_rest"


@pytest.fixture
def db(tmp_path):
    with init_test_db(tmp_path, apply_schema=apply_fixture_schema_ddl) as db_path:
        conn = connect_test_db(db_path)
        conn.execute(
            """
            INSERT INTO projects
                (id, slug, name, github_repo, public_item_prefix, github_sync_mode, created_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (id) DO UPDATE SET
                slug = EXCLUDED.slug,
                name = EXCLUDED.name,
                github_repo = EXCLUDED.github_repo,
                public_item_prefix = EXCLUDED.public_item_prefix,
                github_sync_mode = EXCLUDED.github_sync_mode
            """,
            (
                2,
                "externalwebapp",
                "ExternalWebapp",
                "org/externalwebapp",
                "YOK",
                "enabled",
                "2026-01-01T00:00:00Z",
            ),
        )
        conn.commit()
        try:
            yield conn
        finally:
            conn.close()


def _seed_progress_note(
    db, *, epic_id: int, task_num: int, note_num: int, body: str
) -> None:
    db.execute(
        """
        INSERT INTO epic_progress_notes
            (epic_id, task_num, note_num, body, synced_to_github, created_at)
        VALUES (%s, %s, %s, %s, %s, %s)
        """,
        (epic_id, task_num, note_num, body, 0, "2026-01-01T00:00:00Z"),
    )
    db.commit()


@pytest.fixture(autouse=True)
def _mock_yoke_root():
    """Prevent subprocess.run leaking into worktree git resolution."""
    with patch(
        "yoke_core.domain.epic_task_sync._yoke_root",
        return_value=Path("/tmp/fake-yoke"),
    ):
        yield


@pytest.fixture(autouse=True)
def _stub_project_github_auth():
    """Keep project-scoped GitHub calls on the test resolver."""

    def _ok(project, **kwargs):
        return ProjectGithubAuth(
            project=project,
            repo="org/externalwebapp",
            token="ghs_test",
        )

    with patch(
        "yoke_core.domain.epic_task_sync_github.resolve_project_github_auth",
        side_effect=_ok,
    ) as resolver:
        yield resolver


class TestSyncTaskLabel:
    def test_missing_issue_is_silent(self, db):
        """When the task has no github_issue, the label sync is a noop."""
        insert_item(
            db,
            id=1246,
            workflow_id="epic",
            status="implementing",
            project="externalwebapp",
        )
        insert_epic_task(
            db, epic_id=1246, task_num=1, title="Task 1", status="implementing"
        )

        with (
            patch(f"{_LABEL_REST}.ensure_label") as ensure,
            patch(
                f"{_LABEL_REST}.add_labels",
            ) as add,
            patch(
                f"{_LABEL_REST}.remove_label",
            ) as remove,
            patch(
                f"{_LABEL_REST}.fetch_issue_labels",
            ) as fetch,
        ):
            rc = epic_task_sync.sync_task_label("1246", 1, "implementing", conn=db)

        assert rc == 0
        ensure.assert_not_called()
        add.assert_not_called()
        remove.assert_not_called()
        fetch.assert_not_called()

    def test_label_sync_reconciles_status_labels(
        self,
        db,
        _stub_project_github_auth,
    ):
        insert_item(
            db,
            id=1246,
            workflow_id="epic",
            status="implementing",
            project="externalwebapp",
        )
        insert_epic_task(
            db,
            epic_id=1246,
            task_num=1,
            title="Task 1",
            status="implementing",
            github_issue="#77",
        )

        with (
            patch(
                f"{_LABEL_REST}.ensure_label",
            ) as ensure,
            patch(
                f"{_LABEL_REST}.fetch_issue_labels",
                return_value=["status:planning", "status:blocked"],
            ),
            patch(
                f"{_LABEL_REST}.add_labels",
            ) as add_labels,
            patch(
                f"{_LABEL_REST}.remove_label",
            ) as remove_label,
        ):
            rc = epic_task_sync.sync_task_label("1246", 1, "implementing", conn=db)

        assert rc == 0
        # ensure_label is called once with the new status label.
        ensure.assert_called_once()
        assert ensure.call_args.args[0] == "status:implementing"
        # Stale labels removed.
        removed_labels = {call.args[2] for call in remove_label.call_args_list}
        assert {"status:planning", "status:blocked"} <= removed_labels
        # New status label added.
        added_flat = [
            label for call in add_labels.call_args_list for label in call.args[2]
        ]
        assert "status:implementing" in added_flat
        assert (
            _stub_project_github_auth.call_args.kwargs["required_permissions"]
            is GITHUB_ISSUES_WRITE_PERMISSION_LEVELS
        )

    def test_label_sync_uses_verified_repo_over_stale_project_projection(self, db):
        insert_item(
            db,
            id=1247,
            workflow_id="epic",
            status="implementing",
            project="externalwebapp",
        )
        insert_epic_task(
            db,
            epic_id=1247,
            task_num=1,
            title="Task 1",
            status="implementing",
            github_issue="#78",
        )
        db.execute(
            "UPDATE projects SET github_repo=%s WHERE slug=%s",
            ("stale-owner/stale-repo", "externalwebapp"),
        )
        db.commit()

        with (
            patch(f"{_LABEL_REST}.ensure_label") as ensure,
            patch(
                f"{_LABEL_REST}.fetch_issue_labels",
                return_value=[],
            ),
            patch(f"{_LABEL_REST}.add_labels"),
            patch(
                f"{_LABEL_REST}.remove_label",
            ),
        ):
            rc = epic_task_sync.sync_task_label(
                "1247",
                1,
                "implementing",
                conn=db,
            )

        assert rc == 0
        assert ensure.call_args.args[2] == "org/externalwebapp"

    def test_label_usage_is_nonfatal(self, capsys):
        rc = epic_task_sync.main(["label", "1246", "1"])
        captured = capsys.readouterr()
        assert rc == 0
        assert epic_task_sync.LABEL_USAGE in captured.err
