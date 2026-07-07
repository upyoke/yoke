"""Doctor HC tests for wrong-repo and orphaned-active-items checks.

Delegated-sync and gh-orphan-detection tests live in test_doctor_hc_git_full.py.
Worktree-health/stale-remote-branches tests live in test_doctor_hc_git_full_worktree.py.
Orphaned-gh-issues tests live in test_doctor_hc_git_full_orphans.py.

Schema scaffolding is shared via _doctor_hc_git_test_helpers (private module).
"""

from __future__ import annotations

from unittest.mock import patch

from yoke_core.engines._doctor_hc_git_test_helpers import (
    _completed,
    _insert_item,
    _make_conn,
    _result,
    _run_hc,
    _seed_project,
)
from yoke_core.engines.doctor import (
    RecordCollector,
    hc_orphaned_active_items,
    hc_wrong_repo_issues,
)


class TestWrongRepoIssues:
    """Tests for hc_wrong_repo_issues."""

    @patch("yoke_core.engines.doctor_hc_worktrees._pat_configured", return_value=False)
    def test_no_pat_skips(self, mock_gh):
        """T6: SKIPs with canonical reason when project PAT is missing."""
        rec = _run_hc(hc_wrong_repo_issues)
        assert _result(rec).result == "SKIP"
        assert "PAT capability not configured" in _result(rec).detail

    @patch("yoke_core.engines.doctor_hc_worktrees._pat_configured", return_value=True)
    @patch("yoke_core.engines.doctor_hc_worktrees_gh_repo.resolve_project_github_auth",
           side_effect=lambda project, db_path=None: _auth(
               "upyoke/yoke" if project == "yoke" else f"example-org/{project}"))
    @patch("yoke_core.engines.doctor_hc_worktrees_gh_repo.issue_view_state")
    def test_issue_in_correct_repo(self, mock_gh_run, mock_resolve, mock_avail):
        """T4: PASS when issue is in correct repo."""
        conn = _make_conn()
        _seed_project(conn, "buzz", github_repo="example-org/buzz")
        _insert_item(conn, 42, "Buzz item", project="buzz",
                     type="issue", status="implementing", github_issue="#100")
        mock_gh_run.return_value = _completed(stdout="OPEN\n")
        rec = _run_hc(hc_wrong_repo_issues, conn)
        assert _result(rec).result == "PASS"

    @patch("yoke_core.engines.doctor_hc_worktrees._pat_configured", return_value=True)
    @patch("yoke_core.engines.doctor_hc_worktrees_gh_repo.resolve_project_github_auth",
           side_effect=lambda project, db_path=None: _auth(
               "upyoke/yoke" if project == "yoke" else f"example-org/{project}"))
    @patch("yoke_core.engines.doctor_hc_worktrees_gh_repo.issue_view_state")
    def test_issue_in_wrong_repo(self, mock_gh_run, mock_resolve, mock_avail):
        """T3: Detects wrong-repo (buzz item in yoke repo)."""
        conn = _make_conn()
        _seed_project(conn, "buzz", github_repo="example-org/buzz")
        _insert_item(conn, 662, "Buzz wrong repo", project="buzz",
                     type="issue", status="implementing", github_issue="#1520")
        # Not found in target repo, found in yoke repo
        mock_gh_run.side_effect = [
            _completed(returncode=1, stdout=""),
            _completed(stdout="OPEN\n"),
        ]
        rec = _run_hc(hc_wrong_repo_issues, conn)
        assert _result(rec).result == "WARN"
        assert "YOK-662" in _result(rec).detail
        assert "wrong" in _result(rec).detail.lower() or "Wrong" in _result(rec).detail

    @patch("yoke_core.engines.doctor_hc_worktrees._pat_configured", return_value=True)
    @patch("yoke_core.engines.doctor_hc_worktrees_gh_repo.resolve_project_github_auth",
           side_effect=lambda project, db_path=None: _auth("upyoke/yoke"))
    @patch("yoke_core.engines.doctor_hc_worktrees_gh_repo.issue_view_state")
    def test_yoke_only_items_skipped(self, mock_gh_run, mock_resolve, mock_avail):
        """T5: Same-repo Yoke rows are filtered before any REST call.

        Includes a real ``projects`` row for ``yoke`` so the row passes
        the JOIN; the same-repo filter (target_repo == resolved Yoke
        repo) keeps ``issue_view_state`` from firing.
        """
        conn = _make_conn()
        _seed_project(conn, "yoke", github_repo="upyoke/yoke")
        _insert_item(conn, 100, "Yoke item",
                     type="issue", status="implementing", github_issue="#100")
        rec = _run_hc(hc_wrong_repo_issues, conn)
        assert _result(rec).result == "PASS"
        # Same-repo skip must short-circuit BEFORE the REST lookup.
        assert mock_gh_run.call_count == 0

    @patch("yoke_core.engines.doctor_hc_worktrees._pat_configured", return_value=True)
    @patch("yoke_core.engines.doctor_hc_worktrees_gh_repo.resolve_project_github_auth",
           side_effect=lambda project, db_path=None: _auth(
               "upyoke/yoke" if project == "yoke" else f"example-org/{project}"))
    @patch("yoke_core.engines.doctor_hc_worktrees_gh_repo.issue_view_state")
    def test_auth_resolved_once_per_distinct_project(self, mock_gh_run, mock_resolve, mock_avail):
        """AC-13: ``resolve_project_github_auth`` runs at most once per distinct project.

        Mixes multiple Yoke rows (same-repo, skipped before REST) with
        multiple Buzz rows (external, REST-bound) and asserts the
        resolver call count equals the number of distinct projects.
        """
        conn = _make_conn()
        _seed_project(conn, "yoke", github_repo="upyoke/yoke")
        _seed_project(conn, "buzz", github_repo="example-org/buzz")
        for i in range(3):
            _insert_item(
                conn, 200 + i, "Yoke item",
                type="issue", status="implementing", github_issue=f"#{300 + i}",
            )
        for i in range(4):
            _insert_item(
                conn, 400 + i, "Buzz item", project="buzz",
                type="issue", status="implementing", github_issue=f"#{500 + i}",
            )
        mock_gh_run.return_value = _completed(stdout="OPEN\n")
        rec = _run_hc(hc_wrong_repo_issues, conn)

        assert _result(rec).result == "PASS"
        # Yoke resolves once for the upfront yoke_auth lookup; buzz
        # resolves once for the in-loop cache. Yoke rows are skipped
        # before the in-loop resolve fires.
        resolved_projects = [c.args[0] for c in mock_resolve.call_args_list]
        assert resolved_projects.count("yoke") == 1
        assert resolved_projects.count("buzz") == 1
        # Only the 4 buzz rows reach the REST call — yoke rows skip.
        assert mock_gh_run.call_count == 4

    @patch("yoke_core.engines.doctor_hc_worktrees._pat_configured", return_value=True)
    @patch("yoke_core.engines.doctor_hc_worktrees_gh_repo.resolve_project_github_auth",
           side_effect=lambda project, db_path=None: _auth(
               "upyoke/yoke" if project == "yoke" else f"example-org/{project}"))
    @patch("yoke_core.engines.doctor_hc_worktrees_gh_repo.issue_view_state")
    def test_per_project_iteration(self, mock_gh_run, mock_resolve, mock_avail):
        """T1/T2: HC fetches issues from multiple project repos."""
        conn = _make_conn()
        _seed_project(conn, "buzz", github_repo="example-org/buzz")
        _insert_item(conn, 100, "Yoke item",
                     type="issue", status="implementing", github_issue="#100")
        _insert_item(conn, 200, "Buzz item", project="buzz",
                     type="issue", status="implementing", github_issue="#50")
        # Issue found in target repo for buzz
        mock_gh_run.return_value = _completed(stdout="OPEN\n")
        rec = _run_hc(hc_wrong_repo_issues, conn)
        assert _result(rec).result == "PASS"


