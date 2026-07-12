"""Issue-lifecycle coverage: ``post_comment``, ``close_issue``, ``reopen_issue``.

Tests mock the typed ``github_rest`` and
``backlog_github_label_sync_rest`` surfaces directly.
"""

from __future__ import annotations

import io
from unittest.mock import patch

from runtime.api.backlog_github_sync_test_helpers import (
    GH_PATCH,
    make_db as _make_db,
)
from runtime.api.conftest import insert_item
from yoke_core.domain import (
    backlog_github_comments,
    backlog_github_state_sync,
    backlog_github_sync,
    github_rest,
)
from yoke_core.domain.project_github_auth import ProjectGithubAuth


def _ok_auth(project: str = "buzz") -> ProjectGithubAuth:
    return ProjectGithubAuth(
        project=project, repo=f"org/{project}", token="ghs_fake",
    )


def _issue(number: int = 60, state: str = "OPEN") -> github_rest.Issue:
    return github_rest.Issue(number=number, title="t", state=state)


# ---------------------------------------------------------------------------
# post_comment
# ---------------------------------------------------------------------------


class TestPostComment:
    def test_posts_comment_and_updates_label(self):
        db = _make_db()
        insert_item(db, id=30, type="issue", status="implementing", project="buzz", github_issue="#50")
        stdout = io.StringIO()

        with patch(f"{GH_PATCH}._github_auth_available", return_value=True), patch(
            f"{GH_PATCH}._validate_issue_in_repo",
            autospec=True,
            return_value=True,
        ), patch.object(
            backlog_github_comments, "resolve_project_github_auth",
            return_value=_ok_auth(),
        ), patch.object(
            backlog_github_comments, "_ensure_label",
        ), patch.object(
            backlog_github_comments.github_rest, "post_comment",
        ) as post_comment, patch.object(
            backlog_github_comments._label_rest, "add_labels",
        ) as add_labels, patch.object(
            backlog_github_comments._label_rest, "remove_label",
        ) as remove_label:
            rc = backlog_github_sync.post_comment("30", "idea", "implementing", conn=db, stdout=stdout)

        assert rc == 0
        assert "Posted status update to #50" in stdout.getvalue()
        post_comment.assert_called_once()
        assert "`idea` → `implementing`" in post_comment.call_args.kwargs["body"]
        assert post_comment.call_args.kwargs["number"] == 50
        add_labels.assert_called_once()
        assert add_labels.call_args.args[1] == 50
        assert add_labels.call_args.args[2] == ["status:implementing"]
        remove_label.assert_called_once()
        assert remove_label.call_args.args[2] == "status:idea"
        db.close()

    def test_issue_validation_failure_is_nonzero(self):
        db = _make_db()
        insert_item(
            db, id=31, type="issue", status="implementing",
            project="buzz", github_issue="#51",
        )
        stderr = io.StringIO()

        with patch(
            f"{GH_PATCH}._github_auth_available", return_value=True,
        ), patch(
            f"{GH_PATCH}._validate_issue_in_repo",
            autospec=True,
            return_value=False,
        ):
            rc = backlog_github_sync.post_comment(
                "31", "idea", "implementing", conn=db, stderr=stderr,
            )

        assert rc == 1
        assert "issue validation failed" in stderr.getvalue()
        assert "repo mismatch" not in stderr.getvalue()
        db.close()

    def test_noop_when_no_github_issue(self):
        db = _make_db()
        insert_item(db, id=30, type="issue", status="idea", project="buzz")
        with patch(f"{GH_PATCH}._github_auth_available", return_value=True), patch.object(
            backlog_github_comments.github_rest, "post_comment",
        ) as post_comment:
            rc = backlog_github_sync.post_comment("30", "idea", "implementing", conn=db)
        assert rc == 0
        post_comment.assert_not_called()
        db.close()

    def test_dry_run_skips(self):
        db = _make_db()
        insert_item(db, id=30, type="issue", status="idea", project="buzz", github_issue="#50")
        stdout = io.StringIO()
        with patch.object(backlog_github_sync, "_dry_run", return_value=True):
            rc = backlog_github_sync.post_comment("30", "idea", "implementing", conn=db, stdout=stdout)
        assert rc == 0
        assert "DRY-RUN" in stdout.getvalue()
        db.close()


# ---------------------------------------------------------------------------
# close_issue
# ---------------------------------------------------------------------------


