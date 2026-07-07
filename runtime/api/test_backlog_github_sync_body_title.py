"""Body- and title-sync coverage: ``sync_body`` and ``sync_title``.

Covers AC-5 (sync_body uses ``select_body_for_github`` before the typed
REST update), AC-9 (auth-precedence short-circuit), AC-11 (below-budget,
above-budget, auth-failure-short-circuit regressions), and AC-13 (no
GraphQL "Body is too long" error path).

Tests mock the typed ``github_rest.update_issue`` surface directly.
"""

from __future__ import annotations

import io
from unittest.mock import patch

import pytest

from runtime.api.backlog_github_sync_test_helpers import (
    GH_PATCH,
    make_db as _make_db,
)
from runtime.api.conftest import insert_item
# Import the umbrella module FIRST so its transitive re-export chain
# completes before any sibling-specific submodule attempts to import it.
from yoke_core.domain import backlog_github_sync  # noqa: I001
from yoke_core.domain import (
    backlog_github_body_budget as body_budget,
    backlog_github_body_title_sync as body_title_sync,
    github_rest,
)

# Real resolver class so the AC-9 regression can construct + raise the
# typed exception subclass that callers branch on.
from yoke_core.domain.project_github_auth import (
    MissingToken,
    ProjectGithubAuth,
)


def _ok_resolver(*args, **kwargs):
    return ProjectGithubAuth(
        project=kwargs.get("project") or (args[0] if args else "buzz"),
        repo="org/buzz",
        token="ghp_fake",
        env={"GH_TOKEN": "ghp_fake"},
    )


def _fake_issue(**overrides):
    base = dict(number=80, title="title", state="OPEN")
    base.update(overrides)
    return github_rest.Issue(**base)


# ---------------------------------------------------------------------------
# sync_body
# ---------------------------------------------------------------------------


