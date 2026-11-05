"""Tests for GitHub-dependent doctor HCs and HC registration.

Git-state HCs live in test_doctor_git.py.
Worktree/filesystem/stale-branch HCs live in test_doctor_git_worktrees.py.

Tests use mock subprocess to avoid real gh calls.
"""

from __future__ import annotations

from runtime.api.engines.doctor_git_github_test_support import (
    _make_completed as _make_completed,
    _make_conn as _make_conn,
    _self_project_is_yoke as _self_project_is_yoke,
)


import json
from unittest.mock import patch

from yoke_contracts.github_app_installation_permissions import (
    GITHUB_ISSUES_READ_PERMISSION_LEVELS,
)
from yoke_core.engines._project_identity_test_helpers import (
    _insert_item,
    _seed_project,
)
from yoke_core.engines.doctor import (
    DoctorArgs,
    RecordCollector,
    hc_gh_orphan_detection,
    hc_orphaned_gh_issues,
    hc_wrong_repo_issues,
)


def _args(**kw) -> DoctorArgs:
    kw.setdefault("project", "yoke")
    return DoctorArgs(**kw)


def _run_hc(fn, conn=None, **kw):
    """Run a single HC and return the RecordCollector."""
    owns_conn = conn is None
    if owns_conn:
        conn = _make_conn()
    rec = RecordCollector()
    try:
        fn(conn, _args(**kw), rec)
    finally:
        if owns_conn:
            conn.close()
    return rec


def _auth(repo: str = "upyoke/yoke"):
    """Build a ProjectGithubAuth stub for resolver patches."""
    from yoke_core.domain.project_github_auth import ProjectGithubAuth

    return ProjectGithubAuth(project="yoke", repo=repo, token="t")


def _auth_for_project(project: str, **_kwargs):
    repo = "upyoke/yoke" if project == "yoke" else f"example-org/{project}"
    return _auth(repo)


class TestHcOrphanedGhIssues:
    """Tests for hc_orphaned_gh_issues."""

    @patch(
        "yoke_core.engines.doctor_hc_worktrees._github_auth_configured",
        return_value=False,
    )
    def test_no_github_auth_skips(self, mock_gh):
        rec = _run_hc(hc_orphaned_gh_issues)
        assert rec.results[0].result == "SKIP"
        assert "GitHub App repo binding is not available" in rec.results[0].detail

    @patch(
        "yoke_core.engines.doctor_hc_worktrees._github_auth_configured",
        return_value=True,
    )
    @patch(
        "yoke_core.engines.doctor_hc_worktrees_gh_labels.resolve_project_github_auth",
        side_effect=lambda project, db_path=None, **_kwargs: _auth(),
    )
    @patch("yoke_core.engines.doctor_hc_worktrees_gh_labels.list_issues_by_labels_rest")
    def test_no_orphans_passes(self, mock_rest, mock_resolve, mock_avail):
        conn = _make_conn()
        _seed_project(conn, "yoke", github_repo="upyoke/yoke")
        conn.execute(
            "INSERT INTO items (id, title, workflow_id, workflow_version_id, status, github_issue) "
            "VALUES (1, 'Test', 'issue', (SELECT current_version_id FROM workflows WHERE id='issue'), 'idea', '#100')"
        )
        mock_rest.return_value = _make_completed(stdout="100\n")
        rec = _run_hc(hc_orphaned_gh_issues, conn)
        assert rec.results[0].result == "PASS"
        assert (
            mock_resolve.call_args.kwargs["required_permissions"]
            is GITHUB_ISSUES_READ_PERMISSION_LEVELS
        )


