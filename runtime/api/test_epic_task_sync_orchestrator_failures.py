"""Failure-path coverage for high-level epic-task synchronization."""

from __future__ import annotations

import io
from unittest.mock import patch

from yoke_contracts.github_app_installation_permissions import (
    GITHUB_ISSUES_WRITE_PERMISSION_LEVELS,
)
from runtime.api.conftest import insert_epic_task, insert_item
from runtime.api.epic_task_sync_orchestrator_test_support import (
    _mock_yoke_root as _mock_yoke_root,
    _stub_project_github_auth as _stub_project_github_auth,
    _stub_typed_rest_surfaces as _stub_typed_rest_surfaces,
    db as db,
)
from yoke_core.domain import epic_task_sync, github_rest
from yoke_core.domain.project_github_auth import MissingCapability


class TestSyncEpicTasks:
    def test_sync_fail_closed_on_missing_capability(self, db):
        """When the canonical resolver raises ProjectGithubAuthError the
        orchestrator prints the typed code + repair hint and returns 1
        WITHOUT issuing any REST calls."""
        insert_item(
            db,
            id=10,
            workflow_id="epic",
            status="implementing",
            project="externalwebapp",
            spec="body",
        )
        insert_epic_task(db, epic_id="10", task_num=1, title="Task", status="planned")
        stderr = io.StringIO()

        def _raise(project, **kwargs):
            assert (
                kwargs["required_permissions"] is GITHUB_ISSUES_WRITE_PERMISSION_LEVELS
            )
            raise MissingCapability(project, "no github capability for tests")

        with (
            patch(
                "yoke_core.domain.epic_task_sync_github_orchestrator."
                "resolve_project_github_auth",
                side_effect=_raise,
            ),
            patch(
                "yoke_core.domain.epic_task_sync_github_create.github_rest.create_issue",
            ) as create_issue,
        ):
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

    def test_sync_reports_failure_when_task_create_returns_sentinel(self, db):
        """Failed task creates stay unstamped and make sync exit non-zero."""
        insert_item(
            db,
            id=10,
            workflow_id="epic",
            status="implementing",
            project="externalwebapp",
            spec="body",
        )
        insert_epic_task(
            db,
            epic_id="10",
            task_num=1,
            title="ok-task",
            status="planned",
            body="body-one",
        )
        insert_epic_task(
            db,
            epic_id="10",
            task_num=2,
            title="bad-task",
            status="planned",
            body="body-two",
        )
        stdout = io.StringIO()
        stderr = io.StringIO()

        def fake_create_issue(*, project, title, body, labels, **_):
            if "workflow:epic" in labels:
                return github_rest.Issue(number=100, title=title, state="OPEN")
            if "ok-task" in title:
                return github_rest.Issue(number=101, title=title, state="OPEN")
            raise github_rest.RestTransportError(
                "422 Unprocessable: label too long",
                status=422,
            )

        with patch(
            "yoke_core.domain.epic_task_sync_github_create.github_rest.create_issue",
            side_effect=fake_create_issue,
        ):
            rc = epic_task_sync.sync_epic_tasks(
                "YOK-10",
                conn=db,
                stdout=stdout,
                stderr=stderr,
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
