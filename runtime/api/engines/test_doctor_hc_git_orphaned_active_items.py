"""Doctor HC tests for orphaned active items."""

from unittest.mock import patch

from runtime.api.fixtures.backlog import insert_item_worktree
from yoke_core.engines._doctor_hc_git_test_helpers import (
    _completed,
    _make_conn,
    _result,
    _run_hc,
)
from yoke_core.engines.doctor import hc_orphaned_active_items


def _seed_item_lane(conn, item_id: int, branch: str) -> None:
    insert_item_worktree(conn, item_id=item_id, branch=branch)


class TestOrphanedActiveItems:
    """Tests for hc_orphaned_active_items."""

    def test_pass_no_orphans(self):
        """T1: PASS when no orphaned items exist."""
        conn = _make_conn()
        conn.execute(
            "INSERT INTO items "
            "(id, title, workflow_id, workflow_version_id, status) "
            "VALUES (10, 'Active item', 'issue', "
            "(SELECT current_version_id FROM workflows WHERE id='issue'), "
            "'implementing')"
        )
        _seed_item_lane(conn, 10, "YOK-10")
        rec = _run_hc(hc_orphaned_active_items, conn)
        assert _result(rec).result == "PASS"

    @patch("yoke_core.engines.doctor_report._run")
    def test_warn_branch_merged_but_active(self, mock_run):
        """T2: WARN when branch is merged to main but status is still active."""
        conn = _make_conn()
        conn.execute(
            "INSERT INTO items "
            "(id, title, workflow_id, workflow_version_id, status) "
            "VALUES (20, 'Merged but active', 'issue', "
            "(SELECT current_version_id FROM workflows WHERE id='issue'), "
            "'implementing')"
        )
        _seed_item_lane(conn, 20, "YOK-20")
        # Simulate: branch exists, and is merged
        mock_run.side_effect = [
            _completed(returncode=0, stdout="YOK-20\n"),  # branch exists
            _completed(returncode=0, stdout="abc123\n"),  # merge-base
            _completed(returncode=0, stdout="abc123\n"),  # rev-parse YOK-20
        ]
        rec = _run_hc(hc_orphaned_active_items, conn)
        assert _result(rec).result == "WARN"
        assert "YOK-20" in _result(rec).detail

    def test_warn_merged_at_set_but_not_done(self):
        """T3: WARN when merged_at is set but status is not done."""
        conn = _make_conn()
        conn.execute(
            "INSERT INTO items "
            "(id, title, workflow_id, workflow_version_id, status, merged_at) "
            "VALUES (30, 'Merged at set', 'issue', "
            "(SELECT current_version_id FROM workflows WHERE id='issue'), 'implementing', "
            "'2026-03-01T10:00:00Z')"
        )
        _seed_item_lane(conn, 30, "YOK-30")
        rec = _run_hc(hc_orphaned_active_items, conn)
        assert _result(rec).result == "WARN"
        assert "YOK-30" in _result(rec).detail

    def test_done_items_not_flagged(self):
        """T7: Items in done/cancelled status are not flagged."""
        conn = _make_conn()
        conn.execute(
            "INSERT INTO items (id, title, workflow_id, workflow_version_id, status, merged_at) "
            "VALUES (70, 'Done item', 'issue', (SELECT current_version_id FROM workflows WHERE id='issue'), 'done', '2026-03-01T10:00:00Z')"
        )
        conn.execute(
            "INSERT INTO items (id, title, workflow_id, workflow_version_id, status) "
            "VALUES (71, 'Cancelled item', 'issue', (SELECT current_version_id FROM workflows WHERE id='issue'), 'cancelled')"
        )
        rec = _run_hc(hc_orphaned_active_items, conn)
        assert _result(rec).result == "PASS"

    def test_multiple_orphans(self):
        """T8: Multiple orphaned items reported together."""
        conn = _make_conn()
        # Two items with merged_at set
        conn.execute(
            "INSERT INTO items (id, title, workflow_id, workflow_version_id, status, merged_at) "
            "VALUES (80, 'Orphan 1', 'issue', (SELECT current_version_id FROM workflows WHERE id='issue'), 'implementing', '2026-03-01T10:00:00Z')"
        )
        conn.execute(
            "INSERT INTO items (id, title, workflow_id, workflow_version_id, status, merged_at) "
            "VALUES (81, 'Orphan 2', 'issue', (SELECT current_version_id FROM workflows WHERE id='issue'), 'implementing', '2026-03-01T10:00:00Z')"
        )
        rec = _run_hc(hc_orphaned_active_items, conn)
        assert _result(rec).result == "WARN"
        assert "YOK-80" in _result(rec).detail
        assert "YOK-81" in _result(rec).detail

    def test_idea_status_not_checked(self):
        """T11: Pre-work statuses (idea, defined, designed) not checked."""
        conn = _make_conn()
        # Items in pre-work states with merged_at would be unusual,
        # but the HC only looks at items past the "implementing" stage
        conn.execute(
            "INSERT INTO items (id, title, workflow_id, workflow_version_id, status) "
            "VALUES (110, 'Idea item', 'issue', (SELECT current_version_id FROM workflows WHERE id='issue'), 'idea')"
        )
        rec = _run_hc(hc_orphaned_active_items, conn)
        assert _result(rec).result == "PASS"

    @patch(
        "yoke_core.engines.doctor_report._resolve_repo_root", return_value="/fake/repo"
    )
    @patch("yoke_core.engines.doctor_report._run")
    def test_legacy_ready_status_not_checked(self, mock_run, mock_root):
        """T11b: Legacy ready rows are ignored by the active-item check."""
        conn = _make_conn()
        conn.execute(
            "INSERT INTO items "
            "(id, title, workflow_id, workflow_version_id, status) "
            "VALUES (111, 'Legacy ready item', 'issue', "
            "(SELECT current_version_id FROM workflows WHERE id='issue'), "
            "'ready')"
        )
        _seed_item_lane(conn, 111, "YOK-111")
        mock_run.side_effect = [
            _completed(returncode=0, stdout="main\n"),
        ]
        rec = _run_hc(hc_orphaned_active_items, conn)
        assert _result(rec).result == "PASS"

    @patch(
        "yoke_core.engines.doctor_report._resolve_repo_root", return_value="/fake/repo"
    )
    @patch("yoke_core.engines.doctor_report._run")
    def test_deduplication(self, mock_run, mock_root):
        """T4: Item matching both signals appears only once."""
        conn = _make_conn()
        conn.execute(
            "INSERT INTO items "
            "(id, title, workflow_id, workflow_version_id, status, merged_at) "
            "VALUES (40, 'Both signals', 'issue', "
            "(SELECT current_version_id FROM workflows WHERE id='issue'), 'implementing', "
            "'2026-03-01T10:00:00Z')"
        )
        _seed_item_lane(conn, 40, "YOK-40")
        # Simulate: branch exists and is merged (merge-base --is-ancestor succeeds)
        mock_run.side_effect = [
            _completed(returncode=0, stdout="main\n"),  # rev-parse --verify main
            _completed(returncode=0),  # merge-base --is-ancestor <branch> main
        ]
        rec = _run_hc(hc_orphaned_active_items, conn)
        # flagged by merged_at check first, branch check skips due to dedup
        detail = _result(rec).detail
        # Count only the issue mentions in "YOK-N (status:...)" lines
        import re

        mentions = re.findall(r"YOK-40 \(status:", detail) if detail else []
        assert len(mentions) == 1
