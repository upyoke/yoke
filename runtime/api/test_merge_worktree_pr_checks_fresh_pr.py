"""REST-seam coverage for ``_wait_for_ci`` propagation-race handling."""

from __future__ import annotations

from runtime.api.test_merge_worktree_pr_checks_test_helpers import _stub_ctx


class TestWaitForCiRestSeam:
    """``_wait_for_ci`` orchestration over the REST check-runs surface.

    The underlying transient-failure retry policy lives in
    :mod:`yoke_core.domain.gh_rest_transport` and is covered there;
    these tests verify the merge-engine-level routing (PASSED / SKIPPED /
    FAILED) for the shapes the REST helper can return.
    """

    def test_no_check_runs_at_all_skips_cleanly(self, monkeypatch) -> None:
        from yoke_core.engines import merge_worktree
        from yoke_core.engines import merge_worktree_ci
        from yoke_core.engines.merge_worktree_ci_rest import CheckRunsState

        monkeypatch.setattr(
            merge_worktree, "_emit_merge_event", lambda *_a, **_kw: None
        )
        monkeypatch.setattr(
            merge_worktree_ci,
            "get_check_runs",
            lambda *_a, **_kw: (CheckRunsState(states=()), None),
        )

        outcome = merge_worktree._wait_for_ci("3309", _stub_ctx())
        assert outcome.outcome == "skipped"
        assert outcome.reason == "no_checks_configured"

    def test_check_runs_authorization_failure_fails_closed(self, monkeypatch) -> None:
        """The required Checks read grant cannot degrade into a CI skip."""
        from yoke_core.engines import merge_worktree
        from yoke_core.engines import merge_worktree_ci

        monkeypatch.setattr(
            merge_worktree, "_emit_merge_event", lambda *_a, **_kw: None
        )
        monkeypatch.setattr(
            merge_worktree_ci,
            "get_check_runs",
            lambda *_a, **_kw: (
                None, "check-runs REST authorization failed: HTTP 403",
            ),
        )

        outcome = merge_worktree._wait_for_ci("3309", _stub_ctx())
        assert outcome.outcome == "failed"

    def test_all_success_runs_pass(self, monkeypatch) -> None:
        from yoke_core.engines import merge_worktree
        from yoke_core.engines import merge_worktree_ci
        from yoke_core.engines.merge_worktree_ci_rest import CheckRunsState

        monkeypatch.setattr(
            merge_worktree, "_emit_merge_event", lambda *_a, **_kw: None
        )
        monkeypatch.setattr(
            merge_worktree_ci,
            "get_check_runs",
            lambda *_a, **_kw: (
                CheckRunsState(states=("SUCCESS", "SUCCESS")),
                None,
            ),
        )
        outcome = merge_worktree._wait_for_ci("3309", _stub_ctx())
        assert outcome.outcome == "passed"

    def test_failure_state_routes_to_failed(self, monkeypatch) -> None:
        from yoke_core.engines import merge_worktree
        from yoke_core.engines import merge_worktree_ci
        from yoke_core.engines.merge_worktree_ci_rest import CheckRunsState

        monkeypatch.setattr(
            merge_worktree, "_emit_merge_event", lambda *_a, **_kw: None
        )
        monkeypatch.setattr(
            merge_worktree_ci,
            "get_check_runs",
            lambda *_a, **_kw: (
                CheckRunsState(states=("SUCCESS", "FAILURE")),
                None,
            ),
        )
        outcome = merge_worktree._wait_for_ci("3309", _stub_ctx())
        assert outcome.outcome == "failed"

    def test_neutral_and_skipped_treated_as_pass(self, monkeypatch) -> None:
        """Neutral / skipped check-run conclusions don't block the merge."""
        from yoke_core.engines import merge_worktree
        from yoke_core.engines import merge_worktree_ci
        from yoke_core.engines.merge_worktree_ci_rest import CheckRunsState

        monkeypatch.setattr(
            merge_worktree, "_emit_merge_event", lambda *_a, **_kw: None
        )
        monkeypatch.setattr(
            merge_worktree_ci,
            "get_check_runs",
            lambda *_a, **_kw: (
                CheckRunsState(
                    states=("SUCCESS", "NEUTRAL", "SKIPPED")
                ),
                None,
            ),
        )
        outcome = merge_worktree._wait_for_ci("3309", _stub_ctx())
        assert outcome.outcome == "passed"

    def test_rest_helper_error_emits_failed_event(self, monkeypatch) -> None:
        from yoke_core.engines import merge_worktree
        from yoke_core.engines import merge_worktree_ci

        emitted: list[tuple[str, dict]] = []
        monkeypatch.setattr(
            merge_worktree,
            "_emit_merge_event",
            lambda name, **kw: emitted.append((name, kw)),
        )
        monkeypatch.setattr(
            merge_worktree_ci,
            "get_check_runs",
            lambda *_a, **_kw: (None, "transport failure"),
        )

        outcome = merge_worktree._wait_for_ci("3309", _stub_ctx())
        assert outcome.outcome == "failed"
        assert any(name == "MergePullRequestCiFailed" for name, _ in emitted)


class TestProjectAuthSurface:
    """REST helpers route project-auth failures to a typed error class."""

    def test_validate_github_auth_for_merge_routes_missing_app_credentials(self, monkeypatch) -> None:
        from yoke_core.domain.project_github_auth import MissingAppCredentials
        from yoke_core.engines import merge_worktree_pr_rest

        def _raise(*_a, **_kw):
            raise MissingAppCredentials(
                "yoke",
                "GitHub App control-plane credentials are unavailable",
            )

        monkeypatch.setattr(
            merge_worktree_pr_rest,
            "resolve_project_github_auth",
            _raise,
        )

        ctx = _stub_ctx()
        ctx.project = "yoke"
        ok, message = merge_worktree_pr_rest.validate_github_auth_for_merge(ctx)
        assert ok is False
        assert "missing_app_credentials" in (message or "")
        assert "control-plane App issuer" in (message or "")

    def test_validate_github_auth_for_merge_routes_no_project(self) -> None:
        from yoke_core.engines import merge_worktree_pr_rest

        ctx = _stub_ctx()  # no project set
        ok, message = merge_worktree_pr_rest.validate_github_auth_for_merge(ctx)
        assert ok is False
        assert "merge context has no project" in (message or "")

    def test_validate_github_auth_for_merge_succeeds_when_token_present(
        self, monkeypatch
    ) -> None:
        from yoke_contracts.github_app_installation_permissions import (
            GITHUB_METADATA_READ_PERMISSION_LEVELS,
        )
        from yoke_core.domain.project_github_auth import ProjectGithubAuth
        from yoke_core.engines import merge_worktree_pr_rest

        calls = []

        def _resolve(*args, **kwargs):
            calls.append((args, kwargs))
            return ProjectGithubAuth(
                project="yoke", repo="o/r", token="ghs_x"
            )

        monkeypatch.setattr(
            merge_worktree_pr_rest,
            "resolve_project_github_auth",
            _resolve,
        )
        ctx = _stub_ctx()
        ctx.project = "yoke"
        ok, message = merge_worktree_pr_rest.validate_github_auth_for_merge(ctx)
        assert ok is True
        assert message is None
        assert calls == [
            (
                ("yoke",),
                {"required_permissions": GITHUB_METADATA_READ_PERMISSION_LEVELS},
            )
        ]
