"""Tests for the one-time oversized-body backfill subcommand.

Covers AC-1 through AC-6 of Task 009:
- identifies-oversized: only items whose rendered body exceeds the budget
  trigger a ``sync_body`` call.
- sync_body compact-mirror semantics: the backfill calls ``sync_body``
  (which routes through the compact-mirror path via Task 008).
- idempotence: a second run that sees compact mirrors (under budget)
  reports zero repairs.
- auth-failure-skip: ``ProjectGithubAuthError`` is caught per item,
  logged with the typed class name, counted, and surfaces as a non-zero
  exit while later items continue.
"""

from __future__ import annotations

import io
from unittest.mock import patch

from runtime.api.backlog_github_sync_test_helpers import make_db as _make_db
from runtime.api.conftest import insert_item
# Import the umbrella module FIRST so its transitive re-export chain
# completes before any sibling-specific submodule attempts to import it.
from yoke_core.domain import backlog_github_sync as _bgs  # noqa: I001
from yoke_core.domain import (
    backlog_github_body_budget as body_budget,
    backlog_github_sync_cli as cli,
)
from yoke_core.domain.project_github_auth import (
    MissingRepoBinding,
    ProjectGithubAuth,
)


_OK_AUTH = ProjectGithubAuth(
    project="externalwebapp",
    repo="org/externalwebapp",
    token="ghs_fake",
)


def _huge_spec() -> str:
    """A spec body large enough that the rendered output overflows the budget."""
    return "a" * (body_budget.GITHUB_BODY_BUDGET_BYTES + 5000)


class TestIdentifiesOversizedItems:
    def test_only_oversized_items_get_sync_body(self):
        """AC-3: only items whose rendered body exceeds the budget are repaired."""
        db = _make_db()
        # Two linked items: one tiny, one huge. Both have github_issue set.
        insert_item(
            db, id=60, type="issue", status="idea", project="externalwebapp",
            github_issue="#80", spec="# tiny",
        )
        insert_item(
            db, id=61, type="issue", status="idea", project="externalwebapp",
            github_issue="#81", spec=_huge_spec(),
        )
        # Third item has no github_issue and must be ignored entirely.
        insert_item(
            db, id=62, type="issue", status="idea", project="externalwebapp",
            spec=_huge_spec(),
        )

        stdout = io.StringIO()
        stderr = io.StringIO()
        sync_calls: list[str] = []

        def fake_sync_body(item_id, **kwargs):
            sync_calls.append(str(item_id))
            return 0

        with patch.object(_bgs, "sync_body", side_effect=fake_sync_body), patch.object(
            cli, "resolve_project_github_auth", return_value=_OK_AUTH,
        ):
            rc = cli.backfill_oversized_bodies(conn=db, stdout=stdout, stderr=stderr)

        assert rc == 0
        assert sync_calls == ["61"]
        out = stdout.getvalue()
        assert "Backfilled: EXT-61" in out
        assert "compact mirror" in out
        # The summary names the repair count.
        assert "Total: 1 items repaired" in out
        # No mention of the tiny or unlinked items.
        assert "EXT-60" not in out
        assert "EXT-62" not in out
        db.close()

    def test_no_linked_items_returns_zero(self):
        """Empty backlog (no github_issue values) reports zero repairs, exit 0."""
        db = _make_db()
        insert_item(db, id=60, type="issue", status="idea", project="externalwebapp")
        stdout = io.StringIO()

        with patch.object(_bgs, "sync_body") as sync_mock:
            rc = cli.backfill_oversized_bodies(conn=db, stdout=stdout)

        assert rc == 0
        sync_mock.assert_not_called()
        assert "Total: 0 items repaired" in stdout.getvalue()
        db.close()


