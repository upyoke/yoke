"""Unit tests for worktree_preflight step helpers."""

from __future__ import annotations

from types import SimpleNamespace

from yoke_contracts.api.function_call import (
    FunctionCallResponse,
    FunctionError,
)
from yoke_core.domain import worktree_dirty_main_guard as guard
from yoke_core.domain import worktree_preflight_steps as steps


def _fake_run_factory(canned):
    """Return a callable that pops responses off a queue.

    ``canned`` is a list of (returncode, stdout, stderr) tuples returned
    in FIFO order. Lets tests script the underlying ``_run`` calls
    without exec'ing real subprocesses.
    """
    queue = list(canned)

    def _fake_run(cmd, *_args, **_kwargs):
        if not queue:
            raise AssertionError(f"unexpected _run call: {cmd!r}")
        rc, out, err = queue.pop(0)
        return SimpleNamespace(returncode=rc, stdout=out, stderr=err)

    return _fake_run, queue


class TestPhysicalCwdMode:
    def test_matched_when_cwd_equals_worktree(self, tmp_path):
        assert steps.physical_cwd_mode(str(tmp_path), str(tmp_path)) == steps.CWD_MODE_MATCHED

    def test_matched_when_cwd_inside_worktree(self, tmp_path):
        sub = tmp_path / "runtime" / "api"
        sub.mkdir(parents=True)
        assert steps.physical_cwd_mode(str(sub), str(tmp_path)) == steps.CWD_MODE_MATCHED

    def test_static_when_cwd_outside_worktree(self, tmp_path):
        wt = tmp_path / ".worktrees" / "YOK-1"
        wt.mkdir(parents=True)
        assert steps.physical_cwd_mode(str(tmp_path), str(wt)) == steps.CWD_MODE_STATIC

    def test_static_when_cwd_is_sibling(self, tmp_path):
        a = tmp_path / "a"
        b = tmp_path / "b"
        a.mkdir()
        b.mkdir()
        assert steps.physical_cwd_mode(str(a), str(b)) == steps.CWD_MODE_STATIC


class TestSanctionedPatternsRetired:
    """sanctioned_patterns() retired with the envelope; assert the symbol is gone."""

    def test_sanctioned_patterns_no_longer_exported(self):
        assert not hasattr(steps, "sanctioned_patterns")


class TestCheckDirtyMain:
    def test_clean_main_returns_no_block(self, monkeypatch):
        canned = [
            (0, "", ""),  # diff --name-only
            (0, "", ""),  # diff --name-only --cached
            (0, "", ""),  # ls-files --others --exclude-standard
        ]
        fake_run, _ = _fake_run_factory(canned)
        monkeypatch.setattr(guard, "_run", fake_run)
        blocked, kind, paths = steps.check_dirty_main("/repo", ["foo.py"])
        assert blocked is False
        assert (kind, paths) == ("", [])

    def test_tracked_dirt_blocks_with_paths(self, monkeypatch):
        canned = [
            (0, "runtime/api/foo.py\n", ""),
            (0, "", ""),
            (0, "", ""),
        ]
        fake_run, _ = _fake_run_factory(canned)
        monkeypatch.setattr(guard, "_run", fake_run)
        blocked, kind, paths = steps.check_dirty_main("/repo", ["runtime/api/foo.py"])
        assert blocked is True
        assert kind == steps.BLOCK_DIRTY_TRACKED
        assert "runtime/api/foo.py" in paths

    def test_staged_dirt_also_blocks_as_tracked(self, monkeypatch):
        canned = [
            (0, "", ""),
            (0, "runtime/api/bar.py\n", ""),
            (0, "", ""),
        ]
        fake_run, _ = _fake_run_factory(canned)
        monkeypatch.setattr(guard, "_run", fake_run)
        blocked, kind, paths = steps.check_dirty_main("/repo", ["runtime/api/bar.py"])
        assert blocked is True
        assert kind == steps.BLOCK_DIRTY_TRACKED
        assert paths == ["runtime/api/bar.py"]

    def test_untracked_without_needed_paths_does_not_block(self, monkeypatch):
        canned = [
            (0, "", ""),
            (0, "", ""),
            (0, "scratch.py\n", ""),
        ]
        fake_run, _ = _fake_run_factory(canned)
        monkeypatch.setattr(guard, "_run", fake_run)
        blocked, kind, paths = steps.check_dirty_main("/repo")
        assert blocked is False
        assert (kind, paths) == ("", [])


