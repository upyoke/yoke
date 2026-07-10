"""Compact-pending flag backfill coverage.

Sibling of ``test_backlog_github_backfill_oversized.py``. Covers the
dual-pass selection: oversized-current items are repaired (compact
mirror), plus every item flagged ``github_body_compact_pending`` —
item-side sync state stamped by the body-sync paths. Flagged items
whose body fits again are re-synced to restore the full body (the
sync clears the flag); the retired pattern inferred this queue from
body-too-long markers in telemetry envelopes.
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
    db_backend,
)
from yoke_core.domain.project_github_auth import ProjectGithubAuth


_OK_AUTH = ProjectGithubAuth(
    project="buzz",
    repo="org/buzz",
    token="ghs_fake",
)


def _p(conn) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _huge_spec() -> str:
    return "a" * (body_budget.GITHUB_BODY_BUDGET_BYTES + 5000)


def _flag_compact_pending(db, item_id: int) -> None:
    p = _p(db)
    db.execute(
        f"UPDATE items SET github_body_compact_pending = {p} "
        f"WHERE id = {p}",
        ("2026-05-13T15:10:00Z", item_id),
    )
    db.commit()


class TestFlagDerivedSelection:
    def test_flagged_item_with_oversized_body_repairs_and_marks_source(self):
        """A flagged item whose body is STILL oversized routes through
        sync_body, labelled ``source=flag+oversized``."""
        db = _make_db()
        insert_item(
            db, id=1704, type="issue", status="idea", project="buzz",
            github_issue="#4114", spec=_huge_spec(),
        )
        _flag_compact_pending(db, 1704)

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
        assert sync_calls == ["1704"]
        out = stdout.getvalue()
        assert "Backfilled: BUZ-1704" in out
        assert "source=flag+oversized" in out
        assert "flag-derived 1" in out
        assert "oversized-current 1" in out
        db.close()

    def test_flagged_item_whose_body_now_fits_is_restored(self):
        """A flagged item whose body fits again is re-synced so the full
        body replaces the compact mirror (sync_body clears the flag)."""
        db = _make_db()
        insert_item(
            db, id=1665, type="issue", status="idea", project="buzz",
            github_issue="#3987", spec="# tiny body that fits under budget",
        )
        _flag_compact_pending(db, 1665)

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
        assert sync_calls == ["1665"]
        out = stdout.getvalue()
        assert "Restored: BUZ-1665" in out
        assert "source=flag" in out
        assert "flag-derived 1" in out
        assert "oversized-current 0" in out
        assert "1 restored" in out
        db.close()

    def test_unlinked_flagged_item_is_dropped_silently(self):
        """A flagged item without a GitHub issue link is not a sync
        candidate — there is no mirror to repair."""
        db = _make_db()
        insert_item(
            db, id=9999, type="issue", status="idea", project="buzz",
            spec="# small",
        )
        _flag_compact_pending(db, 9999)

        stdout = io.StringIO()
        with patch.object(_bgs, "sync_body", return_value=0), patch.object(
            cli, "resolve_project_github_auth", return_value=_OK_AUTH,
        ):
            rc = cli.backfill_oversized_bodies(conn=db, stdout=stdout)

        assert rc == 0
        out = stdout.getvalue()
        assert "flag-derived 0" in out
        assert "Total: 0 items repaired" in out
        db.close()


class TestRecordSyncMode:
    def test_compact_sets_flag_and_full_clears_it(self):
        db = _make_db()
        insert_item(
            db, id=77, type="issue", status="idea", project="buzz",
            github_issue="#77", spec="# body",
        )
        body_budget.record_sync_mode(db, 77, "compact")
        assert body_budget.list_compact_pending_item_ids(db) == [77]
        body_budget.record_sync_mode(db, 77, "full")
        assert body_budget.list_compact_pending_item_ids(db) == []
        db.close()

    def test_none_conn_is_noop(self):
        body_budget.record_sync_mode(None, 1, "compact")
