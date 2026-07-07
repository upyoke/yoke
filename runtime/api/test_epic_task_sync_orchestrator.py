"""Tests for the high-level ``sync_epic_tasks`` orchestrator.

The per-task sync helpers live in ``runtime/api/test_epic_task_sync.py``;
backfill helpers and dependency-list parsing live in
``runtime/api/test_epic_task_sync_backfill.py``.

Tests mock the typed REST surfaces (``github_rest.*``) and the
canonical dedup helper directly. Yoke does NOT use the ``gh`` CLI.
"""

from __future__ import annotations

import io
from pathlib import Path
from unittest.mock import patch

import pytest

from runtime.api.conftest import insert_epic_task, insert_item
from yoke_core.domain import epic_task_sync, github_rest
from yoke_core.domain.project_github_auth import (
    MissingCapability,
    ProjectGithubAuth,
)
from runtime.api.fixtures.file_test_db import (
    apply_fixture_schema_ddl,
    connect_test_db,
    init_test_db,
)


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
    """Prevent subprocess.run leaking into worktree git resolution."""
    with patch("yoke_core.domain.epic_task_sync._yoke_root", return_value=Path("/tmp/fake-yoke")):
        yield


def _ok_auth(project: str, **kwargs):
    return ProjectGithubAuth(
        project=project,
        repo="org/buzz",
        token="ghp_test_token",
        env={"GH_TOKEN": "ghp_test_token"},
    )


@pytest.fixture(autouse=True)
def _stub_project_github_auth():
    """Default-stub the canonical resolver to succeed across the
    orchestrator + create helper + label-ensure paths."""
    with patch(
        "yoke_core.domain.epic_task_sync_github_orchestrator."
        "resolve_project_github_auth",
        side_effect=_ok_auth,
    ), patch(
        "yoke_core.domain.epic_task_sync.resolve_project_github_auth",
        side_effect=_ok_auth,
    ), patch(
        "yoke_core.domain.epic_task_sync_github.resolve_project_github_auth",
        side_effect=_ok_auth,
    ), patch(
        "yoke_core.domain.epic_task_sync_github_create.resolve_project_github_auth",
        side_effect=_ok_auth,
    ):
        yield


@pytest.fixture(autouse=True)
def _stub_typed_rest_surfaces():
    """Stub the typed REST surfaces the orchestrator + create helpers
    drive: label ensure, issue create, sub-issue link (which fails so
    the orchestrator falls back to the body-checkbox path), dedup
    search (always empty so a new issue is created)."""
    create_counter = [0]

    def fake_create_issue(*, project, title, body, labels, **_):
        create_counter[0] += 1
        if "type:epic" in labels:
            number = 100
        else:
            number = 100 + create_counter[0]
        return github_rest.Issue(
            number=number, title=title, state="OPEN",
            html_url=f"https://github.com/org/buzz/issues/{number}",
        )

    with patch(
        "yoke_core.domain.epic_task_sync_github_create.github_rest.create_issue",
        side_effect=fake_create_issue,
    ), patch(
        "yoke_core.domain.epic_task_sync_github._label_rest.ensure_label",
    ), patch(
        "yoke_core.domain.github_rest.add_sub_issue",
        side_effect=github_rest.RestTransportError("sub-issue not supported", status=404),
    ), patch(
        "yoke_core.domain.github_dedup.github_rest.list_issues",
        return_value=[],
    ), patch(
        "yoke_core.domain.epic_task_sync_github_orchestrator_body."
        "append_task_list_to_epic_body",
    ):
        yield


