"""Resync engine: fail-closed GitHub-auth regressions (bearer-token REST).

Covers the canonical-resolver propagation chain end-to-end:

- ``_call_domain_sync`` propagates
  :class:`ProjectGithubAuthError` from
  :func:`yoke_core.domain.project_github_auth.resolve_project_github_auth`.
- ``_fetch_gh_issues_per_project`` re-raises for Yoke (the control plane)
  and records explicit unavailable state for other projects.
- ``stage1_linkage`` does not manufacture orphans for unavailable projects.
- The patch-friendly wrappers in :mod:`resync_wrappers` do not swallow.

Yoke does NOT use the ``gh`` CLI; all GitHub access is bearer-token REST.
"""

# Imported pytest fixtures intentionally share names with test parameters.
# ruff: noqa: F811

from __future__ import annotations

from unittest import mock

import pytest

import yoke_core.engines.resync as resync_mod
from yoke_core.domain.gh_rest_transport import (
    RestNetworkError,
    RestResponse,
)
from yoke_core.domain.project_github_auth import (
    MissingCapability,
    MissingRepoBinding,
    ProjectGithubAuth,
    TransportFailure,
)

from yoke_core.engines._resync_test_helpers import (
    populated_db,  # noqa: F401 — imported pytest fixture
    test_db,  # noqa: F401 — imported pytest fixture
)


def _fake_auth(token: str = "test-token", project: str = "yoke") -> ProjectGithubAuth:
    """Build a ProjectGithubAuth for tests without touching the real DB."""
    return ProjectGithubAuth(
        project=project,
        repo=f"org/{project}",
        token=token,
    )


class TestCallDomainSyncFailClosed:
    def test_call_domain_sync_resolves_project_before_call(self):
        called = False
        def fake_func(*args, **kwargs):
            nonlocal called
            called = True
            return 0

        with mock.patch(
            "yoke_core.engines.resync_runtime.resolve_project_github_auth",
            return_value=_fake_auth("new-token", "buzz"),
        ) as resolver:
            assert resync_mod._call_domain_sync(
                fake_func, "42", project="buzz",
            ) is True
        resolver.assert_called_once_with("buzz")
        assert called is True

    def test_call_domain_sync_reports_exception(self, capsys):
        def boom(*args, **kwargs):
            raise RuntimeError("boom")

        with mock.patch(
            "yoke_core.engines.resync_runtime.resolve_project_github_auth",
            return_value=_fake_auth("tmp", "buzz"),
        ):
            assert resync_mod._call_domain_sync(boom, project="buzz") is False
        captured = capsys.readouterr()
        assert "reason: boom failed: RuntimeError: boom" in captured.err

    def test_call_domain_sync_forwards_helper_stderr(self, capsys):
        def helper(*args, **kwargs):
            print("typed REST said nope", file=kwargs["stderr"])
            return 1

        with mock.patch(
            "yoke_core.engines.resync_runtime.resolve_project_github_auth",
            return_value=_fake_auth("tmp", "buzz"),
        ):
            assert resync_mod._call_domain_sync(helper, project="buzz") is False
        captured = capsys.readouterr()
        assert "reason: helper failed: typed REST said nope" in captured.err

    def test_call_domain_sync_propagates_missing_binding(self):
        """:class:`ProjectGithubAuthError` propagates out of _call_domain_sync."""
        def never_called(*args, **kwargs):  # pragma: no cover - asserts call shape
            raise AssertionError("should not be called when auth fails")

        with mock.patch(
            "yoke_core.engines.resync_runtime.resolve_project_github_auth",
            side_effect=MissingRepoBinding("buzz", "repository is not bound"),
        ):
            with pytest.raises(MissingRepoBinding):
                resync_mod._call_domain_sync(never_called, project="buzz")


def _yoke_one_issue_response() -> RestResponse:
    return RestResponse(
        status=200, headers={},
        body=[{"number": 1, "title": "[YOK-1] ok", "labels": [],
               "state": "OPEN", "body": ""}],
    )


