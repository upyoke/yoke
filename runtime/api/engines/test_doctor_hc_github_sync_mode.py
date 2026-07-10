"""Doctor GitHub-validation HCs honor ``projects.github_sync_mode``.

A ``backlog_only`` project keeps its backlog in the Yoke DB only: after
the documented sync-off -> repo-flip cutover its ``github_issue`` refs
stay historical (docs/github-sync.md). The wrong-repo and GitHub-orphan
HCs must treat such projects as out-of-scope — no REST scan, no WARN
flood over the whole backlog — while still recording a mode-language
note in the HC detail.

Schema scaffolding is shared via _doctor_hc_git_test_helpers (private
module); the minimal fixture omits the ``github_sync_mode`` column, so
these tests add it explicitly.
"""

from __future__ import annotations

from unittest.mock import patch

from yoke_core.engines._doctor_hc_git_test_helpers import (
    _completed,
    _make_conn,
    _result,
    _run_hc,
)
from yoke_core.engines._project_identity_test_helpers import _seed_project
from yoke_core.engines.doctor import (
    hc_gh_orphan_detection,
    hc_orphaned_gh_issues,
    hc_wrong_repo_issues,
)


MODE_NOTE = "github_sync_mode=backlog_only"


def _auth(repo: str):
    """Build a ProjectGithubAuth stub for resolver patches."""
    from yoke_core.domain.project_github_auth import ProjectGithubAuth

    return ProjectGithubAuth(
        project="yoke", repo=repo, token="t",
    )


def _set_backlog_only(conn, slug: str) -> None:
    conn.execute("ALTER TABLE projects ADD COLUMN IF NOT EXISTS github_sync_mode TEXT")
    conn.execute(
        "UPDATE projects SET github_sync_mode = 'backlog_only' WHERE slug = %s",
        (slug,),
    )
    conn.commit()


class TestWrongRepoIssuesSyncMode:
    @patch("yoke_core.engines.doctor_hc_worktrees._github_auth_configured", return_value=True)
    @patch("yoke_core.engines.doctor_hc_worktrees_gh_repo.resolve_project_github_auth",
           side_effect=lambda project, db_path=None, **_kwargs: _auth(
               "upyoke/yoke" if project == "yoke" else f"example-org/{project}"))
    @patch("yoke_core.engines.doctor_hc_worktrees_gh_repo.issue_view_state")
    def test_backlog_only_project_rows_skipped_with_note(
        self, mock_gh_run, mock_resolve, mock_avail,
    ):
        """Historical refs of a backlog_only project never reach REST and
        never WARN; the detail names the mode."""
        conn = _make_conn()
        _seed_project(conn, "buzz", github_repo="example-org/buzz")
        _set_backlog_only(conn, "buzz")
        conn.execute(
            "INSERT INTO items (id, title, project_id, type, status, github_issue) "
            "VALUES (662, 'Historical ref', 2, 'issue', 'done', '#1520')"
        )
        rec = _run_hc(hc_wrong_repo_issues, conn)
        assert _result(rec).result == "PASS"
        assert MODE_NOTE in _result(rec).detail
        assert "buzz" in _result(rec).detail
        assert mock_gh_run.call_count == 0

    @patch("yoke_core.engines.doctor_hc_worktrees._github_auth_configured", return_value=True)
    @patch("yoke_core.engines.doctor_hc_worktrees_gh_repo.resolve_project_github_auth",
           side_effect=lambda project, db_path=None, **_kwargs: _auth(
               "upyoke/yoke" if project == "yoke" else f"example-org/{project}"))
    @patch("yoke_core.engines.doctor_hc_worktrees_gh_repo.issue_view_state")
    def test_enabled_projects_still_scanned_alongside_backlog_only(
        self, mock_gh_run, mock_resolve, mock_avail,
    ):
        """Sync-enabled projects keep full wrong-repo validation while a
        backlog_only sibling is skipped."""
        conn = _make_conn()
        _seed_project(conn, "buzz", github_repo="example-org/buzz")
        _seed_project(conn, "b", github_repo="beebauman/b")
        _set_backlog_only(conn, "buzz")
        conn.execute(
            "INSERT INTO items (id, title, project_id, type, status, github_issue) "
            "VALUES (662, 'Historical ref', 2, 'issue', 'done', '#1520')"
        )
        conn.execute(
            "INSERT INTO items (id, title, project_id, type, status, github_issue) "
            "VALUES (700, 'Live ref', 5, 'issue', 'implementing', '#7')"
        )
        mock_gh_run.return_value = _completed(stdout="OPEN\n")
        rec = _run_hc(hc_wrong_repo_issues, conn)
        assert _result(rec).result == "PASS"
        assert MODE_NOTE in _result(rec).detail
        # Only the enabled project's row reaches the REST lookup.
        assert mock_gh_run.call_count == 1


class TestOrphanedGhIssuesSyncMode:
    @patch("yoke_core.engines.doctor_hc_worktrees._github_auth_configured", return_value=True)
    @patch("yoke_core.engines.doctor_hc_worktrees_gh.resolve_project_github_auth",
           side_effect=lambda project, db_path=None, **_kwargs: _auth(f"example-org/{project}"))
    @patch("yoke_core.engines.doctor_hc_worktrees_gh.list_issues_by_labels_rest")
    def test_backlog_only_repo_not_scanned(
        self, mock_rest, mock_resolve, mock_avail,
    ):
        """A backlog_only project's repo is never fetched, so labeled
        issues there cannot flood the report."""
        conn = _make_conn()
        _seed_project(conn, "yoke", github_repo="upyoke/yoke")
        _set_backlog_only(conn, "yoke")
        rec = _run_hc(hc_orphaned_gh_issues, conn)
        assert _result(rec).result == "PASS"
        assert MODE_NOTE in _result(rec).detail
        assert mock_rest.call_count == 0
        assert mock_resolve.call_count == 0


class TestGhOrphanDetectionSyncMode:
    @patch("yoke_core.engines.doctor_hc_worktrees._github_auth_configured", return_value=True)
    @patch("yoke_core.engines.doctor_hc_worktrees_gh.resolve_project_github_auth",
           side_effect=lambda project, db_path=None, **_kwargs: _auth(f"example-org/{project}"))
    @patch("yoke_core.engines.doctor_hc_worktrees_gh.search_issues_by_query_rest")
    def test_backlog_only_repo_not_searched(
        self, mock_rest, mock_resolve, mock_avail,
    ):
        """A backlog_only project's repo is never searched for [YOK-]
        prefixes; the detail carries the mode-language note."""
        conn = _make_conn()
        _seed_project(conn, "yoke", github_repo="upyoke/yoke")
        _set_backlog_only(conn, "yoke")
        conn.execute(
            "INSERT INTO items (id, title, type, status, github_issue) "
            "VALUES (1, 'Historical ref', 'issue', 'done', '#10')"
        )
        rec = _run_hc(hc_gh_orphan_detection, conn)
        assert _result(rec).result == "PASS"
        assert MODE_NOTE in _result(rec).detail
        assert mock_rest.call_count == 0
        assert mock_resolve.call_count == 0
