"""Resync engine: fail-closed GitHub-auth regressions (bearer-token REST).

Covers the canonical-resolver propagation chain end-to-end:

- ``_gh_env`` / ``_call_domain_sync`` propagate
  :class:`ProjectGithubAuthError` from
  :func:`yoke_core.domain.project_github_auth.resolve_project_github_auth`.
- ``_fetch_gh_issues_per_project`` re-raises for Yoke (the control plane)
  and records the typed-failure sentinel for other projects.
- ``stage1_linkage`` does not manufacture orphans for projects whose
  per-project value is the ``_auth_error`` sentinel.
- The patch-friendly wrappers in :mod:`resync_wrappers` do not swallow.
- The top-level engine surface (``resync.main``) exits non-zero with a
  warning when one project fails auth and continues with healthy projects.

Yoke does NOT use the ``gh`` CLI; all GitHub access is bearer-token REST.
"""

from __future__ import annotations

from unittest import mock

import pytest

import yoke_core.engines.resync as resync_mod
from yoke_core.domain.gh_rest_transport import RestResponse
from yoke_core.domain.project_github_auth import (
    MissingCapability,
    MissingToken,
    ProjectGithubAuth,
)
from runtime.api.fixtures.file_test_db import connect_test_db

from yoke_core.engines._resync_test_helpers import (
    populated_db,
    test_db,
)


def _fake_auth(token: str = "test-token", project: str = "yoke") -> ProjectGithubAuth:
    """Build a ProjectGithubAuth for tests without touching the real DB."""
    return ProjectGithubAuth(
        project=project,
        repo=f"org/{project}",
        token=token,
        env={"GH_TOKEN": token},
    )


class TestGhEnvFailClosed:
    def test_gh_env_routes_through_canonical_resolver(self):
        with mock.patch(
            "yoke_core.engines.resync_runtime.resolve_project_github_auth",
            return_value=_fake_auth("abc", "buzz"),
        ):
            env = resync_mod._gh_env("buzz")
        assert env["GH_TOKEN"] == "abc"

    def test_gh_env_propagates_missing_capability(self):
        with mock.patch(
            "yoke_core.engines.resync_runtime.resolve_project_github_auth",
            side_effect=MissingCapability("buzz", "no github capability"),
        ):
            with pytest.raises(MissingCapability):
                resync_mod._gh_env("buzz")


class TestCallDomainSyncFailClosed:
    def test_call_domain_sync_restores_env(self):
        """_call_domain_sync injects the project token then restores GH_TOKEN."""
        import os

        def fake_func(*args, **kwargs):
            assert os.environ.get("GH_TOKEN") == "new-token"
            return 0

        prior = os.environ.get("GH_TOKEN")
        try:
            os.environ["GH_TOKEN"] = "prior-token"
            with mock.patch(
                "yoke_core.engines.resync_runtime.resolve_project_github_auth",
                return_value=_fake_auth("new-token", "buzz"),
            ):
                assert resync_mod._call_domain_sync(fake_func, "42", project="buzz") is True
            assert os.environ.get("GH_TOKEN") == "prior-token"
        finally:
            if prior is None:
                os.environ.pop("GH_TOKEN", None)
            else:
                os.environ["GH_TOKEN"] = prior

    def test_call_domain_sync_handles_exception_and_restores_env(self, capsys):
        import os

        def boom(*args, **kwargs):
            raise RuntimeError("boom")

        prior = os.environ.pop("GH_TOKEN", None)
        try:
            with mock.patch(
                "yoke_core.engines.resync_runtime.resolve_project_github_auth",
                return_value=_fake_auth("tmp", "buzz"),
            ):
                assert resync_mod._call_domain_sync(boom, project="buzz") is False
            assert "GH_TOKEN" not in os.environ
            captured = capsys.readouterr()
            assert "reason: boom failed: RuntimeError: boom" in captured.err
        finally:
            if prior is not None:
                os.environ["GH_TOKEN"] = prior

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

    def test_call_domain_sync_propagates_missing_token(self):
        """:class:`ProjectGithubAuthError` propagates out of _call_domain_sync."""
        def never_called(*args, **kwargs):  # pragma: no cover - asserts call shape
            raise AssertionError("should not be called when auth fails")

        with mock.patch(
            "yoke_core.engines.resync_runtime.resolve_project_github_auth",
            side_effect=MissingToken("buzz", "no token"),
        ):
            with pytest.raises(MissingToken):
                resync_mod._call_domain_sync(never_called, project="buzz")


def _empty_list_response() -> RestResponse:
    return RestResponse(status=200, headers={}, body=[])


def _yoke_one_issue_response() -> RestResponse:
    return RestResponse(
        status=200, headers={},
        body=[{"number": 1, "title": "[YOK-1] ok", "labels": [],
               "state": "OPEN", "body": ""}],
    )