def _resp(function, *, result=None, success=True, error=None):
    return FunctionCallResponse(
        success=success, function=function, version="v1",
        result=result or {}, error=error,
    )


def _patch_facade(monkeypatch, router):
    from yoke_core.api import service_client_structured_api_adapter as facade

    monkeypatch.setattr(facade, "call_dispatcher", router)


class TestActivatePathClaims:
    """The client-git / server-DB split: list claims, resolve heads from
    the machine-local checkout, relay ``claims.path.activation_run`` with
    the resolved heads — no subprocess, no bare local connect, so it works
    over an https control plane the same way it does in-process."""

    def test_no_claims_relays_empty_head_map(self, monkeypatch):
        calls = []

        def router(*, function_id, target, payload=None, **_k):
            calls.append({"function_id": function_id, "payload": payload})
            if function_id == "claims.path.list":
                return _resp(function_id, result={"item_id": 1599, "claims": []})
            if function_id == "claims.path.activation_run":
                return _resp(function_id, result={
                    "outcomes": [], "blocked_errors": [], "diverged_error": None,
                })
            raise AssertionError(function_id)

        _patch_facade(monkeypatch, router)
        ok, err, ids = steps.activate_path_claims(1599)
        assert (ok, err, ids) == (True, "", [])
        run_call = next(
            c for c in calls if c["function_id"] == "claims.path.activation_run"
        )
        assert run_call["payload"] == {"resolved_heads": {}}

    def test_planned_claim_resolves_head_and_activates(self, monkeypatch):
        from yoke_core.domain import advance_path_claim_activation_retry as _retry

        monkeypatch.setattr(steps, "_local_checkout_for_item", lambda _id: "/repo")
        monkeypatch.setattr(
            _retry,
            "resolve_integration_head_with_retry",
            lambda *a, **k: _retry.ResolveResult(
                commit_sha="deadbeef", error=None, diverged=False, attempts=1,
            ),
        )
        calls = []

        def router(*, function_id, target, payload=None, **_k):
            calls.append({"function_id": function_id, "payload": payload})
            if function_id == "claims.path.list":
                return _resp(function_id, result={"claims": [
                    {"id": 39, "state": "planned", "integration_target": "main"},
                ]})
            if function_id == "claims.path.activation_run":
                return _resp(function_id, result={"outcomes": [
                    {"claim_id": 39, "state_before": "planned",
                     "state_after": "active", "error": None},
                ], "blocked_errors": [], "diverged_error": None})
            raise AssertionError(function_id)

        _patch_facade(monkeypatch, router)
        ok, err, ids = steps.activate_path_claims(1599)
        assert (ok, err, ids) == (True, "", [39])
        run_call = next(
            c for c in calls if c["function_id"] == "claims.path.activation_run"
        )
        assert run_call["payload"] == {"resolved_heads": {39: "deadbeef"}}

    def test_planned_head_resolution_error_blocks_before_activation(
        self, monkeypatch
    ):
        from yoke_core.domain import advance_path_claim_activation_retry as _retry

        monkeypatch.setattr(steps, "_local_checkout_for_item", lambda _id: "/repo")
        monkeypatch.setattr(
            _retry,
            "resolve_integration_head_with_retry",
            lambda *a, **k: _retry.ResolveResult(
                commit_sha=None, error="db-lock:retried 3 times: locked",
                diverged=False, attempts=3,
            ),
        )
        seen = []

        def router(*, function_id, target, payload=None, **_k):
            seen.append(function_id)
            if function_id == "claims.path.list":
                return _resp(function_id, result={"claims": [
                    {"id": 39, "state": "planned", "integration_target": "main"},
                ]})
            raise AssertionError(f"activation_run must not run: {function_id}")

        _patch_facade(monkeypatch, router)
        ok, err, ids = steps.activate_path_claims(1599)
        assert ok is False
        assert steps.classify_activation_failure(err) == steps.BLOCK_DB_LOCK
        assert "claims.path.activation_run" not in seen

    def test_blocked_claim_resolution_error_is_omitted_not_fatal(self, monkeypatch):
        from yoke_core.domain import advance_path_claim_activation_retry as _retry

        monkeypatch.setattr(steps, "_local_checkout_for_item", lambda _id: "/repo")
        monkeypatch.setattr(
            _retry,
            "resolve_integration_head_with_retry",
            lambda *a, **k: _retry.ResolveResult(
                commit_sha=None, error="boundary error", diverged=False, attempts=1,
            ),
        )
        run_payloads = []

        def router(*, function_id, target, payload=None, **_k):
            if function_id == "claims.path.list":
                return _resp(function_id, result={"claims": [
                    {"id": 40, "state": "blocked", "integration_target": "main"},
                ]})
            if function_id == "claims.path.activation_run":
                run_payloads.append(payload)
                return _resp(function_id, result={
                    "outcomes": [], "blocked_errors": [], "diverged_error": None,
                })
            raise AssertionError(function_id)

        _patch_facade(monkeypatch, router)
        ok, err, ids = steps.activate_path_claims(1599)
        assert (ok, err, ids) == (True, "", [])
        # The blocked claim's unresolved head is omitted; the server keeps it
        # blocked (or falls back to local resolution on repair-to-planned).
        assert run_payloads == [{"resolved_heads": {}}]

    def test_activation_run_blocked_errors_surface(self, monkeypatch):
        def router(*, function_id, target, payload=None, **_k):
            if function_id == "claims.path.list":
                return _resp(function_id, result={"claims": []})
            if function_id == "claims.path.activation_run":
                return _resp(function_id, result={
                    "outcomes": [],
                    "blocked_errors": ["claim 39 is blocked by upstream 12"],
                    "diverged_error": None,
                })
            raise AssertionError(function_id)

        _patch_facade(monkeypatch, router)
        ok, err, ids = steps.activate_path_claims(1599)
        assert ok is False
        assert "blocked by upstream" in err
        assert ids == []


