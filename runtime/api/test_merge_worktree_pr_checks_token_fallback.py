"""REST check-runs authorization fails closed for the required App grant."""

from __future__ import annotations

from runtime.api.test_merge_worktree_pr_checks_test_helpers import _stub_ctx


def test_check_runs_authorization_error_routes_to_failed(monkeypatch) -> None:
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


def test_get_check_runs_returns_error_on_403(monkeypatch) -> None:
    from yoke_core.domain.gh_rest_transport import RestAuthError
    from yoke_core.domain.project_github_auth import ProjectGithubAuth
    from yoke_core.engines import merge_worktree_ci_rest

    # First call (head sha lookup) returns the head SHA; second call
    # (check-runs) raises RestAuthError to simulate 403.
    call_counter = {"n": 0}

    class _Resp:
        def __init__(self, body):
            self.status = 200
            self.headers: dict = {}
            self.body = body

    def _fake_request(req, *, token, timeout_seconds=30.0):
        call_counter["n"] += 1
        if call_counter["n"] == 1:
            return _Resp({"head": {"sha": "deadbeef"}})
        raise RestAuthError("HTTP 403: Resource not accessible", status=403)

    monkeypatch.setattr(
        merge_worktree_ci_rest,
        "resolve_auth",
        lambda *_a, **_kw: ProjectGithubAuth(
            project="yoke", repo="o/r", token="t"
        ),
    )
    monkeypatch.setattr(merge_worktree_ci_rest, "request_with_retry", _fake_request)

    state, err = merge_worktree_ci_rest.get_check_runs(_stub_ctx(), "3309")
    assert state is None
    assert err is not None
    assert "authorization failed" in err


def test_get_check_runs_maps_run_states_to_canonical_vocabulary(monkeypatch) -> None:
    """REST status/conclusion pairs translate to the legacy state names
    the CI poll loop's classifier expects (SUCCESS / PENDING / FAILURE etc.)."""
    from yoke_core.domain.project_github_auth import ProjectGithubAuth
    from yoke_core.engines import merge_worktree_ci_rest

    class _Resp:
        def __init__(self, body):
            self.status = 200
            self.headers: dict = {}
            self.body = body

    call_counter = {"n": 0}

    def _fake_request(req, *, token, timeout_seconds=30.0):
        call_counter["n"] += 1
        if call_counter["n"] == 1:
            return _Resp({"head": {"sha": "abc123"}})
        return _Resp(
            {
                "check_runs": [
                    {"status": "completed", "conclusion": "success"},
                    {"status": "completed", "conclusion": "failure"},
                    {"status": "in_progress", "conclusion": ""},
                    {"status": "queued", "conclusion": ""},
                    {"status": "completed", "conclusion": "neutral"},
                ]
            }
        )

    monkeypatch.setattr(
        merge_worktree_ci_rest,
        "resolve_auth",
        lambda *_a, **_kw: ProjectGithubAuth(
            project="yoke", repo="o/r", token="t"
        ),
    )
    monkeypatch.setattr(merge_worktree_ci_rest, "request_with_retry", _fake_request)

    state, err = merge_worktree_ci_rest.get_check_runs(_stub_ctx(), "3309")
    assert err is None
    assert state is not None
    assert state.states == (
        "SUCCESS",
        "FAILURE",
        "PENDING",
        "PENDING",
        "NEUTRAL",
    )
