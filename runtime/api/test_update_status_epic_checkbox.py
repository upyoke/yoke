"""Epic checkbox synchronization follows the pinned task-success handoff."""

from __future__ import annotations
import io
from unittest import mock
from runtime.api.conftest import insert_epic_task, insert_item
from runtime.api.update_status_github_test_support import _auth, _ok_response
from yoke_core.domain import update_status


class TestEpicCheckbox:
    def test_checkbox_on_terminal_success(self, test_db):
        insert_item(
            test_db, id=42, title="Epic", workflow_id="epic", github_issue="#100"
        )
        insert_epic_task(
            test_db,
            epic_id=42,
            task_num=1,
            status="reviewed-implementation",
            github_issue="#200",
        )
        out = io.StringIO()
        body_before = "- [ ] #200 Task one\n"

        def fake_req(req, *, token, **kwargs):
            if req.method == "GET":
                return _ok_response({"body": body_before, "number": 100})
            return _ok_response()

        with (
            mock.patch(
                "yoke_core.domain.update_status_epic_checkbox.resolve_project_github_auth",
                return_value=_auth(),
            ),
            mock.patch(
                "yoke_core.domain.update_status_epic_checkbox.request_with_retry",
                side_effect=fake_req,
            ),
        ):
            update_status._update_epic_checkbox(
                test_db,
                "42",
                "1",
                "reviewed-implementation",
                "#200",
                [],
                "yoke",
                stdout=out,
            )
        assert "Checked off" in out.getvalue()

    def test_no_checkbox_on_non_terminal(self, test_db):
        insert_item(
            test_db, id=42, title="Epic", workflow_id="epic", github_issue="#100"
        )
        insert_epic_task(
            test_db,
            epic_id=42,
            task_num=1,
            status="implementing",
            github_issue="#200",
        )
        out = io.StringIO()
        called = []

        def fake_req(req, *, token, **kwargs):
            called.append(req.method)
            return _ok_response()

        with (
            mock.patch(
                "yoke_core.domain.update_status_epic_checkbox.resolve_project_github_auth",
                return_value=_auth(),
            ),
            mock.patch(
                "yoke_core.domain.update_status_epic_checkbox.request_with_retry",
                side_effect=fake_req,
            ),
        ):
            update_status._update_epic_checkbox(
                test_db,
                "42",
                "1",
                "implementing",
                "#200",
                [],
                "yoke",
                stdout=out,
            )
        assert not called

    def test_checkbox_dry_run(self, test_db):
        insert_item(
            test_db, id=42, title="Epic", workflow_id="epic", github_issue="#100"
        )
        out = io.StringIO()
        called = []

        def fake_req(req, *, token, **kwargs):
            called.append(req.method)
            return _ok_response()

        with (
            mock.patch.object(
                update_status,
                "_is_dry_run",
                return_value=True,
            ),
            mock.patch(
                "yoke_core.domain.update_status_epic_checkbox.resolve_project_github_auth",
                return_value=_auth(),
            ),
            mock.patch(
                "yoke_core.domain.update_status_epic_checkbox.request_with_retry",
                side_effect=fake_req,
            ),
        ):
            update_status._update_epic_checkbox(
                test_db,
                "42",
                "1",
                "reviewed-implementation",
                "#200",
                [],
                "yoke",
                stdout=out,
            )
        assert "DRY-RUN" in out.getvalue()
        # Dry-run must not dispatch any REST call.
        assert not called

    def test_checkbox_rejects_mismatched_repo_projection(self, test_db):
        insert_item(
            test_db, id=42, title="Epic", workflow_id="epic", github_issue="#100"
        )
        err = io.StringIO()

        with (
            mock.patch(
                "yoke_core.domain.update_status_epic_checkbox.resolve_project_github_auth",
                return_value=_auth(repo="org/verified"),
            ),
            mock.patch(
                "yoke_core.domain.update_status_epic_checkbox.request_with_retry",
            ) as request,
        ):
            update_status._update_epic_checkbox(
                test_db,
                "42",
                "1",
                "reviewed-implementation",
                "#200",
                ["-R", "org/stale"],
                "yoke",
                stderr=err,
            )

        request.assert_not_called()
        assert "does not match the verified binding" in err.getvalue()