class TestSyncEpicTasks:
    def test_sync_creates_epic_and_task_issues(self, db):
        insert_item(db, id=10, type="epic", status="implementing", project="buzz", spec="Epic body here")
        insert_epic_task(db, epic_id="10", task_num=1, title="First task",
                         status="planned", body="Task 1 body")
        insert_epic_task(db, epic_id="10", task_num=2, title="Second task",
                         status="planned", body="Task 2 body")
        stdout = io.StringIO()
        stderr = io.StringIO()

        rc = epic_task_sync.sync_epic_tasks(
            "YOK-10", conn=db, stdout=stdout, stderr=stderr,
        )

        assert rc == 0
        output = stdout.getvalue()
        assert "Sync complete" in output
        assert "2 created" in output

        row1 = db.execute(
            "SELECT github_issue, branch FROM epic_tasks WHERE epic_id='10' AND task_num=1"
        ).fetchone()
        assert row1 is not None
        assert row1[0] is not None
        assert row1[0].startswith("#")
        assert row1[1] == "YOK-10"

        row2 = db.execute(
            "SELECT github_issue FROM epic_tasks WHERE epic_id='10' AND task_num=2"
        ).fetchone()
        assert row2 is not None
        assert row2[0] is not None

    def test_sync_without_conn_uses_backend_connect(self, db):
        insert_item(db, id=10, type="epic", status="implementing", project="buzz", spec="Epic body here")
        insert_epic_task(db, epic_id="10", task_num=1, title="First task",
                         status="planned", body="Task 1 body")
        stdout = io.StringIO()
        stderr = io.StringIO()

        with patch(
            "yoke_core.domain.epic_task_sync_github_orchestrator._connect_db",
            return_value=db,
        ) as open_conn, patch(
            "yoke_core.domain.epic_task_sync._db_path",
            side_effect=AssertionError("path resolver must not be used for sync"),
        ):
            rc = epic_task_sync.sync_epic_tasks(
                "YOK-10", stdout=stdout, stderr=stderr,
            )

        assert rc == 0
        open_conn.assert_called_once_with()
        assert "Sync complete" in stdout.getvalue()

    def test_sync_skips_already_synced_tasks(self, db):
        insert_item(db, id=10, type="epic", status="implementing", project="buzz", spec="Epic body")
        insert_epic_task(db, epic_id="10", task_num=1, title="Already synced",
                         status="implementing", github_issue="#50", worktree="custom-synced")
        insert_epic_task(db, epic_id="10", task_num=2, title="Not yet synced",
                         status="planned", body="Task 2 body")
        stdout = io.StringIO()

        rc = epic_task_sync.sync_epic_tasks("YOK-10", conn=db, stdout=stdout)

        assert rc == 0
        output = stdout.getvalue()
        assert "Skipping task 001 (already synced)" in output
        assert "1 created, 1 skipped" in output

        chains = db.execute(
            "SELECT worktree, queue FROM epic_dispatch_chains WHERE epic_id='10'"
        ).fetchall()
        assert {row[0]: row[1] for row in chains} == {
            "YOK-10": '["002"]',
            "custom-synced": '["001"]',
        }

    def test_sync_dry_run_skips_github(self, db):
        insert_item(db, id=10, type="epic", status="implementing", project="buzz")
        insert_epic_task(db, epic_id="10", task_num=1, title="Task one",
                         status="planned")
        stdout = io.StringIO()

        with patch("yoke_core.domain.epic_task_sync_github._is_dry_run", return_value=True):
            rc = epic_task_sync.sync_epic_tasks("YOK-10", conn=db, stdout=stdout)

        assert rc == 0
        output = stdout.getvalue()
        assert "[DRY-RUN]" in output

    def test_sync_fail_closed_on_missing_capability(self, db):
        """When the canonical resolver raises ProjectGithubAuthError the
        orchestrator prints the typed code + repair hint and returns 1
        WITHOUT issuing any REST calls."""
        insert_item(db, id=10, type="epic", status="implementing", project="buzz", spec="body")
        insert_epic_task(db, epic_id="10", task_num=1, title="Task", status="planned")
        stderr = io.StringIO()

        def _raise(project, **kwargs):
            raise MissingCapability(project, "no github capability for tests")

        with patch(
            "yoke_core.domain.epic_task_sync_github_orchestrator."
            "resolve_project_github_auth",
            side_effect=_raise,
        ), patch(
            "yoke_core.domain.epic_task_sync_github_create.github_rest.create_issue",
        ) as create_issue:
            rc = epic_task_sync.sync_epic_tasks("YOK-10", conn=db, stderr=stderr)

        assert rc == 1
        err_text = stderr.getvalue()
        assert "missing_capability" in err_text
        assert "Repair:" in err_text
        # Fail-closed: no REST calls after the resolver raises.
        create_issue.assert_not_called()
        row = db.execute(
            "SELECT github_issue FROM epic_tasks WHERE epic_id='10' AND task_num=1"
        ).fetchone()
        assert row[0] in (None, "")

    def test_sync_preserves_explicit_task_worktree(self, db):
        """Architect/refine worktree assignments are the dispatch source of truth."""
        insert_item(db, id=10, type="epic", status="implementing", project="buzz", spec="body")
        insert_epic_task(db, epic_id="10", task_num=1, title="Task",
                         status="planned", worktree="custom-branch")
        stdout = io.StringIO()

        rc = epic_task_sync.sync_epic_tasks("YOK-10", conn=db, stdout=stdout)

        assert rc == 0
        row = db.execute(
            "SELECT worktree, branch FROM epic_tasks WHERE epic_id='10' AND task_num=1"
        ).fetchone()
        assert row[0] == "custom-branch"
        assert row[1] == "custom-branch"

        chains = db.execute(
            "SELECT worktree, queue FROM epic_dispatch_chains WHERE epic_id='10'"
        ).fetchall()
        assert [(row[0], row[1]) for row in chains] == [("custom-branch", '["001"]')]

    def test_sync_defaults_empty_task_worktree_to_parent(self, db):
        """Legacy unslotted tasks still get the parent worktree fallback."""
        insert_item(db, id=10, type="epic", status="implementing", project="buzz", spec="body")
        insert_epic_task(db, epic_id="10", task_num=1, title="Task",
                         status="planned")
        stdout = io.StringIO()
        stderr = io.StringIO()

        rc = epic_task_sync.sync_epic_tasks(
            "YOK-10", conn=db, stdout=stdout, stderr=stderr,
        )

        assert rc == 0
        row = db.execute(
            "SELECT worktree, branch FROM epic_tasks WHERE epic_id='10' AND task_num=1"
        ).fetchone()
        assert row[0] == "YOK-10"
        assert row[1] == "YOK-10"
        assert "defaulting to YOK-10" in stderr.getvalue()

    def test_sync_reports_failure_when_task_create_returns_sentinel(self, db):
        """Failed task creates stay unstamped and make sync exit non-zero."""
        insert_item(db, id=10, type="epic", status="implementing",
                    project="buzz", spec="body")
        insert_epic_task(db, epic_id="10", task_num=1, title="ok-task",
                         status="planned", body="body-one")
        insert_epic_task(db, epic_id="10", task_num=2, title="bad-task",
                         status="planned", body="body-two")
        stdout = io.StringIO()
        stderr = io.StringIO()

        def fake_create_issue(*, project, title, body, labels, **_):
            if "type:epic" in labels:
                return github_rest.Issue(number=100, title=title, state="OPEN")
            if "ok-task" in title:
                return github_rest.Issue(number=101, title=title, state="OPEN")
            raise github_rest.RestTransportError(
                "422 Unprocessable: label too long", status=422,
            )

        with patch(
            "yoke_core.domain.epic_task_sync_github_create.github_rest.create_issue",
            side_effect=fake_create_issue,
        ):
            rc = epic_task_sync.sync_epic_tasks(
                "YOK-10", conn=db, stdout=stdout, stderr=stderr,
            )

        assert rc == 1
        output = stdout.getvalue()
        assert "1 created, 0 skipped, 1 failed" in output
        assert "tasks 002" in output

        ok_row = db.execute(
            "SELECT github_issue FROM epic_tasks WHERE epic_id='10' AND task_num=1"
        ).fetchone()
        bad_row = db.execute(
            "SELECT github_issue FROM epic_tasks WHERE epic_id='10' AND task_num=2"
        ).fetchone()
        assert ok_row[0] == "#101"
        # The sentinel #0 must NOT land in the DB — leave it NULL so the
        # next sync retries the create.
        assert bad_row[0] in (None, "")

    def test_main_sync_routing(self, capsys):
        """CLI 'sync' mode routes to sync_epic_tasks."""
        with patch("yoke_core.domain.epic_task_sync_github_core.sync_epic_tasks", return_value=0) as mock:
            rc = epic_task_sync.main(["sync", "YOK-10"])
        assert rc == 0
        mock.assert_called_once_with("YOK-10", "")

    def test_main_sync_usage(self, capsys):
        rc = epic_task_sync.main(["sync"])
        captured = capsys.readouterr()
        assert rc == 1
        assert epic_task_sync.SYNC_USAGE in captured.err