class TestIdempotent:
    def test_second_run_reports_zero_repaired(self):
        """AC-4: a second run sees compact mirrors under budget; no work needed."""
        db = _make_db()
        insert_item(
            db, id=61, type="issue", status="idea", project="externalwebapp",
            github_issue="#81", spec=_huge_spec(),
        )

        stdout1 = io.StringIO()
        with patch.object(_bgs, "sync_body", return_value=0), patch.object(
            cli, "resolve_project_github_auth", return_value=_OK_AUTH,
        ):
            rc1 = cli.backfill_oversized_bodies(conn=db, stdout=stdout1)
        assert rc1 == 0
        assert "Total: 1 items repaired" in stdout1.getvalue()

        # Simulate the post-repair state: the rendered body now fits.
        # The backfill scans + measures the body before calling sync_body, so
        # we patch ``build_body`` for the second invocation to return a small
        # body (matching the on-GitHub compact mirror that fits under the
        # budget). Patch on the cli module's local name (cli does
        # ``from yoke_core.domain.render_body import build_body``).
        stdout2 = io.StringIO()
        with patch.object(
            cli, "build_body", return_value="# tiny mirror",
        ), patch.object(_bgs, "sync_body") as sync_mock, patch.object(
            cli, "resolve_project_github_auth", return_value=_OK_AUTH,
        ):
            rc2 = cli.backfill_oversized_bodies(conn=db, stdout=stdout2)

        assert rc2 == 0
        sync_mock.assert_not_called()
        assert "Total: 0 items repaired" in stdout2.getvalue()
        db.close()


class TestSkipsOnAuthFailure:
    def test_auth_failure_skips_item_and_continues(self):
        """AC-6: ProjectGithubAuthError per item is logged + counted; later
        items still process; final exit is non-zero."""
        db = _make_db()
        insert_item(
            db, id=61, type="issue", status="idea", project="externalwebapp",
            github_issue="#81", spec=_huge_spec(),
        )
        insert_item(
            db, id=62, type="issue", status="idea", project="externalwebapp",
            github_issue="#82", spec=_huge_spec(),
        )

        def raise_missing_binding_for_61(project, *args, **kwargs):
            # First-call lookup is project-keyed: both items share project=externalwebapp,
            # so use a stateful counter so the *first* call raises and the
            # second succeeds.
            calls = raise_missing_binding_for_61._calls + 1
            raise_missing_binding_for_61._calls = calls
            if calls == 1:
                raise MissingRepoBinding("externalwebapp", "repository is not bound")
            return _OK_AUTH

        raise_missing_binding_for_61._calls = 0

        stdout = io.StringIO()
        stderr = io.StringIO()
        sync_calls: list[str] = []

        def fake_sync_body(item_id, **kwargs):
            sync_calls.append(str(item_id))
            return 0

        with patch.object(_bgs, "sync_body", side_effect=fake_sync_body), patch.object(
            cli, "resolve_project_github_auth",
            side_effect=raise_missing_binding_for_61,
        ):
            rc = cli.backfill_oversized_bodies(
                conn=db, stdout=stdout, stderr=stderr,
            )

        # Any auth failure → non-zero exit.
        assert rc == 1
        # Only the second item went through sync_body — the first was skipped.
        assert sync_calls == ["62"]
        # The skipped item is logged with the typed class name to stderr.
        skipped = stderr.getvalue()
        assert "EXT-61" in skipped
        assert "MissingRepoBinding" in skipped
        # The summary names the auth failure count.
        out = stdout.getvalue()
        assert "auth failures 1" in out
        assert "Total: 1 items repaired" in out
        db.close()

    def test_sync_failure_counted_and_returns_nonzero(self):
        """A non-auth sync failure also drives a non-zero exit code."""
        db = _make_db()
        insert_item(
            db, id=61, type="issue", status="idea", project="externalwebapp",
            github_issue="#81", spec=_huge_spec(),
        )
        stdout = io.StringIO()
        stderr = io.StringIO()

        with patch.object(_bgs, "sync_body", return_value=1), patch.object(
            cli, "resolve_project_github_auth", return_value=_OK_AUTH,
        ):
            rc = cli.backfill_oversized_bodies(
                conn=db, stdout=stdout, stderr=stderr,
            )

        assert rc == 1
        assert "sync failures 1" in stdout.getvalue()
        assert "Failed: EXT-61" in stderr.getvalue()
        db.close()
