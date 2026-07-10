"""Tests for the epic-task GitHub backfill helpers.

Per-task sync helpers live in ``runtime/api/test_epic_task_sync.py``;
the high-level ``sync_epic_tasks`` orchestrator lives in
``runtime/api/test_epic_task_sync_orchestrator.py``.

These tests mock the typed REST surfaces (``github_rest.*`` and
``backlog_github_label_sync_rest.*``) directly. Yoke does NOT use the
``gh`` CLI; every GitHub interaction in production goes through the
typed REST stack.
"""

from __future__ import annotations

import io
from pathlib import Path
from unittest.mock import patch

import pytest

from yoke_contracts.github_app_installation_permissions import (
    GITHUB_ISSUES_WRITE_PERMISSION_LEVELS,
)
from runtime.api.conftest import insert_epic_task, insert_item
from yoke_core.domain import epic_task_sync, github_rest
from yoke_core.domain.project_github_auth import ProjectGithubAuth
from runtime.api.fixtures.file_test_db import (
    apply_fixture_schema_ddl,
    connect_test_db,
    init_test_db,
)


_LABEL_REST = "yoke_core.domain.backlog_github_label_sync_rest"


def _issue(number: int, *, title: str = "t", state: str = "OPEN") -> github_rest.Issue:
    return github_rest.Issue(number=number, title=title, state=state)


@pytest.fixture
def db(tmp_path):
    with init_test_db(tmp_path, apply_schema=apply_fixture_schema_ddl) as db_path:
        conn = connect_test_db(db_path)
        conn.execute(
            """
            INSERT INTO projects
                (id, slug, name, github_repo, public_item_prefix, created_at)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (id) DO UPDATE SET
                slug = EXCLUDED.slug,
                name = EXCLUDED.name,
                github_repo = EXCLUDED.github_repo,
                public_item_prefix = EXCLUDED.public_item_prefix
            """,
            (2, "buzz", "Buzz", "org/buzz", "YOK", "2026-01-01T00:00:00Z"),
        )
        conn.commit()
        try:
            yield conn
        finally:
            conn.close()


@pytest.fixture(autouse=True)
def _mock_yoke_root():
    with patch("yoke_core.domain.epic_task_sync._yoke_root", return_value=Path("/tmp/fake-yoke")):
        yield


@pytest.fixture(autouse=True)
def _stub_project_github_auth():
    """Stub the canonical resolver so the typed REST surfaces resolve
    a known repo+token without DB I/O."""
    def _ok(project, **kwargs):
        return ProjectGithubAuth(
            project=project, repo="org/buzz", token="ghs_test",
        )

    with patch(
        "yoke_core.domain.epic_task_sync_github_backfill.resolve_project_github_auth",
        side_effect=_ok,
    ) as resolver:
        yield resolver