class TestFetchGhIssuesPerProjectFailClosed:
    def test_records_per_project_auth_failure_sentinel(self):
        """Non-Yoke project's auth failure becomes the _auth_error sentinel."""
        def fake_resolve(project, *args, **kwargs):
            if project == "yoke":
                return _fake_auth()
            raise MissingToken(project, f"no token configured for '{project}'")

        with mock.patch(
            "yoke_core.engines.resync_detect_fetch.resolve_project_github_auth",
            side_effect=fake_resolve,
        ), mock.patch(
            "yoke_core.engines.resync_detect_fetch.request_with_retry",
            return_value=_yoke_one_issue_response(),
        ):
            result = resync_mod._fetch_gh_issues_per_project(
                {"yoke": "", "buzz": "org/buzz"},
            )

        assert result["yoke"][1]["title"] == "[YOK-1] ok"
        assert result["buzz"]["_auth_error"] == "missing_token"
        assert "capability secret set" in result["buzz"]["_repair_hint"]

    def test_reraises_yoke_auth_failure(self):
        """Yoke is the control plane -- its auth failure must propagate."""
        with mock.patch(
            "yoke_core.engines.resync_detect_fetch.resolve_project_github_auth",
            side_effect=MissingCapability("yoke", "no yoke capability"),
        ):
            with pytest.raises(MissingCapability):
                resync_mod._fetch_gh_issues_per_project(
                    {"yoke": "", "buzz": "org/buzz"},
                )


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
            "buzz": {"_auth_error": "missing_token", "_repair_hint": "set the token"},
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
        assert gh_by_project["buzz"]["_auth_error"] == "missing_token"


class TestWrapperPropagation:
    """The patch-friendly wrappers must let ProjectGithubAuthError propagate."""

    def test_fetch_gh_issues_per_project_wrapper_propagates_yoke_auth_error(self):
        with mock.patch(
            "yoke_core.engines.resync_detect_fetch.resolve_project_github_auth",
            side_effect=MissingToken("yoke", "no yoke token"),
        ):
            with pytest.raises(MissingToken):
                resync_mod._fetch_gh_issues_per_project({"yoke": ""})

    def test_stage1_linkage_wrapper_propagates_yoke_auth_error(
        self, populated_db, tmp_path,
    ):
        """The wrapper does NOT swallow ProjectGithubAuthError from the resolver."""
        yoke_root = tmp_path / "state"
        (yoke_root / "backlog").mkdir(parents=True)
        with mock.patch(
            "yoke_core.engines.resync_detect_fetch.resolve_project_github_auth",
            side_effect=MissingCapability("yoke", "no yoke capability"),
        ):
            with pytest.raises(MissingCapability):
                resync_mod.stage1_linkage(populated_db, str(yoke_root))


class TestEngineMultiProjectPartialAuthFailure:
    """End-to-end: when one project's auth fails, the engine continues with
    healthy projects, surfaces the failed project as a warning, and exits
    non-zero overall -- and does NOT manufacture orphans for the failed
    project.
    """

    def test_resync_multi_project_partial_auth_failure(
        self, populated_db, tmp_path, monkeypatch, capsys,
    ):
        yoke_root = tmp_path / "data"
        yoke_root.mkdir(parents=True)
        monkeypatch.setenv("YOKE_ROOT", str(yoke_root))

        # Seed a buzz project row so the multi-project fetch loop visits it.
        conn = connect_test_db(populated_db)
        conn.execute(
            "INSERT INTO projects "
            "(id, slug, name, default_branch, created_at, "
            "github_repo, public_item_prefix) "
            "VALUES (2, 'buzz', 'Buzz', 'main', "
            "'2026-01-01T00:00:00Z', 'org/buzz', 'BUZ') "
            "ON CONFLICT (id) DO UPDATE SET "
            "slug = excluded.slug, name = excluded.name, "
            "github_repo = excluded.github_repo"
        )
        conn.commit()
        conn.close()

        def fake_resolve(project, *, db_path=None, base_env=None, **kwargs):
            if project == "yoke":
                return _fake_auth("sun-token", "yoke")
            raise MissingToken(project, f"no token for '{project}'")

        yoke_issues = RestResponse(
            status=200, headers={},
            body=[
                {"number": 100, "title": "[YOK-42] Test item", "labels": [],
                 "state": "OPEN", "body": ""},
            ],
        )

        with mock.patch(
            "yoke_core.engines.resync_runtime.resolve_project_github_auth",
            side_effect=fake_resolve,
        ), mock.patch(
            "yoke_core.engines.resync_detect_fetch.resolve_project_github_auth",
            side_effect=fake_resolve,
        ), mock.patch(
            "yoke_core.engines.resync_detect_fetch.request_with_retry",
            return_value=yoke_issues,
        ):
            rc = resync_mod.main(["--detect-only"])

        out = capsys.readouterr().out
        assert rc == 1
        # Warning surfaced for buzz with the typed code.
        assert "buzz" in out and "missing_token" in out
        # No buzz items manufactured as orphans.
        assert "project=buzz" not in out
        assert "Summary:" in out
