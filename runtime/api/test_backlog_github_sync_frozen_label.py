"""Frozen-label synchronization coverage."""

from __future__ import annotations

import io
from unittest.mock import patch

from yoke_contracts.github_app_installation_permissions import (
    GITHUB_ISSUES_WRITE_PERMISSION_LEVELS,
)
from runtime.api.backlog_github_sync_test_helpers import (
    GH_PATCH,
    make_db as _make_db,
)
from runtime.api.conftest import insert_item
from yoke_core.domain import backlog_github_state_sync, backlog_github_sync
from yoke_core.domain.project_github_auth import ProjectGithubAuth


_LABEL_REST_STATE = "yoke_core.domain.backlog_github_state_sync._label_rest"


def _ok_resolver(*args, **kwargs):
    project = kwargs.get("project") or (args[0] if args else "externalwebapp")
    return ProjectGithubAuth(
        project=project, repo="org/externalwebapp", token="ghs_fake",
    )


class TestSyncFrozenLabel:
    def test_missing_issue_is_silent(self):
        db = _make_db()
        insert_item(db, id=7, type="issue", status="implementing", project="externalwebapp")
        with patch(f"{GH_PATCH}._github_auth_available", return_value=True), patch(
            f"{_LABEL_REST_STATE}.ensure_label",
        ) as ensure, patch(
            f"{_LABEL_REST_STATE}.add_labels",
        ) as add, patch(
            f"{_LABEL_REST_STATE}.remove_label",
        ) as remove:
            rc = backlog_github_sync.sync_frozen_label("7", "true", conn=db)
        assert rc == 0
        ensure.assert_not_called()
        add.assert_not_called()
        remove.assert_not_called()
        db.close()

    def test_adds_frozen_label_in_project_repo(self):
        db = _make_db()
        insert_item(
            db,
            id=7,
            type="issue",
            status="implementing",
            project="externalwebapp",
            github_issue="#42",
        )
        stdout = io.StringIO()

        with patch(f"{GH_PATCH}._github_auth_available", return_value=True), patch(
            f"{GH_PATCH}._validate_issue_in_repo",
            autospec=True,
            return_value=True,
        ), patch.object(
            backlog_github_state_sync, "resolve_project_github_auth",
            side_effect=_ok_resolver,
        ) as resolve_auth, patch(f"{_LABEL_REST_STATE}.ensure_label") as ensure, patch(
            f"{_LABEL_REST_STATE}.add_labels",
        ) as add_labels:
            rc = backlog_github_sync.sync_frozen_label("7", "true", conn=db, stdout=stdout)

        assert rc == 0
        assert resolve_auth.call_args.kwargs == {
            "required_permissions": GITHUB_ISSUES_WRITE_PERMISSION_LEVELS,
        }
        ensure.assert_called_once()
        add_labels.assert_called_once_with(
            "org/externalwebapp", 42, ["frozen"], token="ghs_fake",
        )
        assert "Frozen label added: EXT-7 → #42" in stdout.getvalue()
        db.close()

    def test_removes_frozen_label_when_value_false(self):
        db = _make_db()
        insert_item(
            db,
            id=7,
            type="issue",
            status="implementing",
            project="externalwebapp",
            github_issue="#42",
        )
        stdout = io.StringIO()

        with patch(f"{GH_PATCH}._github_auth_available", return_value=True), patch(
            f"{GH_PATCH}._validate_issue_in_repo", return_value=True,
        ), patch.object(
            backlog_github_state_sync, "resolve_project_github_auth",
            side_effect=_ok_resolver,
        ), patch(f"{_LABEL_REST_STATE}.ensure_label"), patch(
            f"{_LABEL_REST_STATE}.remove_label",
        ) as remove_label:
            rc = backlog_github_sync.sync_frozen_label(
                "7", "false", conn=db, stdout=stdout,
            )

        assert rc == 0
        remove_label.assert_called_once_with(
            "org/externalwebapp", 42, "frozen", token="ghs_fake",
        )
        assert "Frozen label removed: EXT-7 → #42" in stdout.getvalue()
        db.close()

    def test_issue_validation_failure_is_nonzero(self):
        db = _make_db()
        insert_item(
            db,
            id=8,
            type="issue",
            status="implementing",
            project="externalwebapp",
            github_issue="#43",
        )
        stderr = io.StringIO()

        with patch(
            f"{GH_PATCH}._github_auth_available", return_value=True,
        ), patch(
            f"{GH_PATCH}._validate_issue_in_repo",
            autospec=True,
            return_value=False,
        ):
            rc = backlog_github_sync.sync_frozen_label(
                "8", "true", conn=db, stderr=stderr,
            )

        assert rc == 1
        assert "issue validation failed" in stderr.getvalue()
        assert "repo mismatch" not in stderr.getvalue()
        db.close()