class TestFetchGhIssuesPerProjectFailClosed:
    def test_records_per_project_auth_failure_sentinel(self):
        """Non-Yoke auth failure becomes explicit unavailable state."""
        def fake_resolve(project, *args, **kwargs):
            if project == "yoke":
                return _fake_auth()
            raise MissingRepoBinding(project, f"repository is not bound for '{project}'")

        with mock.patch(
            "yoke_core.engines.resync_detect_fetch.resolve_project_github_auth",
            side_effect=fake_resolve,
        ), mock.patch(
            "yoke_core.engines.resync_detect_fetch.request_with_retry",
            return_value=_yoke_one_issue_response(),
        ):
            result = resync_mod._fetch_gh_issues_per_project(
                {"yoke", "buzz"},
            )

        assert result["yoke"][1]["title"] == "[YOK-1] ok"
        assert result["buzz"]["_github_unavailable"] == "true"
        assert result["buzz"]["_unavailable_code"] == "missing_repo_binding"
        assert "github-binding bind" in result["buzz"]["_repair_hint"]

    def test_reraises_yoke_auth_failure(self):
        """Yoke is the control plane -- its auth failure must propagate."""
        with mock.patch(
            "yoke_core.engines.resync_detect_fetch.resolve_project_github_auth",
            side_effect=MissingCapability("yoke", "no yoke capability"),
        ):
            with pytest.raises(MissingCapability):
                resync_mod._fetch_gh_issues_per_project(
                    {"yoke", "buzz"},
                )

    def test_non_yoke_transport_failure_is_explicit_unavailable_state(self):
        def fake_resolve(project, *args, **kwargs):
            return _fake_auth(project=project)

        with mock.patch(
            "yoke_core.engines.resync_detect_fetch.resolve_project_github_auth",
            side_effect=fake_resolve,
        ), mock.patch(
            "yoke_core.engines.resync_detect_fetch.request_with_retry",
            side_effect=[
                _yoke_one_issue_response(),
                RestNetworkError("network down"),
            ],
        ):
            result = resync_mod._fetch_gh_issues_per_project(
                {"yoke", "buzz"},
            )

        assert result["buzz"]["_github_unavailable"] == "true"
        assert result["buzz"]["_unavailable_code"] == "transport_failure"
        assert result["buzz"]["_unavailable_stage"] == "issues"
        assert result["buzz"] != {}

    def test_yoke_transport_failure_becomes_typed_control_plane_error(self):
        with mock.patch(
            "yoke_core.engines.resync_detect_fetch.resolve_project_github_auth",
            return_value=_fake_auth(),
        ), mock.patch(
            "yoke_core.engines.resync_detect_fetch.request_with_retry",
            side_effect=RestNetworkError("network down"),
        ):
            with pytest.raises(TransportFailure):
                resync_mod._fetch_gh_issues_per_project({"yoke"})


class TestStage1LinkageAuthSentinel:
    def test_skips_auth_failed_projects(self, populated_db, tmp_path):
        """Stage 1 must NOT manufacture orphans for projects whose fetch failed."""
        yoke_root = tmp_path / "state"
        (yoke_root / "backlog").mkdir(parents=True)
        gh_map = {
            "yoke": {
                100: {"number": 100, "title": "[YOK-42] Test item", "labels": [], "state": "OPEN", "body": ""},
            },
            # buzz auth failed -- sentinel instead of issues map.
            "buzz": {
                "_github_unavailable": "true",
                "_unavailable_code": "missing_repo_binding",
                "_unavailable_stage": "issues",
                "_repair_hint": "bind the repository",
            },
        }
        with mock.patch(
            "yoke_core.engines.resync._fetch_gh_issues_per_project",
            return_value=gh_map,
        ):
            paired, local_orphans, gh_orphans, gh_by_project = resync_mod.stage1_linkage(
                populated_db, str(yoke_root),
            )

        non_yoke_local_orphans = [o for o in local_orphans if o[3] not in ("yoke", "")]
        assert non_yoke_local_orphans == []
        assert gh_by_project["buzz"]["_unavailable_code"] == "missing_repo_binding"

    def test_skips_transport_unavailable_projects(self, populated_db, tmp_path):
        yoke_root = tmp_path / "state"
        (yoke_root / "backlog").mkdir(parents=True)
        unavailable = {
            "_github_unavailable": "true",
            "_unavailable_code": "transport_failure",
            "_unavailable_stage": "issues",
            "_repair_hint": "retry network access",
        }
        with mock.patch(
            "yoke_core.engines.resync._fetch_gh_issues_per_project",
            return_value={"yoke": {}, "buzz": unavailable},
        ):
            _, local_orphans, gh_orphans, _ = resync_mod.stage1_linkage(
                populated_db, str(yoke_root),
            )

        assert [entry for entry in local_orphans if entry[3] == "buzz"] == []
        assert [entry for entry in gh_orphans if entry[3] == "buzz"] == []

    def test_missing_fetch_result_is_unavailable_not_empty_state(
        self, populated_db, tmp_path,
    ):
        yoke_root = tmp_path / "state"
        (yoke_root / "backlog").mkdir(parents=True)
        with mock.patch(
            "yoke_core.engines.resync._fetch_gh_issues_per_project",
            return_value={},
        ):
            paired, local_orphans, gh_orphans, states = (
                resync_mod.stage1_linkage(populated_db, str(yoke_root))
            )

        assert paired == []
        assert local_orphans == []
        assert gh_orphans == []
        assert states["yoke"]["_github_unavailable"] == "true"
        assert states["yoke"]["_unavailable_code"] == "transport_failure"