def _auth(repo: str):
    """Build a ProjectGithubAuth stub for resolver patches."""
    from yoke_core.domain.project_github_auth import ProjectGithubAuth
    return ProjectGithubAuth(project="yoke", repo=repo, token="t", env={"GH_TOKEN": "t"})


class TestOrphanedActiveItems:
    """Tests for hc_orphaned_active_items."""

    def test_pass_no_orphans(self):
        """T1: PASS when no orphaned items exist."""
        conn = _make_conn()
        conn.execute(
            "INSERT INTO items (id, title, type, status, worktree) "
            "VALUES (10, 'Active item', 'issue', 'implementing', 'YOK-10')"
        )
        rec = _run_hc(hc_orphaned_active_items, conn)
        assert _result(rec).result == "PASS"

    @patch("yoke_core.engines.doctor_report._run")
    def test_warn_branch_merged_but_active(self, mock_run):
        """T2: WARN when branch is merged to main but status is still active."""
        conn = _make_conn()
        conn.execute(
            "INSERT INTO items (id, title, type, status, worktree) "
            "VALUES (20, 'Merged but active', 'issue', 'implementing', 'YOK-20')"
        )
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
            "INSERT INTO items (id, title, type, status, worktree, merged_at) "
            "VALUES (30, 'Merged at set', 'issue', 'implementing', 'YOK-30', "
            "'2026-03-01T10:00:00Z')"
        )
        rec = _run_hc(hc_orphaned_active_items, conn)
        assert _result(rec).result == "WARN"
        assert "YOK-30" in _result(rec).detail

    def test_done_items_not_flagged(self):
        """T7: Items in done/cancelled status are not flagged."""
        conn = _make_conn()
        conn.execute(
            "INSERT INTO items (id, title, type, status, merged_at) "
            "VALUES (70, 'Done item', 'issue', 'done', '2026-03-01T10:00:00Z')"
        )
        conn.execute(
            "INSERT INTO items (id, title, type, status) "
            "VALUES (71, 'Cancelled item', 'issue', 'cancelled')"
        )
        rec = _run_hc(hc_orphaned_active_items, conn)
        assert _result(rec).result == "PASS"

    def test_multiple_orphans(self):
        """T8: Multiple orphaned items reported together."""
        conn = _make_conn()
        # Two items with merged_at set
        conn.execute(
            "INSERT INTO items (id, title, type, status, merged_at) "
            "VALUES (80, 'Orphan 1', 'issue', 'implementing', '2026-03-01T10:00:00Z')"
        )
        conn.execute(
            "INSERT INTO items (id, title, type, status, merged_at) "
            "VALUES (81, 'Orphan 2', 'issue', 'implementing', '2026-03-01T10:00:00Z')"
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
            "INSERT INTO items (id, title, type, status) "
            "VALUES (110, 'Idea item', 'issue', 'idea')"
        )
        rec = _run_hc(hc_orphaned_active_items, conn)
        assert _result(rec).result == "PASS"

    @patch("yoke_core.engines.doctor_report._resolve_repo_root", return_value="/fake/repo")
    @patch("yoke_core.engines.doctor_report._run")
    def test_legacy_ready_status_not_checked(self, mock_run, mock_root):
        """T11b: Legacy ready rows are ignored by the active-item check."""
        conn = _make_conn()
        conn.execute(
            "INSERT INTO items (id, title, type, status, worktree) "
            "VALUES (111, 'Legacy ready item', 'issue', 'ready', 'YOK-111')"
        )
        mock_run.side_effect = [
            _completed(returncode=0, stdout="main\n"),
        ]
        rec = _run_hc(hc_orphaned_active_items, conn)
        assert _result(rec).result == "PASS"

    @patch("yoke_core.engines.doctor_report._resolve_repo_root", return_value="/fake/repo")
    @patch("yoke_core.engines.doctor_report._run")
    def test_deduplication(self, mock_run, mock_root):
        """T4: Item matching both signals appears only once."""
        conn = _make_conn()
        conn.execute(
            "INSERT INTO items (id, title, type, status, worktree, merged_at) "
            "VALUES (40, 'Both signals', 'issue', 'implementing', 'YOK-40', "
            "'2026-03-01T10:00:00Z')"
        )
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