class TestLocalCheckoutForItem:
    def test_resolves_project_checkout(self, monkeypatch, tmp_path):
        def router(*, function_id, target, payload=None, **_k):
            assert function_id == "items.detail.get"
            return _resp(function_id, result={
                "item": {"id": 1599, "project": {"id": 5}},
            })

        _patch_facade(monkeypatch, router)
        monkeypatch.setattr(
            "yoke_core.domain.project_checkout_locations.checkout_for_project_id",
            lambda pid, **_k: tmp_path if pid == 5 else None,
        )
        assert steps._local_checkout_for_item(1599) == str(tmp_path)

    def test_returns_none_when_detail_get_fails(self, monkeypatch):
        _patch_facade(
            monkeypatch,
            lambda **_k: _resp(
                "items.detail.get", success=False,
                error=FunctionError(code="not_found", message="no"),
            ),
        )
        assert steps._local_checkout_for_item(1599) is None


class TestClaimWork:
    """``claim_work`` acquires the item work claim through the transport-aware
    dispatcher (``claims.work.acquire``) rather than shelling to a local-DB
    module, so it works over an https control plane."""

    def _patch_dispatch(self, monkeypatch, response):
        from yoke_core.api import service_client_structured_api_adapter as facade

        calls = []

        def fake(**kwargs):
            calls.append(kwargs)
            return response

        monkeypatch.setattr(facade, "call_dispatcher", fake)
        return calls

    def test_acquire_success_relays_claims_work_acquire(self, monkeypatch):
        calls = self._patch_dispatch(
            monkeypatch,
            FunctionCallResponse(
                success=True, function="claims.work.acquire", version="v1",
                result={"claim": "held"},
            ),
        )
        ok, msg = steps.claim_work(1599)
        assert ok is True
        assert msg  # non-empty status string
        assert calls[0]["function_id"] == "claims.work.acquire"
        assert calls[0]["target"].kind == "item"
        assert calls[0]["target"].item_id == 1599

    def test_other_session_holding_returns_failure(self, monkeypatch):
        self._patch_dispatch(
            monkeypatch,
            FunctionCallResponse(
                success=False, function="claims.work.acquire", version="v1",
                error=FunctionError(
                    code="active_claim_conflict",
                    message="already claimed by session 'alt'",
                ),
            ),
        )
        ok, msg = steps.claim_work(1599)
        assert ok is False
        assert "already claimed by session" in msg