class TestCloseIssue:
    def test_closes_open_issue(self):
        db = _make_db()
        insert_item(db, id=40, type="issue", status="done", project="buzz", github_issue="#60")
        stdout = io.StringIO()

        with patch(f"{GH_PATCH}._github_auth_available", return_value=True), patch(
            f"{GH_PATCH}._validate_issue_in_repo",
            autospec=True,
            return_value=True,
        ), patch.object(
            backlog_github_state_sync, "resolve_project_github_auth",
            return_value=_ok_auth(),
        ), patch.object(
            backlog_github_state_sync, "_ensure_label",
        ), patch.object(
            backlog_github_state_sync, "_get_issue_labels",
            return_value=["status:implementing"],
        ), patch.object(
            backlog_github_state_sync, "_get_issue_state",
            return_value="OPEN",
        ), patch.object(
            backlog_github_state_sync._label_rest, "add_labels",
        ), patch.object(
            backlog_github_state_sync._label_rest, "remove_label",
        ), patch.object(
            backlog_github_state_sync.github_rest, "set_issue_state",
            return_value=_issue(state="CLOSED"),
        ) as set_state:
            rc = backlog_github_sync.close_issue("40", conn=db, stdout=stdout)

        assert rc == 0
        assert "Closed: BUZ-40 -> #60" in stdout.getvalue()
        set_state.assert_called_once()
        assert set_state.call_args.kwargs["state"] == "closed"
        assert set_state.call_args.kwargs["number"] == 60
        db.close()

    def test_already_closed_is_noop(self):
        db = _make_db()
        insert_item(db, id=40, type="issue", status="done", project="buzz", github_issue="#60")
        stdout = io.StringIO()

        with patch(f"{GH_PATCH}._github_auth_available", return_value=True), patch(
            f"{GH_PATCH}._validate_issue_in_repo", return_value=True
        ), patch.object(
            backlog_github_state_sync, "resolve_project_github_auth",
            return_value=_ok_auth(),
        ), patch.object(
            backlog_github_state_sync, "_ensure_label",
        ), patch.object(
            backlog_github_state_sync, "_get_issue_labels",
            return_value=["status:done"],
        ), patch.object(
            backlog_github_state_sync, "_get_issue_state",
            return_value="CLOSED",
        ), patch.object(
            backlog_github_state_sync._label_rest, "add_labels",
        ), patch.object(
            backlog_github_state_sync._label_rest, "remove_label",
        ), patch.object(
            backlog_github_state_sync.github_rest, "set_issue_state",
        ) as set_state:
            rc = backlog_github_sync.close_issue("40", conn=db, stdout=stdout)

        assert rc == 0
        assert "already closed" in stdout.getvalue()
        set_state.assert_not_called()
        db.close()

    def test_noop_when_no_github_issue(self):
        db = _make_db()
        insert_item(db, id=40, type="issue", status="done", project="buzz")
        stdout = io.StringIO()
        with patch(f"{GH_PATCH}._github_auth_available", return_value=True), patch.object(
            backlog_github_state_sync.github_rest, "set_issue_state",
        ) as set_state:
            rc = backlog_github_sync.close_issue("40", conn=db, stdout=stdout)
        assert rc == 0
        assert "skipping close" in stdout.getvalue()
        set_state.assert_not_called()
        db.close()


# ---------------------------------------------------------------------------
# reopen_issue
# ---------------------------------------------------------------------------


class TestReopenIssue:
    def test_reopens_closed_issue(self):
        db = _make_db()
        insert_item(db, id=50, type="issue", status="implementing", project="buzz", github_issue="#70")
        stdout = io.StringIO()

        with patch(f"{GH_PATCH}._github_auth_available", return_value=True), patch(
            f"{GH_PATCH}._validate_issue_in_repo", return_value=True
        ), patch.object(
            backlog_github_state_sync, "_get_issue_state",
            return_value="CLOSED",
        ), patch.object(
            backlog_github_state_sync.github_rest, "set_issue_state",
            return_value=_issue(number=70, state="OPEN"),
        ) as set_state:
            rc = backlog_github_sync.reopen_issue("50", conn=db, stdout=stdout)

        assert rc == 0
        assert "Reopened: BUZ-50 → #70" in stdout.getvalue()
        set_state.assert_called_once()
        assert set_state.call_args.kwargs["state"] == "open"
        assert set_state.call_args.kwargs["number"] == 70
        db.close()

    def test_already_open_is_noop(self):
        db = _make_db()
        insert_item(db, id=50, type="issue", status="implementing", project="buzz", github_issue="#70")
        stdout = io.StringIO()

        with patch(f"{GH_PATCH}._github_auth_available", return_value=True), patch(
            f"{GH_PATCH}._validate_issue_in_repo", return_value=True
        ), patch.object(
            backlog_github_state_sync, "_get_issue_state",
            return_value="OPEN",
        ), patch.object(
            backlog_github_state_sync.github_rest, "set_issue_state",
        ) as set_state:
            rc = backlog_github_sync.reopen_issue("50", conn=db, stdout=stdout)

        assert rc == 0
        assert "Already open" in stdout.getvalue()
        set_state.assert_not_called()
        db.close()

    def test_dry_run_skips(self):
        db = _make_db()
        insert_item(db, id=50, type="issue", status="implementing", project="buzz", github_issue="#70")
        stdout = io.StringIO()
        with patch.object(backlog_github_sync, "_dry_run", return_value=True):
            rc = backlog_github_sync.reopen_issue("50", conn=db, stdout=stdout)
        assert rc == 0
        assert "DRY-RUN" in stdout.getvalue()
        db.close()
