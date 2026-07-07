"""Auth-error translation regressions for ``backlog_github_state_sync``.

Verifies the AC-7 contract: when the typed REST surface raises
:class:`ProjectGithubAuthError` (the canonical resolver's typed
diagnostic), every public entrypoint in ``backlog_github_state_sync``
translates the exception into a non-zero return + typed-stderr
diagnostic carrying the exception class name and a concrete repair
hint. No silent swallow.
"""

from __future__ import annotations

import io
from unittest.mock import patch

import pytest

from runtime.api.backlog_github_sync_test_helpers import GH_PATCH, make_db as _make_db
from runtime.api.conftest import insert_item
from yoke_core.domain import backlog_github_state_sync, backlog_github_sync
from yoke_core.domain.project_github_auth import (
    MissingCapability,
    MissingToken,
)


@pytest.fixture
def db():
    conn = _make_db()
    yield conn
    conn.close()


# ---------------------------------------------------------------------------
# close_issue
# ---------------------------------------------------------------------------


class TestCloseIssueAuthTranslation:
    def test_translates_missing_token_to_sync_warning(self, db):
        insert_item(db, id=40, type="issue", status="done", project="buzz", github_issue="#60")
        stderr = io.StringIO()

        with patch(f"{GH_PATCH}._pat_available", return_value=True), patch(
            f"{GH_PATCH}._validate_issue_in_repo", return_value=True,
        ), patch.object(
            backlog_github_state_sync, "resolve_project_github_auth",
            side_effect=MissingToken("buzz", "no token row for project 'buzz'"),
        ):
            rc = backlog_github_sync.close_issue("40", conn=db, stderr=stderr)

        assert rc == 1  # non-zero — no silent swallow
        text = stderr.getvalue()
        assert "sync_warning=MissingToken" in text
        assert "close_issue skipped for BUZ-40" in text
        assert "Repair:" in text
        assert "capability secret set" in text


# ---------------------------------------------------------------------------
# reopen_issue
# ---------------------------------------------------------------------------


class TestReopenIssueAuthTranslation:
    def test_translates_missing_capability_to_sync_warning(self, db):
        insert_item(db, id=50, type="issue", status="implementing", project="buzz", github_issue="#70")
        stderr = io.StringIO()

        with patch(f"{GH_PATCH}._pat_available", return_value=True), patch(
            f"{GH_PATCH}._validate_issue_in_repo", return_value=True,
        ), patch.object(
            backlog_github_state_sync, "_get_issue_state",
            side_effect=MissingCapability("buzz", "no github capability for project 'buzz'"),
        ):
            rc = backlog_github_sync.reopen_issue("50", conn=db, stderr=stderr)

        assert rc == 1
        text = stderr.getvalue()
        assert "sync_warning=MissingCapability" in text
        assert "reopen_issue skipped for BUZ-50" in text


# ---------------------------------------------------------------------------
# sync_frozen_label / sync_blocked_label (share _sync_flag_label helper)
# ---------------------------------------------------------------------------


class TestFlagLabelAuthTranslation:
    def test_frozen_label_translates_missing_token(self, db):
        insert_item(db, id=60, type="issue", status="implementing", project="buzz", github_issue="#80")
        stderr = io.StringIO()

        with patch(f"{GH_PATCH}._pat_available", return_value=True), patch(
            f"{GH_PATCH}._validate_issue_in_repo", return_value=True,
        ), patch.object(
            backlog_github_state_sync, "resolve_project_github_auth",
            side_effect=MissingToken("buzz", "no token row"),
        ):
            rc = backlog_github_sync.sync_frozen_label(
                "60", "true", conn=db, stderr=stderr,
            )

        assert rc == 1
        text = stderr.getvalue()
        assert "sync_warning=MissingToken" in text
        assert "sync_frozen_label skipped for BUZ-60" in text

    def test_blocked_label_translates_missing_token(self, db):
        insert_item(db, id=70, type="issue", status="implementing", project="buzz", github_issue="#90")
        stderr = io.StringIO()

        with patch(f"{GH_PATCH}._pat_available", return_value=True), patch(
            f"{GH_PATCH}._validate_issue_in_repo", return_value=True,
        ), patch.object(
            backlog_github_state_sync, "resolve_project_github_auth",
            side_effect=MissingToken("buzz", "no token row"),
        ):
            rc = backlog_github_sync.sync_blocked_label(
                "70", "true", conn=db, stderr=stderr,
            )

        assert rc == 1
        text = stderr.getvalue()
        assert "sync_warning=MissingToken" in text
        assert "sync_blocked_label skipped for BUZ-70" in text