class TestSyncBody:
    def test_syncs_body_to_github(self):
        db = _make_db()
        insert_item(
            db,
            id=60,
            type="issue",
            status="idea",
            project="buzz",
            github_issue="#80",
            spec="# Test body",
        )
        stdout = io.StringIO()

        with patch(f"{GH_PATCH}._pat_available", return_value=True), patch(
            f"{GH_PATCH}._validate_issue_in_repo", return_value=True
        ), patch.object(
            body_title_sync.github_rest, "update_issue",
            return_value=_fake_issue(),
        ) as update_issue, patch.object(
            body_title_sync, "resolve_project_github_auth",
            side_effect=_ok_resolver,
        ):
            rc = backlog_github_sync.sync_body("60", conn=db, stdout=stdout)

        assert rc == 0
        assert "Synced body: BUZ-60 → #80" in stdout.getvalue()
        update_issue.assert_called_once()
        assert update_issue.call_args.kwargs["number"] == 80
        assert update_issue.call_args.kwargs["project"] == "buzz"
        # body is the rendered structured body — value depends on the
        # in-memory schema; presence of the kwarg is the contract.
        assert "body" in update_issue.call_args.kwargs
        db.close()

    def test_below_budget_uses_full_body(self):
        """AC-11: small body → full mode; mirror is NOT used."""
        db = _make_db()
        insert_item(
            db, id=60, type="issue", status="idea", project="buzz",
            github_issue="#80", spec="# Tiny body",
        )
        stdout = io.StringIO()

        with patch(f"{GH_PATCH}._pat_available", return_value=True), patch(
            f"{GH_PATCH}._validate_issue_in_repo", return_value=True
        ), patch.object(
            body_title_sync.github_rest, "update_issue",
            return_value=_fake_issue(),
        ) as update_issue, patch.object(
            body_title_sync, "resolve_project_github_auth",
            side_effect=_ok_resolver,
        ):
            rc = backlog_github_sync.sync_body("60", conn=db, stdout=stdout)

        assert rc == 0
        body_sent = update_issue.call_args.kwargs["body"]
        assert not body_budget.body_exceeds_budget(body_sent)
        db.close()

    def test_above_budget_uses_compact_mirror(self):
        """AC-11: oversized body → compact mirror path engages."""
        db = _make_db()
        huge_spec = "a" * (body_budget.GITHUB_BODY_BUDGET_BYTES + 100)
        insert_item(
            db, id=60, type="issue", status="idea", project="buzz",
            github_issue="#80", spec=huge_spec,
        )
        stdout = io.StringIO()
        stderr = io.StringIO()

        with patch(f"{GH_PATCH}._pat_available", return_value=True), patch(
            f"{GH_PATCH}._validate_issue_in_repo", return_value=True
        ), patch.object(
            body_title_sync.github_rest, "update_issue",
            return_value=_fake_issue(),
        ) as update_issue, patch.object(
            body_title_sync, "resolve_project_github_auth",
            side_effect=_ok_resolver,
        ):
            rc = backlog_github_sync.sync_body(
                "60", conn=db, stdout=stdout, stderr=stderr,
            )

        assert rc == 0
        body_sent = update_issue.call_args.kwargs["body"]
        assert len(body_sent.encode("utf-8")) <= body_budget.GITHUB_BODY_BUDGET_BYTES
        assert "compact mirror" in stderr.getvalue()
        db.close()

    def test_auth_failure_short_circuits_body_budget_check(self):
        """AC-9: resolver runs FIRST; body_exceeds_budget is never called
        when the resolver raises a ProjectGithubAuthError subclass."""
        db = _make_db()
        insert_item(
            db, id=60, type="issue", status="idea", project="buzz",
            github_issue="#80", spec="some body",
        )
        stderr = io.StringIO()

        def fail_budget_check(*a, **kw):
            pytest.fail(
                "body_exceeds_budget should not be called on auth failure",
            )

        def raise_missing_token(*a, **kw):
            raise MissingToken("buzz", "no token configured for buzz")

        with patch.object(
            body_budget, "body_exceeds_budget", side_effect=fail_budget_check,
        ), patch.object(
            body_title_sync, "resolve_project_github_auth",
            side_effect=raise_missing_token,
        ), patch(f"{GH_PATCH}._pat_available", return_value=True), patch.object(
            body_title_sync.github_rest, "update_issue",
        ) as update_issue:
            rc = backlog_github_sync.sync_body("60", conn=db, stderr=stderr)

        assert rc == 1
        # REST call MUST NOT be made on auth failure.
        update_issue.assert_not_called()
        msg = stderr.getvalue()
        assert "MissingToken" in msg
        # No GraphQL "Body is too long" error path is exercised.
        assert "GraphQL" not in msg
        assert "Body is too long" not in msg
        db.close()

    def test_noop_when_no_github_issue(self):
        db = _make_db()
        insert_item(db, id=60, type="issue", status="idea", project="buzz")
        with patch(f"{GH_PATCH}._pat_available", return_value=True), patch.object(
            body_title_sync.github_rest, "update_issue",
        ) as update_issue:
            rc = backlog_github_sync.sync_body("60", conn=db)
        assert rc == 0
        update_issue.assert_not_called()
        db.close()

    def test_dry_run_skips(self):
        db = _make_db()
        insert_item(db, id=60, type="issue", status="idea", project="buzz", github_issue="#80")
        stdout = io.StringIO()
        with patch.object(backlog_github_sync, "_dry_run", return_value=True):
            rc = backlog_github_sync.sync_body("60", conn=db, stdout=stdout)
        assert rc == 0
        assert "DRY-RUN" in stdout.getvalue()
        db.close()


# ---------------------------------------------------------------------------
# sync_title
# ---------------------------------------------------------------------------


class TestSyncTitle:
    def test_syncs_title_to_github(self):
        db = _make_db()
        insert_item(
            db,
            id=70,
            type="issue",
            status="idea",
            project="buzz",
            github_issue="#90",
            title="My test title",
        )
        stdout = io.StringIO()

        with patch(f"{GH_PATCH}._pat_available", return_value=True), patch(
            f"{GH_PATCH}._validate_issue_in_repo", return_value=True
        ), patch.object(
            body_title_sync.github_rest, "update_issue",
            return_value=_fake_issue(number=90, title="[BUZ-70] My test title"),
        ) as update_issue:
            rc = backlog_github_sync.sync_title("70", conn=db, stdout=stdout)

        assert rc == 0
        assert "Synced title: BUZ-70 → #90" in stdout.getvalue()
        update_issue.assert_called_once()
        assert update_issue.call_args.kwargs == {
            "project": "buzz",
            "number": 90,
            "title": "[BUZ-70] My test title",
        }
        db.close()

    def test_noop_when_no_github_issue(self):
        db = _make_db()
        insert_item(db, id=70, type="issue", status="idea", project="buzz")
        with patch(f"{GH_PATCH}._pat_available", return_value=True), patch.object(
            body_title_sync.github_rest, "update_issue",
        ) as update_issue:
            rc = backlog_github_sync.sync_title("70", conn=db)
        assert rc == 0
        update_issue.assert_not_called()
        db.close()