class TestHcGhOrphanDetection:
    """Tests for hc_gh_orphan_detection."""

    @patch(
        "yoke_core.engines.doctor_hc_worktrees._github_auth_configured",
        return_value=False,
    )
    def test_no_github_auth_skips(self, mock_gh):
        rec = _run_hc(hc_gh_orphan_detection)
        assert rec.results[0].result == "SKIP"
        assert "GitHub App repo binding is not available" in rec.results[0].detail

    @patch(
        "yoke_core.engines.doctor_hc_worktrees._github_auth_configured",
        return_value=True,
    )
    @patch(
        "yoke_core.engines.doctor_hc_worktrees_gh.resolve_project_github_auth",
        side_effect=lambda project, db_path=None, **_kwargs: _auth(),
    )
    @patch("yoke_core.engines.doctor_hc_worktrees_gh.search_issues_by_query_rest")
    def test_orphan_detected_warns(self, mock_rest, mock_resolve, mock_avail):
        conn = _make_conn()
        _seed_project(conn, "yoke", github_repo="upyoke/yoke")
        gh_json = json.dumps(
            [{"number": 999, "title": "[YOK-999] orphan", "state": "OPEN"}]
        )
        mock_rest.return_value = _make_completed(stdout=gh_json)
        rec = _run_hc(hc_gh_orphan_detection, conn)
        assert rec.results[0].result == "WARN"
        assert "#999" in rec.results[0].detail
        assert (
            mock_resolve.call_args.kwargs["required_permissions"]
            is GITHUB_ISSUES_READ_PERMISSION_LEVELS
        )
        assert mock_rest.call_args.kwargs["search"] == "[YOK- is:issue"

    @patch(
        "yoke_core.engines.doctor_hc_worktrees._github_auth_configured",
        return_value=True,
    )
    @patch(
        "yoke_core.engines.doctor_hc_worktrees_gh.resolve_project_github_auth",
        side_effect=lambda project, db_path=None, **_kwargs: _auth(),
    )
    @patch("yoke_core.engines.doctor_hc_worktrees_gh.search_issues_by_query_rest")
    def test_search_failure_warns(self, mock_rest, mock_resolve, mock_avail):
        conn = _make_conn()
        _seed_project(conn, "yoke", github_repo="upyoke/yoke")
        mock_rest.return_value = _make_completed(returncode=1)

        rec = _run_hc(hc_gh_orphan_detection, conn)

        assert rec.results[0].result == "WARN"
        assert "search unreadable" in rec.results[0].detail
        assert "Issues read access" in rec.results[0].detail
        assert "retry" in rec.results[0].detail


class TestHcWrongRepoIssues:
    """Tests for hc_wrong_repo_issues."""

    @patch(
        "yoke_core.engines.doctor_hc_worktrees._github_auth_configured",
        return_value=False,
    )
    def test_no_github_auth_skips(self, mock_gh):
        rec = _run_hc(hc_wrong_repo_issues)
        assert rec.results[0].result == "SKIP"
        assert "GitHub App repo binding is not available" in rec.results[0].detail

    @patch(
        "yoke_core.engines.doctor_hc_worktrees._github_auth_configured",
        return_value=True,
    )
    @patch(
        "yoke_core.engines.doctor_hc_worktrees_gh_repo.resolve_project_github_auth",
        side_effect=_auth_for_project,
    )
    @patch("yoke_core.engines.doctor_hc_worktrees_gh_repo.repository_issue_states")
    def test_issue_in_correct_repo_passes(self, mock_gh_run, mock_resolve, mock_avail):
        conn = _make_conn()
        _seed_project(conn, "externalwebapp", github_repo="example-org/externalwebapp")
        _insert_item(
            conn,
            42,
            "ExternalWebapp item",
            project="externalwebapp",
            workflow_id="issue",
            status="idea",
            github_issue="#100",
        )
        mock_gh_run.return_value = {"100": "OPEN"}
        rec = _run_hc(hc_wrong_repo_issues, conn)
        assert rec.results[0].result == "PASS"

    @patch(
        "yoke_core.engines.doctor_hc_worktrees._github_auth_configured",
        return_value=True,
    )
    @patch(
        "yoke_core.engines.doctor_hc_worktrees_gh_repo.resolve_project_github_auth",
        side_effect=_auth_for_project,
    )
    @patch("yoke_core.engines.doctor_hc_worktrees_gh_repo.repository_issue_states")
    def test_issue_in_wrong_repo_warns(self, mock_gh_run, mock_resolve, mock_avail):
        conn = _make_conn()
        _seed_project(conn, "externalwebapp", github_repo="example-org/externalwebapp")
        _insert_item(
            conn,
            42,
            "ExternalWebapp item",
            project="externalwebapp",
            workflow_id="issue",
            status="idea",
            github_issue="#100",
        )
        mock_gh_run.side_effect = [
            {},  # not in externalwebapp repo
            {"100": "OPEN"},  # found in yoke repo
        ]
        rec = _run_hc(hc_wrong_repo_issues, conn)
        assert rec.results[0].result == "WARN"
        assert "wrong repo" in rec.results[0].detail.lower()
