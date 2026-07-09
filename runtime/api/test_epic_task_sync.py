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

import io
from pathlib import Path
from unittest.mock import patch

import pytest

from runtime.api.conftest import insert_epic_task, insert_item
from yoke_core.domain import (
    backlog_github_body_writer,
    epic_task_sync,
    github_rest,
)
from yoke_core.domain.project_github_auth import (
    MissingToken,
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


def _seed_progress_note(db, *, epic_id: int, task_num: int, note_num: int, body: str) -> None:
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
    with patch("yoke_core.domain.epic_task_sync._yoke_root", return_value=Path("/tmp/fake-yoke")):
        yield


@pytest.fixture(autouse=True)
def _stub_project_github_auth():
    """Stub the canonical resolver consumed by ``epic_task_sync._resolve_pat``.

    Real-DB reads would leak into this test DB. Default-stub
    succeeds; individual tests override by re-patching.
    """
    def _ok(project, **kwargs):
        return ProjectGithubAuth(
            project=project, repo="org/buzz", token="ghs_test",
            env={"GH_TOKEN": "ghs_test"},
        )

    with patch(
        "yoke_core.domain.epic_task_sync.resolve_project_github_auth",
        side_effect=_ok,
    ), patch(
        "yoke_core.domain.epic_task_sync_github.resolve_project_github_auth",
        side_effect=_ok,
    ):
        yield


class TestSyncTaskLabel:
    def test_missing_issue_is_silent(self, db):
        """When the task has no github_issue, the label sync is a noop."""
        insert_item(db, id=1246, type="epic", status="implementing", project="buzz")
        insert_epic_task(db, epic_id=1246, task_num=1, title="Task 1", status="implementing")

        with patch(f"{_LABEL_REST}.ensure_label") as ensure, patch(
            f"{_LABEL_REST}.add_labels",
        ) as add, patch(
            f"{_LABEL_REST}.remove_label",
        ) as remove, patch(
            f"{_LABEL_REST}.fetch_issue_labels",
        ) as fetch:
            rc = epic_task_sync.sync_task_label("1246", 1, "implementing", conn=db)

        assert rc == 0
        ensure.assert_not_called()
        add.assert_not_called()
        remove.assert_not_called()
        fetch.assert_not_called()

    def test_label_sync_reconciles_status_labels(self, db):
        insert_item(db, id=1246, type="epic", status="implementing", project="buzz")
        insert_epic_task(
            db,
            epic_id=1246,
            task_num=1,
            title="Task 1",
            status="implementing",
            github_issue="#77",
        )

        with patch(
            f"{_LABEL_REST}.ensure_label",
        ) as ensure, patch(
            f"{_LABEL_REST}.fetch_issue_labels",
            return_value=["status:planning", "status:blocked"],
        ), patch(
            f"{_LABEL_REST}.add_labels",
        ) as add_labels, patch(
            f"{_LABEL_REST}.remove_label",
        ) as remove_label:
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

    def test_label_usage_is_nonfatal(self, capsys):
        rc = epic_task_sync.main(["label", "1246", "1"])
        captured = capsys.readouterr()
        assert rc == 0
        assert epic_task_sync.LABEL_USAGE in captured.err


class TestSyncTaskBody:
    def test_body_sync_routes_through_typed_rest(self, db):
        """A body sync against a project with a resolved GitHub App auth routes the
        validator (existence check) and the body-write step through the
        typed ``github_rest.*`` surface — no argv shim involved."""
        insert_item(db, id=1246, type="epic", status="implementing", project="buzz")
        insert_epic_task(
            db,
            epic_id=1246,
            task_num=1,
            title="Task 1",
            status="implementing",
            body="Hello world",
            github_issue="#77",
        )
        stdout = io.StringIO()
        stderr = io.StringIO()

        existing_issue = github_rest.Issue(number=77, title="Task 1", state="OPEN")
        with patch(
            "yoke_core.domain.github_rest.get_issue", return_value=existing_issue,
        ) as get_issue_mock, patch(
            "yoke_core.domain.github_rest.update_issue",
            return_value=existing_issue,
        ) as update_issue_mock:
            rc = epic_task_sync.sync_task_body(
                "1246", 1, conn=db, stdout=stdout, stderr=stderr,
            )

        assert rc == 0
        assert "Synced task body: 1246/1 -> #77" in stdout.getvalue()
        # Validator probed the typed surface with the resolved repo + issue number.
        assert get_issue_mock.call_count == 1
        assert get_issue_mock.call_args.kwargs == {"project": "buzz", "number": 77}
        # Body write also flows through the typed PATCH.
        update_issue_mock.assert_called_once()
        assert update_issue_mock.call_args.kwargs["project"] == "buzz"
        assert update_issue_mock.call_args.kwargs["number"] == 77
        assert stderr.getvalue() == ""

    def test_body_usage_is_error(self, capsys):
        rc = epic_task_sync.main(["body", "1246"])
        captured = capsys.readouterr()
        assert rc == 2
        assert epic_task_sync.BODY_USAGE in captured.err


class TestSyncProgress:
    def test_progress_sync_routes_to_project_repo_and_marks_synced(self, db):
        insert_item(db, id=1246, type="epic", status="implementing", project="buzz")
        insert_epic_task(
            db,
            epic_id=1246,
            task_num=1,
            title="Task 1",
            status="implementing",
            github_issue="#77",
        )
        _seed_progress_note(db, epic_id=1246, task_num=1, note_num=1, body="Progress update")
        stdout = io.StringIO()

        with patch(
            "yoke_core.domain.github_rest.post_comment",
        ) as post_comment:
            rc = epic_task_sync.sync_progress_notes(
                "YOK-1246", conn=db, stdout=stdout,
            )

        assert rc == 0
        post_comment.assert_called_once()
        assert post_comment.call_args.kwargs["project"] == "buzz"
        assert post_comment.call_args.kwargs["number"] == 77
        assert post_comment.call_args.kwargs["body"] == "Progress update"
        synced = db.execute(
            """
            SELECT synced_to_github FROM epic_progress_notes
            WHERE epic_id='1246' AND task_num=1 AND note_num=1
            """
        ).fetchone()
        assert synced[0] == 1
        assert "Synced 1 new progress note(s) for epic '1246'" in stdout.getvalue()

    def test_progress_sync_without_conn_uses_backend_connect(self, db):
        insert_item(db, id=1246, type="epic", status="implementing", project="buzz")
        insert_epic_task(
            db,
            epic_id=1246,
            task_num=1,
            title="Task 1",
            status="implementing",
            github_issue="#77",
        )
        _seed_progress_note(db, epic_id=1246, task_num=1, note_num=1, body="Progress update")
        stdout = io.StringIO()

        with patch(
            "yoke_core.domain.epic_task_sync_github_core._connect_db",
            return_value=db,
        ) as open_conn, patch(
            "yoke_core.domain.epic_task_sync._db_path",
            side_effect=AssertionError("path resolver must not be used for sync"),
        ), patch(
            "yoke_core.domain.github_rest.post_comment",
        ) as post_comment:
            rc = epic_task_sync.sync_progress_notes("YOK-1246", stdout=stdout)

        assert rc == 0
        open_conn.assert_called_once_with()
        post_comment.assert_called_once()
        assert "Synced 1 new progress note(s) for epic '1246'" in stdout.getvalue()

    def test_progress_usage_is_error(self, capsys):
        rc = epic_task_sync.main(["progress"])
        captured = capsys.readouterr()
        assert rc == 1
        assert epic_task_sync.PROGRESS_USAGE in captured.err