class TestBackfillTaskTitles:
    def test_backfill_titles_updates_open_issues(self, db):
        insert_item(db, id=1246, type="epic", status="implementing", project="buzz")
        insert_epic_task(
            db, epic_id=1246, task_num=1, title="Implement feature",
            status="implementing", github_issue="#201",
        )
        insert_epic_task(
            db, epic_id=1246, task_num=2, title="Write tests",
            status="planning", github_issue="#202",
        )
        stdout = io.StringIO()

        def fake_get_issue(*, project, number, **_):
            if number == 201:
                return _issue(201, title="[YOK-1246] Implement feature", state="OPEN")
            return _issue(202, title="[YOK-1246] Write tests", state="OPEN")

        with patch(
            "yoke_core.domain.github_rest.get_issue", side_effect=fake_get_issue,
        ), patch(
            "yoke_core.domain.github_rest.update_issue",
        ) as update_issue:
            rc = epic_task_sync.backfill_task_titles(
                "YOK-1246", conn=db, stdout=stdout,
            )

        assert rc == 0
        assert "Updated: #201 — [YOK-1246] 001 Implement feature" in stdout.getvalue()
        assert "Updated: #202 — [YOK-1246] 002 Write tests" in stdout.getvalue()
        titles = [call.kwargs["title"] for call in update_issue.call_args_list]
        assert "[YOK-1246] 001 Implement feature" in titles
        assert "[YOK-1246] 002 Write tests" in titles

    def test_backfill_titles_is_idempotent_and_skips_closed(self, db):
        insert_item(db, id=1246, type="epic", status="implementing", project="buzz")
        insert_epic_task(
            db, epic_id=1246, task_num=1, title="Already correct",
            status="implementing", github_issue="#301",
        )
        insert_epic_task(
            db, epic_id=1246, task_num=2, title="Closed task",
            status="done", github_issue="#302",
        )
        stdout = io.StringIO()

        def fake_get_issue(*, project, number, **_):
            if number == 301:
                return _issue(301, title="[YOK-1246] 001 Already correct", state="OPEN")
            return _issue(302, title="[YOK-1246] 002 Closed task", state="CLOSED")

        with patch(
            "yoke_core.domain.github_rest.get_issue", side_effect=fake_get_issue,
        ), patch(
            "yoke_core.domain.github_rest.update_issue",
        ) as update_issue:
            rc = epic_task_sync.backfill_task_titles(
                "YOK-1246", conn=db, stdout=stdout,
            )

        assert rc == 0
        assert "Already correct: #301 — [YOK-1246] 001 Already correct" in stdout.getvalue()
        assert "Skipping closed issue #302 (task 002)" in stdout.getvalue()
        update_issue.assert_not_called()

    def test_backfill_titles_without_conn_uses_backend_connect(self, db):
        insert_item(db, id=1246, type="epic", status="implementing", project="buzz")
        insert_epic_task(
            db,
            epic_id=1246,
            task_num=1,
            title="Implement feature",
            status="implementing",
            github_issue="#201",
        )
        stdout = io.StringIO()

        with patch(
            "yoke_core.domain.epic_task_sync_github_backfill._connect_db",
            return_value=db,
        ) as open_conn, patch(
            "yoke_core.domain.epic_task_sync._db_path",
            side_effect=AssertionError("path resolver must not be used for sync"),
        ), patch(
            "yoke_core.domain.github_rest.get_issue",
            return_value=_issue(201, title="[YOK-1246] Implement feature", state="OPEN"),
        ), patch(
            "yoke_core.domain.github_rest.update_issue",
        ) as update_issue:
            rc = epic_task_sync.backfill_task_titles("YOK-1246", stdout=stdout)

        assert rc == 0
        open_conn.assert_called_once_with()
        update_issue.assert_called_once()
        assert "Updated: #201 — [YOK-1246] 001 Implement feature" in stdout.getvalue()


class TestBackfillTaskLabels:
    def test_backfill_labels_uses_db_status_and_worktree_label(
        self, db, _stub_project_github_auth,
    ):
        insert_item(db, id=1246, type="epic", status="implementing", project="buzz")
        insert_epic_task(
            db, epic_id=1246, task_num=1, title="Task 1",
            status="reviewed-implementation",
            worktree="feature/test-epic",
            github_issue="#401",
        )
        db.execute(
            "UPDATE projects SET github_repo=%s WHERE slug=%s",
            ("stale-owner/stale-repo", "buzz"),
        )
        db.commit()
        stdout = io.StringIO()

        with patch(
            f"{_LABEL_REST}.fetch_issue_state", return_value="OPEN",
        ), patch(
            f"{_LABEL_REST}.fetch_issue_labels",
            return_value=["status:planning"],
        ), patch(f"{_LABEL_REST}.ensure_label") as ensure_label, patch(
            f"{_LABEL_REST}.add_labels",
        ) as add_labels, patch(
            f"{_LABEL_REST}.remove_label",
        ) as remove_label:
            rc = epic_task_sync.backfill_task_labels(
                "YOK-1246", conn=db, stdout=stdout,
            )

        assert rc == 0
        output = stdout.getvalue()
        assert "Removed stale status:planning from #401 (task 001)" in output
        assert "Added status:reviewed-implementation to #401 (task 001)" in output
        assert "Added worktree:feature-test-epic to #401 (task 001)" in output

        added_flat = [
            label for call in add_labels.call_args_list for label in call.args[2]
        ]
        assert "type:task" in added_flat
        assert "status:reviewed-implementation" in added_flat
        assert "worktree:feature-test-epic" in added_flat
        assert (
            _stub_project_github_auth.call_args.kwargs["required_permissions"]
            is GITHUB_ISSUES_WRITE_PERMISSION_LEVELS
        )
        removed_labels = {call.args[2] for call in remove_label.call_args_list}
        assert "status:planning" in removed_labels
        assert {call.args[2] for call in ensure_label.call_args_list} == {"org/buzz"}


class TestResolveDeps:
    def test_empty_string(self):
        assert epic_task_sync._resolve_deps("") == []

    def test_none_string(self):
        assert epic_task_sync._resolve_deps("None") == []

    def test_single_dep(self):
        assert epic_task_sync._resolve_deps("1") == ["001"]

    def test_multiple_deps(self):
        assert epic_task_sync._resolve_deps("001, 002, 003") == ["001", "002", "003"]

    def test_strips_non_digits(self):
        assert epic_task_sync._resolve_deps("task-1, task-2") == ["001", "002"]
