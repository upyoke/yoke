"""GitHub-side and CLI tests for ``yoke_core.domain.update_status``.

Covers:
  - GitHub label sync (REST-mocked)
  - GitHub comment post (REST-mocked)
  - GitHub close-on-terminal (REST-mocked)
  - Epic checkbox sync (REST-mocked)
  - Cross-project repo resolution
  - CLI entry point shape

Status sync now dispatches GitHub side effects through the bearer-token
REST transport (``yoke_core.domain.gh_rest_transport.request_with_retry``);
the host ``gh`` shell-out path was retired alongside ``_run_gh``. New
tests patch ``request_with_retry`` on the consuming module (canonical
pattern shared with ``runtime/api/domain/test_update_status_no_gh.py``).

Core DB update, done guard, auto-unblock, and parent-epic auto-derive
tests live in ``runtime/api/test_update_status.py``.
"""

from __future__ import annotations

import io
from unittest import mock

from yoke_contracts.github_app_installation_permissions import (
    GITHUB_ISSUES_WRITE_PERMISSION_LEVELS,
)
from runtime.api.conftest import insert_epic_task, insert_item
from yoke_core.domain import update_status
from yoke_core.domain.gh_rest_transport import RestResponse
from yoke_core.domain.project_github_auth import ProjectGithubAuth


def _auth(project: str = "yoke", repo: str = "org/yoke") -> ProjectGithubAuth:
    return ProjectGithubAuth(
        project=project, repo=repo, token="t",
    )


def _ok_response(body=None) -> RestResponse:
    return RestResponse(
        status=200, headers={}, body=body if body is not None else {},
    )


# ---------------------------------------------------------------------------
# GitHub side effects (REST-mocked)
# ---------------------------------------------------------------------------


class TestGitHubLabelSync:
    def test_label_sync_dry_run(self, test_db):
        err = io.StringIO()
        with mock.patch.object(update_status, "_is_dry_run", return_value=True):
            update_status._github_label_sync("123", "implementing", [], "yoke", stderr=err)
        assert "DRY-RUN" in err.getvalue()

    def test_label_sync_dispatches_rest(self, test_db):
        err = io.StringIO()
        calls = []

        def fake_req(req, *, token, **kwargs):
            calls.append((req.method, req.path))
            if req.method == "GET":
                return _ok_response([{"name": "status:old"}])
            return _ok_response()

        with mock.patch(
            "yoke_core.domain.update_status_github_sync.resolve_project_github_auth",
            return_value=_auth(),
        ) as resolve_auth, mock.patch(
            "yoke_core.domain.update_status_github_sync.request_with_retry",
            side_effect=fake_req,
        ):
            update_status._github_label_sync(
                "123", "implementing", [], "yoke", stderr=err,
            )
        methods = [c[0] for c in calls]
        # Label sync reads existing labels (GET) and creates / mutates (POST).
        assert "GET" in methods
        assert "POST" in methods
        resolve_auth.assert_called_once_with(
            "yoke",
            required_permissions=GITHUB_ISSUES_WRITE_PERMISSION_LEVELS,
        )


class TestGitHubCommentPost:
    def test_comment_dry_run(self, test_db):
        err = io.StringIO()
        with mock.patch.object(update_status, "_is_dry_run", return_value=True):
            update_status._github_comment_post(
                "123", "planned", "implementing", "", [], "yoke", stderr=err,
            )
        assert "DRY-RUN" in err.getvalue()

    def test_comment_with_note(self, test_db):
        err = io.StringIO()
        calls = []

        def fake_req(req, *, token, **kwargs):
            calls.append((req.method, req.path, req.body))
            return _ok_response()

        with mock.patch(
            "yoke_core.domain.update_status_github_sync.resolve_project_github_auth",
            return_value=_auth(),
        ), mock.patch(
            "yoke_core.domain.update_status_github_sync.request_with_retry",
            side_effect=fake_req,
        ):
            update_status._github_comment_post(
                "123", "planned", "implementing", "test note", [], "yoke",
                stderr=err,
            )
        # Comment POST should fire on the /comments endpoint.
        assert any(
            c[0] == "POST" and c[1].endswith("/issues/123/comments")
            for c in calls
        )

    def test_legacy_repo_projection_cannot_override_verified_binding(self):
        err = io.StringIO()
        with mock.patch(
            "yoke_core.domain.update_status_github_sync.resolve_project_github_auth",
            return_value=_auth(repo="org/verified"),
        ), mock.patch(
            "yoke_core.domain.update_status_github_sync.request_with_retry",
        ) as request:
            update_status._github_comment_post(
                "123", "planned", "implementing", "",
                ["-R", "org/stale"], "yoke", stderr=err,
            )

        request.assert_not_called()
        assert "cannot resolve verified GitHub target" in err.getvalue()


class TestGitHubClose:
    def test_close_on_terminal_success(self, test_db):
        err = io.StringIO()
        calls = []

        def fake_req(req, *, token, **kwargs):
            calls.append((req.method, req.path, dict(req.body or {})))
            if req.method == "GET":
                return _ok_response({"state": "closed"})
            return _ok_response()

        with mock.patch(
            "yoke_core.domain.update_status_github_sync.resolve_project_github_auth",
            return_value=_auth(),
        ), mock.patch(
            "yoke_core.domain.update_status_github_sync.request_with_retry",
            side_effect=fake_req,
        ):
            update_status._github_close_on_terminal(
                "123", "reviewed-implementation", "42", "1", [], "yoke",
                stderr=err,
            )
        patches = [c for c in calls if c[0] == "PATCH"]
        assert patches
        assert patches[0][2].get("state") == "closed"

    def test_no_close_on_non_terminal(self, test_db):
        err = io.StringIO()
        called = []

        def fake_req(req, *, token, **kwargs):
            called.append(req.method)
            return _ok_response()

        with mock.patch(
            "yoke_core.domain.update_status_github_sync.resolve_project_github_auth",
            return_value=_auth(),
        ), mock.patch(
            "yoke_core.domain.update_status_github_sync.request_with_retry",
            side_effect=fake_req,
        ):
            update_status._github_close_on_terminal(
                "123", "implementing", "42", "1", [], "yoke", stderr=err,
            )
        assert not called


