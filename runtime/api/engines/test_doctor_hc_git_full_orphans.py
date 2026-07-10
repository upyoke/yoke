"""Doctor HC tests for orphaned-gh-issues check.

Delegated-sync and gh-orphan-detection tests live in test_doctor_hc_git_full.py.
Wrong-repo/orphaned-active-items tests live in test_doctor_hc_git_full_repos.py.
Worktree-health/stale-remote-branches tests live in test_doctor_hc_git_full_worktree.py.

Schema scaffolding is shared via _doctor_hc_git_test_helpers (private module).
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
from yoke_core.engines.doctor import hc_orphaned_gh_issues


class TestOrphanedGhIssues:
    """Tests for hc_orphaned_gh_issues."""

    @patch("yoke_core.engines.doctor_hc_worktrees._github_auth_configured", return_value=False)
    def test_no_github_auth_skips(self, mock_gh):
        rec = _run_hc(hc_orphaned_gh_issues)
        assert _result(rec).result == "SKIP"
        assert "GitHub App repo binding is not available" in _result(rec).detail

    @patch("yoke_core.engines.doctor_hc_worktrees._github_auth_configured", return_value=True)
    @patch("yoke_core.engines.doctor_hc_worktrees_gh.resolve_project_github_auth",
           side_effect=lambda project, db_path=None, **_kwargs: _auth("upyoke/yoke"))
    @patch("yoke_core.engines.doctor_hc_worktrees_gh.list_issues_by_labels_rest")
    def test_no_orphans_passes(self, mock_rest, mock_resolve, mock_avail):
        conn = _make_conn()
        _seed_project(conn, "yoke", github_repo="upyoke/yoke")
        conn.execute(
            "INSERT INTO items (id, title, type, status, github_issue) "
            "VALUES (1, 'Test', 'issue', 'implementing', '#100')"
        )
        mock_rest.return_value = _completed(stdout="100\n")
        rec = _run_hc(hc_orphaned_gh_issues, conn)
        assert _result(rec).result == "PASS"

    @patch("yoke_core.engines.doctor_hc_worktrees._github_auth_configured", return_value=True)
    @patch("yoke_core.engines.doctor_hc_worktrees_gh.list_issues_by_labels_rest")
    def test_uses_dynamic_yoke_repo(self, mock_rest, mock_avail):
        """AC-3: Yoke repo is resolved via canonical resolver — not a
        hard-coded ``upyoke/yoke`` literal.

        Patch the resolver to return a custom repo string and assert the
        REST helper receives the split (owner, name) pair.
        """
        captured: list[dict] = []

        def _capture(*, owner, name, token, labels, state="open"):
            captured.append({"owner": owner, "name": name})
            return _completed(stdout="")

        mock_rest.side_effect = _capture

        conn = _make_conn()
        _seed_project(conn, "yoke", github_repo="custom/owner-repo")
        with patch(
            "yoke_core.engines.doctor_hc_worktrees_gh.resolve_project_github_auth",
            side_effect=lambda project, db_path=None, **_kwargs: _auth("custom/owner-repo"),
        ):
            _run_hc(hc_orphaned_gh_issues, conn)

        assert captured, "expected at least one REST invocation"
        for call in captured:
            assert call["owner"] == "custom"
            assert call["name"] == "owner-repo"


def _auth(repo: str):
    """Build a ProjectGithubAuth stub for resolver patches."""
    from yoke_core.domain.project_github_auth import ProjectGithubAuth
    return ProjectGithubAuth(project="yoke", repo=repo, token="t")
