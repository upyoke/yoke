"""Doctor HC tests for wrong-repo and orphaned-active-items checks.

Delegated-sync and gh-orphan-detection tests live in test_doctor_hc_git_full.py.
Worktree-health/stale-remote-branches tests live in test_doctor_hc_git_full_worktree.py.
Orphaned-gh-issues tests live in test_doctor_hc_git_full_orphans.py.

Schema scaffolding is shared via _doctor_hc_git_test_helpers (private module).
"""

from __future__ import annotations

from unittest.mock import patch

from yoke_contracts.github_app_installation_permissions import (
    GITHUB_ISSUES_READ_PERMISSION_LEVELS,
    GITHUB_ISSUES_WRITE_PERMISSION_LEVELS,
)
from yoke_core.engines._doctor_hc_git_test_helpers import (
    _completed,
    _insert_item,
    _make_conn,
    _result,
    _run_hc,
    _seed_project,
)
from yoke_core.engines.doctor import (
    hc_wrong_repo_issues,
)


class TestWrongRepoIssues:
    """Tests for hc_wrong_repo_issues."""

    @patch(
        "yoke_core.engines.doctor_hc_worktrees._github_auth_configured",
        return_value=False,
    )
    def test_no_github_auth_skips(self, mock_gh):
        """T6: SKIPs with canonical reason when project GitHub App auth is unavailable."""
        rec = _run_hc(hc_wrong_repo_issues)
        assert _result(rec).result == "SKIP"
        assert "GitHub App repo binding is not available" in _result(rec).detail

    @patch(
        "yoke_core.engines.doctor_hc_worktrees._github_auth_configured",
        return_value=True,
    )
    @patch(
        "yoke_core.engines.doctor_hc_worktrees_gh_repo.resolve_project_github_auth",
        side_effect=lambda project, db_path=None, **_kwargs: _auth(
            "upyoke/yoke" if project == "yoke" else f"example-org/{project}"
        ),
    )
    @patch("yoke_core.engines.doctor_hc_worktrees_gh_repo.issue_view_state")
    def test_issue_in_correct_repo(self, mock_gh_run, mock_resolve, mock_avail):
        """T4: PASS when issue is in correct repo."""
        conn = _make_conn()
        _seed_project(conn, "externalwebapp", github_repo="example-org/externalwebapp")
        _insert_item(
            conn,
            42,
            "ExternalWebapp item",
            project="externalwebapp",
            workflow_id="issue",
            status="implementing",
            github_issue="#100",
        )
        mock_gh_run.return_value = _completed(stdout="OPEN\n")
        rec = _run_hc(hc_wrong_repo_issues, conn)
        assert _result(rec).result == "PASS"

    @patch(
        "yoke_core.engines.doctor_hc_worktrees._github_auth_configured",
        return_value=True,
    )
    @patch(
        "yoke_core.engines.doctor_hc_worktrees_gh_repo.resolve_project_github_auth",
        side_effect=lambda project, db_path=None, **_kwargs: _auth(
            "upyoke/yoke" if project == "yoke" else f"example-org/{project}"
        ),
    )
    @patch("yoke_core.engines.doctor_hc_worktrees_gh_repo.issue_view_state")
    def test_issue_in_wrong_repo(self, mock_gh_run, mock_resolve, mock_avail):
        """T3: Detects wrong-repo (externalwebapp item in yoke repo)."""
        conn = _make_conn()
        _seed_project(conn, "externalwebapp", github_repo="example-org/externalwebapp")
        _insert_item(
            conn,
            662,
            "ExternalWebapp wrong repo",
            project="externalwebapp",
            workflow_id="issue",
            status="implementing",
            github_issue="#1520",
        )
        # Not found in target repo, found in yoke repo
        mock_gh_run.side_effect = [
            _completed(returncode=1, stdout=""),
            _completed(stdout="OPEN\n"),
        ]
        rec = _run_hc(hc_wrong_repo_issues, conn)
        assert _result(rec).result == "WARN"
        assert "YOK-662" in _result(rec).detail
        assert "wrong" in _result(rec).detail.lower() or "Wrong" in _result(rec).detail

    @patch(
        "yoke_core.engines.doctor_hc_worktrees._github_auth_configured",
        return_value=True,
    )
    @patch(
        "yoke_core.engines.doctor_hc_worktrees_gh_repo.resolve_project_github_auth",
        side_effect=lambda project, db_path=None, **_kwargs: _auth("upyoke/yoke"),
    )
    @patch("yoke_core.engines.doctor_hc_worktrees_gh_repo.issue_view_state")
    def test_yoke_only_items_skipped(self, mock_gh_run, mock_resolve, mock_avail):
        """T5: Same-repo Yoke rows are filtered before any REST call.

        Includes a real ``projects`` row for ``yoke`` so the row passes
        the JOIN; the same-repo filter (target_repo == resolved Yoke
        repo) keeps ``issue_view_state`` from firing.
        """
        conn = _make_conn()
        _seed_project(conn, "yoke", github_repo="upyoke/yoke")
        _insert_item(
            conn,
            100,
            "Yoke item",
            workflow_id="issue",
            status="implementing",
            github_issue="#100",
        )
        rec = _run_hc(hc_wrong_repo_issues, conn)
        assert _result(rec).result == "PASS"
        # Same-repo skip must short-circuit BEFORE the REST lookup.
        assert mock_gh_run.call_count == 0

    @patch(
        "yoke_core.engines.doctor_hc_worktrees._github_auth_configured",
        return_value=True,
    )
    @patch(
        "yoke_core.engines.doctor_hc_worktrees_gh_repo.resolve_project_github_auth",
        side_effect=lambda project, db_path=None, **_kwargs: _auth(
            "upyoke/yoke" if project == "yoke" else f"example-org/{project}"
        ),
    )
    @patch("yoke_core.engines.doctor_hc_worktrees_gh_repo.issue_view_state")
    def test_auth_resolved_once_per_distinct_project(
        self, mock_gh_run, mock_resolve, mock_avail
    ):
        """``resolve_project_github_auth`` runs at most once per distinct project.

        Mixes multiple Yoke rows (same-repo, skipped before REST) with
        multiple ExternalWebapp rows (external, REST-bound) and asserts the
        resolver call count equals the number of distinct projects.
        """
        conn = _make_conn()
        _seed_project(conn, "yoke", github_repo="upyoke/yoke")
        _seed_project(conn, "externalwebapp", github_repo="example-org/externalwebapp")
        for i in range(3):
            _insert_item(
                conn,
                200 + i,
                "Yoke item",
                workflow_id="issue",
                status="implementing",
                github_issue=f"#{300 + i}",
            )
        for i in range(4):
            _insert_item(
                conn,
                400 + i,
                "ExternalWebapp item",
                project="externalwebapp",
                workflow_id="issue",
                status="implementing",
                github_issue=f"#{500 + i}",
            )
        mock_gh_run.return_value = _completed(stdout="OPEN\n")
        rec = _run_hc(hc_wrong_repo_issues, conn)

        assert _result(rec).result == "PASS"
        # Yoke resolves once for the upfront yoke_auth lookup; externalwebapp
        # resolves once for the in-loop cache. Yoke rows are skipped
        # before the in-loop resolve fires.
        resolved_projects = [c.args[0] for c in mock_resolve.call_args_list]
        assert resolved_projects.count("yoke") == 1
        assert resolved_projects.count("externalwebapp") == 1
        assert all(
            call.kwargs["required_permissions"] is GITHUB_ISSUES_READ_PERMISSION_LEVELS
            for call in mock_resolve.call_args_list
        )
        # Only the 4 externalwebapp rows reach the REST call — yoke rows skip.
        assert mock_gh_run.call_count == 4

    @patch(
        "yoke_core.engines.doctor_hc_worktrees._github_auth_configured",
        return_value=True,
    )
    @patch(
        "yoke_core.engines.doctor_hc_worktrees_gh_repo.resolve_project_github_auth",
        side_effect=lambda project, db_path=None, **_kwargs: _auth(
            "upyoke/yoke" if project == "yoke" else f"example-org/{project}"
        ),
    )
    @patch("yoke_core.engines.doctor_hc_worktrees_gh_repo.issue_view_state")
    def test_per_project_iteration(self, mock_gh_run, mock_resolve, mock_avail):
        """T1/T2: HC fetches issues from multiple project repos."""
        conn = _make_conn()
        _seed_project(conn, "externalwebapp", github_repo="example-org/externalwebapp")
        _insert_item(
            conn,
            100,
            "Yoke item",
            workflow_id="issue",
            status="implementing",
            github_issue="#100",
        )
        _insert_item(
            conn,
            200,
            "ExternalWebapp item",
            project="externalwebapp",
            workflow_id="issue",
            status="implementing",
            github_issue="#50",
        )
        # Issue found in target repo for externalwebapp
        mock_gh_run.return_value = _completed(stdout="OPEN\n")
        rec = _run_hc(hc_wrong_repo_issues, conn)
        assert _result(rec).result == "PASS"

    @patch(
        "yoke_core.engines.doctor_hc_worktrees._github_auth_configured",
        return_value=True,
    )
    @patch(
        "yoke_core.engines.doctor_hc_worktrees_gh_repo.resolve_project_github_auth",
        side_effect=lambda project, db_path=None, **_kwargs: _auth(
            "upyoke/yoke" if project == "yoke" else "verified-org/externalwebapp"
        ),
    )
    @patch("yoke_core.engines.doctor_hc_worktrees_gh_repo.issue_view_state")
    def test_verified_binding_overrides_stale_project_projection(
        self,
        mock_issue,
        mock_resolve,
        mock_available,
    ):
        conn = _make_conn()
        _seed_project(conn, "externalwebapp", github_repo="stale-org/stale-repo")
        _insert_item(
            conn,
            701,
            "ExternalWebapp item",
            project="externalwebapp",
            workflow_id="issue",
            status="implementing",
            github_issue="#91",
        )
        mock_issue.return_value = _completed(stdout="OPEN\n")

        rec = _run_hc(hc_wrong_repo_issues, conn)

        assert _result(rec).result == "PASS"
        assert mock_issue.call_args.kwargs["repo"] == "verified-org/externalwebapp"

    @patch(
        "yoke_core.engines.doctor_hc_worktrees._github_auth_configured",
        return_value=True,
    )
    @patch(
        "yoke_core.engines.doctor_hc_worktrees_gh_repo.resolve_project_github_auth",
        return_value=None,
    )
    def test_fix_mode_requests_issues_write(self, mock_resolve, mock_available):
        mock_resolve.return_value = _auth("upyoke/yoke")

        rec = _run_hc(hc_wrong_repo_issues, fix=True)

        assert _result(rec).result == "PASS"
        assert (
            mock_resolve.call_args.kwargs["required_permissions"]
            is GITHUB_ISSUES_WRITE_PERMISSION_LEVELS
        )


def _auth(repo: str):
    """Build a ProjectGithubAuth stub for resolver patches."""
    from yoke_core.domain.project_github_auth import ProjectGithubAuth

    return ProjectGithubAuth(project="yoke", repo=repo, token="t")
