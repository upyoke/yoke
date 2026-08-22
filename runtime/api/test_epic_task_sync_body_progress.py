"""Body and progress-note synchronization coverage for epic tasks."""

from __future__ import annotations

import io
from unittest.mock import patch

from runtime.api.conftest import insert_epic_task, insert_item
from runtime.api.test_epic_task_sync import (
    _seed_progress_note,
    _stub_project_github_auth as _stub_project_github_auth,
    db as db,
)
from yoke_contracts.github_app_installation_permissions import (
    GITHUB_ISSUES_READ_PERMISSION_LEVELS,
)
from yoke_core.domain import epic_task_sync, github_rest


class TestSyncTaskBody:
    def test_body_sync_routes_through_typed_rest(self, db, _stub_project_github_auth):
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
            body="Hello world",
            github_issue="#77",
        )
        stdout = io.StringIO()
        stderr = io.StringIO()
        existing_issue = github_rest.Issue(number=77, title="Task 1", state="OPEN")
        with (
            patch(
                "yoke_core.domain.github_rest.get_issue", return_value=existing_issue
            ) as get_issue,
            patch(
                "yoke_core.domain.github_rest.update_issue", return_value=existing_issue
            ) as update_issue,
        ):
            rc = epic_task_sync.sync_task_body(
                1246, 1, conn=db, stdout=stdout, stderr=stderr
            )
        assert rc == 0
        assert "Synced task body: 1246/1 -> #77" in stdout.getvalue()
        assert get_issue.call_args.kwargs == {"project": "externalwebapp", "number": 77}
        update_issue.assert_called_once()
        assert update_issue.call_args.kwargs["project"] == "externalwebapp"
        assert update_issue.call_args.kwargs["number"] == 77
        assert (
            _stub_project_github_auth.call_args.kwargs["required_permissions"]
            is GITHUB_ISSUES_READ_PERMISSION_LEVELS
        )
        assert stderr.getvalue() == ""

    def test_body_validation_failure_is_not_reported_as_repo_mismatch(self, db):
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
            body="Hello world",
            github_issue="#77",
        )
        stderr = io.StringIO()
        with patch(
            "yoke_core.domain.epic_task_sync_github._validate_issue_in_repo",
            autospec=True,
            return_value=False,
        ):
            rc = epic_task_sync.sync_task_body(1246, 1, conn=db, stderr=stderr)
        assert rc == 1
        assert "issue validation failed" in stderr.getvalue()
        assert "repo mismatch" not in stderr.getvalue()

    def test_body_usage_is_error(self, capsys):
        assert epic_task_sync.main(["body", "1246"]) == 2
        assert epic_task_sync.BODY_USAGE in capsys.readouterr().err


class TestSyncProgress:
    def test_progress_sync_routes_to_project_repo_and_marks_synced(
        self, db, _stub_project_github_auth
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
        _seed_progress_note(
            db, epic_id=1246, task_num=1, note_num=1, body="Progress update"
        )
        stdout = io.StringIO()
        with patch("yoke_core.domain.github_rest.post_comment") as post_comment:
            rc = epic_task_sync.sync_progress_notes(1246, conn=db, stdout=stdout)
        assert rc == 0
        assert post_comment.call_args.kwargs == {
            "project": "externalwebapp",
            "number": 77,
            "body": "Progress update",
        }
        synced = db.execute(
            "SELECT synced_to_github FROM epic_progress_notes WHERE epic_id='1246' AND task_num=1 AND note_num=1"
        ).fetchone()
        assert synced[0] == 1
        assert "Synced 1 new progress note(s) for epic '1246'" in stdout.getvalue()

    def test_progress_sync_without_conn_uses_backend_connect(
        self, db, _stub_project_github_auth
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
        _seed_progress_note(
            db, epic_id=1246, task_num=1, note_num=1, body="Progress update"
        )
        stdout = io.StringIO()
        with (
            patch(
                "yoke_core.domain.epic_task_sync_github_core._connect_db",
                return_value=db,
            ) as open_conn,
            patch(
                "yoke_core.domain.epic_task_sync._db_path",
                side_effect=AssertionError("path resolver must not be used for sync"),
            ),
            patch("yoke_core.domain.github_rest.post_comment") as post_comment,
        ):
            rc = epic_task_sync.sync_progress_notes(1246, stdout=stdout)
        assert rc == 0
        open_conn.assert_called_once_with()
        post_comment.assert_called_once()
        assert "Synced 1 new progress note(s) for epic '1246'" in stdout.getvalue()

    def test_progress_usage_is_error(self, capsys):
        assert epic_task_sync.main(["progress"]) == 1
        assert epic_task_sync.PROGRESS_USAGE in capsys.readouterr().err
