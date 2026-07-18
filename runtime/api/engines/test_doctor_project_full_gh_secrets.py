"""Doctor HC tests for ``HC-project-gh-secrets`` (bearer-token REST).

The HC dispatches ``GET /repos/{owner}/{name}/actions/secrets``. Tests
mock the canonical resolver + REST transport rather than the legacy
host-``gh`` probe.
"""

from __future__ import annotations

from unittest.mock import patch

from yoke_contracts.github_app_installation_permissions import (
    GITHUB_SECRETS_READ_PERMISSION_LEVELS,
)
from yoke_core.domain.gh_rest_transport import (
    RestAuthError,
    RestResponse,
)
from yoke_core.domain.project_github_auth import (
    MissingCapability,
    ProjectGithubAuth,
)
from yoke_core.engines.doctor import hc_project_gh_secrets
from runtime.api.engines.test_doctor_project_full import (
    _make_conn,
    _run_hc,
    _seed_project,
)


def _auth(project: str = "externalwebapp", repo: str = "org/externalwebapp") -> ProjectGithubAuth:
    return ProjectGithubAuth(
        project=project, repo=repo, token="t",
    )


class TestProjectGhSecrets:
    def test_skips_when_github_auth_unavailable(self):
        """When the project GitHub App auth is unavailable, SKIP with canonical reason."""
        conn = _make_conn()
        _seed_project(conn, "externalwebapp", github_repo="org/externalwebapp")
        with patch(
            "yoke_core.engines.doctor_hc_worktrees_gh_project.resolve_project_github_auth",
            side_effect=MissingCapability("externalwebapp", "no capability"),
        ):
            rec = _run_hc(hc_project_gh_secrets, conn)
        assert rec.results[0].result == "SKIP"
        assert "GitHub App repo binding is not available" in rec.results[0].detail

    def test_passes_when_secrets_found(self):
        conn = _make_conn()
        _seed_project(conn, "externalwebapp", github_repo="org/externalwebapp")
        with patch(
            "yoke_core.engines.doctor_hc_worktrees_gh_project.resolve_project_github_auth",
            return_value=_auth("externalwebapp", "org/externalwebapp"),
        ) as resolver, patch(
            "yoke_core.engines.doctor_hc_worktrees_gh_project.request_with_retry",
            return_value=RestResponse(
                status=200, headers={},
                body={"total_count": 2, "secrets": [{"name": "A"}, {"name": "B"}]},
            ),
        ):
            rec = _run_hc(hc_project_gh_secrets, conn)
        assert rec.results[0].result == "PASS"
        assert "2 secrets" in rec.results[0].detail
        assert (
            resolver.call_args.kwargs["required_permissions"]
            is GITHUB_SECRETS_READ_PERMISSION_LEVELS
        )

    def test_warns_when_no_secrets_found(self):
        conn = _make_conn()
        _seed_project(conn, "externalwebapp", github_repo="org/externalwebapp")
        with patch(
            "yoke_core.engines.doctor_hc_worktrees_gh_project.resolve_project_github_auth",
            return_value=_auth("externalwebapp", "org/externalwebapp"),
        ), patch(
            "yoke_core.engines.doctor_hc_worktrees_gh_project.request_with_retry",
            return_value=RestResponse(
                status=200, headers={}, body={"total_count": 0, "secrets": []},
            ),
        ):
            rec = _run_hc(hc_project_gh_secrets, conn)
        assert rec.results[0].result == "WARN"

    def test_skips_on_rest_auth_error(self):
        """REST 401/403 -> SKIP with canonical reason (operator UX parity)."""
        conn = _make_conn()
        _seed_project(conn, "externalwebapp", github_repo="org/externalwebapp")
        with patch(
            "yoke_core.engines.doctor_hc_worktrees_gh_project.resolve_project_github_auth",
            return_value=_auth("externalwebapp", "org/externalwebapp"),
        ), patch(
            "yoke_core.engines.doctor_hc_worktrees_gh_project.request_with_retry",
            side_effect=RestAuthError("HTTP 403: insufficient scope", status=403),
        ):
            rec = _run_hc(hc_project_gh_secrets, conn)
        assert rec.results[0].result == "SKIP"
        assert "GitHub App repo binding is not available" in rec.results[0].detail

    def test_runs_for_yoke(self):
        """Yoke is a first-class GitHub project; secrets HC runs as normal."""
        conn = _make_conn()
        _seed_project(conn, "yoke", github_repo="upyoke/yoke")
        with patch(
            "yoke_core.engines.doctor_hc_worktrees_gh_project.resolve_project_github_auth",
            return_value=_auth("yoke", "upyoke/yoke"),
        ), patch(
            "yoke_core.engines.doctor_hc_worktrees_gh_project.request_with_retry",
            return_value=RestResponse(
                status=200, headers={},
                body={"total_count": 2, "secrets": [{"name": "A"}, {"name": "B"}]},
            ),
        ):
            rec = _run_hc(hc_project_gh_secrets, conn, project="yoke")
        assert rec.results[0].result == "PASS"
        assert "upyoke/yoke" in rec.results[0].detail

    def test_uses_verified_binding_repo_not_project_projection(self):
        conn = _make_conn()
        _seed_project(conn, "externalwebapp", github_repo="stale-owner/stale-repo")
        with patch(
            "yoke_core.engines.doctor_hc_worktrees_gh_project."
            "resolve_project_github_auth",
            return_value=_auth("externalwebapp", "verified-owner/verified-repo"),
        ), patch(
            "yoke_core.engines.doctor_hc_worktrees_gh_project.request_with_retry",
            return_value=RestResponse(
                status=200, headers={}, body={"total_count": 1, "secrets": []},
            ),
        ) as request:
            rec = _run_hc(hc_project_gh_secrets, conn)

        assert rec.results[0].result == "PASS"
        assert request.call_args.args[0].path == (
            "/repos/verified-owner/verified-repo/actions/secrets"
        )