# ---------------------------------------------------------------------------
# Epic checkbox sync (REST-mocked)
# ---------------------------------------------------------------------------


class TestEpicCheckbox:
    def test_checkbox_on_terminal_success(self, test_db):
        insert_item(test_db, id=42, title="Epic", type="epic", github_issue="#100")
        insert_epic_task(
            test_db, epic_id=42, task_num=1,
            status="reviewed-implementation", github_issue="#200",
        )
        out = io.StringIO()
        body_before = "- [ ] #200 Task one\n"

        def fake_req(req, *, token, **kwargs):
            if req.method == "GET":
                return _ok_response({"body": body_before, "number": 100})
            return _ok_response()

        with mock.patch(
            "yoke_core.domain.update_status_epic_checkbox.resolve_project_github_auth",
            return_value=_auth(),
        ), mock.patch(
            "yoke_core.domain.update_status_epic_checkbox.request_with_retry",
            side_effect=fake_req,
        ):
            update_status._update_epic_checkbox(
                test_db, "42", "1", "reviewed-implementation", "#200",
                [], "yoke", stdout=out,
            )
        assert "Checked off" in out.getvalue()

    def test_no_checkbox_on_non_terminal(self, test_db):
        insert_item(test_db, id=42, title="Epic", type="epic", github_issue="#100")
        insert_epic_task(
            test_db, epic_id=42, task_num=1, status="implementing",
            github_issue="#200",
        )
        out = io.StringIO()
        called = []

        def fake_req(req, *, token, **kwargs):
            called.append(req.method)
            return _ok_response()

        with mock.patch(
            "yoke_core.domain.update_status_epic_checkbox.resolve_project_github_auth",
            return_value=_auth(),
        ), mock.patch(
            "yoke_core.domain.update_status_epic_checkbox.request_with_retry",
            side_effect=fake_req,
        ):
            update_status._update_epic_checkbox(
                test_db, "42", "1", "implementing", "#200", [], "yoke",
                stdout=out,
            )
        assert not called

    def test_checkbox_dry_run(self, test_db):
        insert_item(test_db, id=42, title="Epic", type="epic", github_issue="#100")
        out = io.StringIO()
        called = []

        def fake_req(req, *, token, **kwargs):
            called.append(req.method)
            return _ok_response()

        with mock.patch.object(
            update_status, "_is_dry_run", return_value=True,
        ), mock.patch(
            "yoke_core.domain.update_status_epic_checkbox.resolve_project_github_auth",
            return_value=_auth(),
        ), mock.patch(
            "yoke_core.domain.update_status_epic_checkbox.request_with_retry",
            side_effect=fake_req,
        ):
            update_status._update_epic_checkbox(
                test_db, "42", "1", "reviewed-implementation", "#200",
                [], "yoke", stdout=out,
            )
        assert "DRY-RUN" in out.getvalue()
        # Dry-run must not dispatch any REST call.
        assert not called

    def test_checkbox_rejects_mismatched_repo_projection(self, test_db):
        insert_item(test_db, id=42, title="Epic", type="epic", github_issue="#100")
        err = io.StringIO()

        with mock.patch(
            "yoke_core.domain.update_status_epic_checkbox.resolve_project_github_auth",
            return_value=_auth(repo="org/verified"),
        ), mock.patch(
            "yoke_core.domain.update_status_epic_checkbox.request_with_retry",
        ) as request:
            update_status._update_epic_checkbox(
                test_db, "42", "1", "reviewed-implementation", "#200",
                ["-R", "org/stale"], "yoke", stderr=err,
            )

        request.assert_not_called()
        assert "does not match the verified binding" in err.getvalue()


# ---------------------------------------------------------------------------
# Cross-project repo resolution
# ---------------------------------------------------------------------------


class TestRepoResolution:
    def test_resolve_project_from_epic(self, test_db):
        test_db.execute(
            "INSERT INTO projects "
            "(id, slug, name, github_repo, created_at) "
            "VALUES (2, 'buzz', 'Buzz', 'example-org/buzz', "
            "'2026-01-01T00:00:00Z') "
            "ON CONFLICT (id) DO UPDATE SET "
            "slug = excluded.slug, name = excluded.name, "
            "github_repo = excluded.github_repo"
        )
        test_db.commit()
        insert_item(test_db, id=42, title="Epic", type="epic", project="buzz")
        project, repo = update_status._resolve_repo_for_epic(test_db, "42")
        assert project == "buzz"
        assert repo == "example-org/buzz"

    def test_resolve_no_project(self, test_db):
        insert_item(test_db, id=42, title="Epic", type="epic", project="yoke")
        project, repo = update_status._resolve_repo_for_epic(test_db, "42")
        assert project == "yoke"


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


class TestCLI:
    def test_no_args_shows_usage(self):
        rc = update_status.main([])
        assert rc == 2

    def test_invalid_args_shows_usage(self):
        rc = update_status.main(["42"])
        assert rc == 2
