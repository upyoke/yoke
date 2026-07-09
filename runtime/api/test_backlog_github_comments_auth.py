"""Auth-error translation regression for ``backlog_github_comments``.

Verifies the AC-7 contract: when the typed REST surface raises
:class:`ProjectGithubAuthError` (the canonical resolver's typed
diagnostic), :func:`post_comment` translates the exception into a
non-zero return + typed-stderr diagnostic carrying the exception
class name and a concrete repair hint. No silent swallow.
"""

from __future__ import annotations

import io
from unittest.mock import patch

import pytest

from runtime.api.backlog_github_sync_test_helpers import GH_PATCH, make_db as _make_db
from runtime.api.conftest import insert_item
from yoke_core.domain import backlog_github_comments, backlog_github_sync
from yoke_core.domain.project_github_auth import (
    MissingCapability,
    MissingToken,
)


@pytest.fixture
def db():
    conn = _make_db()
    yield conn
    conn.close()


class TestPostCommentAuthTranslation:
    def test_translates_missing_token_to_sync_warning(self, db):
        insert_item(db, id=30, type="issue", status="implementing", project="buzz", github_issue="#50")
        stderr = io.StringIO()

        with patch(f"{GH_PATCH}._github_auth_available", return_value=True), patch(
            f"{GH_PATCH}._validate_issue_in_repo", return_value=True,
        ), patch.object(
            backlog_github_comments, "resolve_project_github_auth",
            side_effect=MissingToken("buzz", "no token row for project 'buzz'"),
        ):
            rc = backlog_github_sync.post_comment(
                "30", "idea", "implementing", conn=db, stderr=stderr,
            )

        assert rc == 1  # non-zero — no silent swallow
        text = stderr.getvalue()
        assert "sync_warning=MissingToken" in text
        assert "post_comment skipped for BUZ-30" in text
        assert "Repair:" in text
        assert "capability secret set" in text

    def test_translates_missing_capability(self, db):
        insert_item(db, id=31, type="issue", status="implementing", project="buzz", github_issue="#51")
        stderr = io.StringIO()

        with patch(f"{GH_PATCH}._github_auth_available", return_value=True), patch(
            f"{GH_PATCH}._validate_issue_in_repo", return_value=True,
        ), patch.object(
            backlog_github_comments, "resolve_project_github_auth",
            side_effect=MissingCapability("buzz", "no github capability for project 'buzz'"),
        ):
            rc = backlog_github_sync.post_comment(
                "31", "idea", "implementing", conn=db, stderr=stderr,
            )

        assert rc == 1
        text = stderr.getvalue()
        assert "sync_warning=MissingCapability" in text
        assert "post_comment skipped for BUZ-31" in text
