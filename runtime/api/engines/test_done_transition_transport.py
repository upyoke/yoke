"""Transport-aware routing regression tests for done-transition reads.

The done-transition engine's control-plane reads must route through the
transport-aware ``call_dispatcher`` facade so the merge finalize works over
an https control plane, not only a local Postgres connection. These tests
monkeypatch ``call_dispatcher`` and assert every migrated read relays instead
of opening a bare ``_connect()``, with each gate's verdict, narrative, and
degrade-vs-fail-closed disposition preserved. Deployment guards are covered
by ``test_done_transition_deploy_transport``.
"""

from __future__ import annotations

import pytest

from yoke_contracts.api.function_call import FunctionCallResponse
from yoke_core.engines import done_transition as dt
from yoke_core.engines import done_transition_cleanup as cleanup
from yoke_core.engines import done_transition_gates as gates
from yoke_core.engines import done_transition_item_context as item_context
from yoke_core.engines import done_transition_preconditions as preconditions
from yoke_core.engines import done_transition_runtime as runtime

# Synthetic fixture id kept off the bare literal so the doc-hygiene drift guard stays clean.
TEST_ITEM_ID = 42
TEST_ITEM_REF = f"YOK-{TEST_ITEM_ID}"


def _resp(function_id, result=None, *, success=True):
    return FunctionCallResponse(
        success=success, function=function_id, version="v1", result=result or {}
    )


def _install(monkeypatch, fake, modules):
    """Route every relay through *fake* and fail on any bare read connect."""
    # Local-import call sites re-read call_dispatcher from the source each call.
    monkeypatch.setattr(
        "yoke_core.api.service_client_structured_api_adapter.call_dispatcher", fake
    )
    # Module-top import sites bind the name at import time.
    for module in modules:
        if hasattr(module, "call_dispatcher"):
            monkeypatch.setattr(module, "call_dispatcher", fake)
    monkeypatch.setattr(
        dt, "_connect",
        lambda *a, **k: pytest.fail("must not open a bare _connect() on a read path"),
    )


_DEFINITION = {
    "stages": [{"id": "idea"}, {"id": "implementing"}, {"id": "done"}],
    "terminal_stage_ids": ["done"],
    "policies": {"delivery": "no_run"},
    "executor_bindings": [],
    "entry_surfaces": ["harness_skill"],
}


class TestItemContextRelay:
    def test_relays_and_reconstructs_runtime(self, monkeypatch):
        calls = []

        def fake(**kwargs):
            calls.append(kwargs)
            return _resp("done_transition.item_context", {
                "found": True,
                "title": "Ship it",
                "stage_id": "implementing",
                "lane_branch": TEST_ITEM_REF,
                "project": "yoke",
                "workflow": {
                    "workflow_id": "issue",
                    "workflow_version_id": 3,
                    "version": 2,
                    "definition_digest": "abc",
                    "definition": _DEFINITION,
                },
            })

        _install(monkeypatch, fake, [item_context])
        ctx = item_context.load_done_item_context_over_transport(42)
        assert calls[0]["function_id"] == "done_transition.item_context"
        assert calls[0]["target"].item_id == 42
        assert ctx is not None
        assert ctx.title == "Ship it"
        assert ctx.stage_id == "implementing"
        assert ctx.lane_branch == TEST_ITEM_REF
        assert ctx.project == "yoke"
        assert ctx.workflow.workflow_id == "issue"
        assert ctx.workflow.stage_ids == ("idea", "implementing", "done")

    def test_not_found_returns_none(self, monkeypatch):
        _install(
            monkeypatch,
            lambda **k: _resp("done_transition.item_context", {"found": False}),
            [item_context],
        )
        assert item_context.load_done_item_context_over_transport(43) is None

    def test_failure_raises(self, monkeypatch):
        _install(
            monkeypatch,
            lambda **k: _resp("done_transition.item_context", success=False),
            [item_context],
        )
        with pytest.raises(RuntimeError):
            item_context.load_done_item_context_over_transport(44)


class TestItemFieldRelay:
    def test_relays_and_returns_value(self, monkeypatch):
        calls = []

        def fake(**kwargs):
            calls.append(kwargs)
            return _resp("done_transition.item_field", {"value": "yoke-hosted-stage"})

        _install(monkeypatch, fake, [runtime])
        assert runtime._query_item_field(42, "deployment_flow") == "yoke-hosted-stage"
        assert calls[0]["function_id"] == "done_transition.item_field"
        assert calls[0]["payload"] == {"field": "deployment_flow"}
        assert calls[0]["target"].item_id == 42

    def test_failure_raises(self, monkeypatch):
        _install(
            monkeypatch,
            lambda **k: _resp("done_transition.item_field", success=False),
            [runtime],
        )
        with pytest.raises(RuntimeError):
            runtime._query_item_field(42, "status")


class TestForeignClaimRelay:
    def test_true_when_other_session_holds(self, monkeypatch):
        monkeypatch.setattr(cleanup, "_current_session_id", lambda: "caller-x")
        calls = []

        def fake(**kwargs):
            calls.append(kwargs)
            return _resp("claims.work.holder_list", {
                "holders": [{"session_id": "other-session"}],
            })

        _install(monkeypatch, fake, [cleanup])
        assert cleanup._has_foreign_claim(42) is True
        assert calls[0]["function_id"] == "claims.work.holder_list"
        assert calls[0]["target"].item_id == 42

    def test_false_when_only_caller_holds(self, monkeypatch):
        monkeypatch.setattr(cleanup, "_current_session_id", lambda: "caller-x")
        _install(
            monkeypatch,
            lambda **k: _resp("claims.work.holder_list", {
                "holders": [{"session_id": "caller-x"}],
            }),
            [cleanup],
        )
        assert cleanup._has_foreign_claim(42) is False

    def test_failclosed_on_non_success(self, monkeypatch):
        monkeypatch.setattr(cleanup, "_current_session_id", lambda: "caller-x")
        _install(
            monkeypatch,
            lambda **k: _resp("claims.work.holder_list", success=False),
            [cleanup],
        )
        assert cleanup._has_foreign_claim(42) is True

    def test_failclosed_on_exception(self, monkeypatch):
        monkeypatch.setattr(cleanup, "_current_session_id", lambda: "caller-x")

        def boom(**kwargs):
            raise RuntimeError("transport down")

        _install(monkeypatch, boom, [cleanup])
        assert cleanup._has_foreign_claim(42) is True


class TestBlockedFlagRelay:
    def test_blocked_returns_9_with_narrative(self, monkeypatch, capsys):
        calls = []

        def fake(**kwargs):
            calls.append(kwargs)
            return _resp("done_transition.blocked_gate", {
                "blocked": True, "reason": "upstream unresolved",
            })

        monkeypatch.setattr(
            gates, "_ref", lambda _item_id, _item_ref=None: TEST_ITEM_REF
        )
        _install(monkeypatch, fake, [gates])
        assert gates._check_blocked_flag(42) == 9
        assert calls[0]["function_id"] == "done_transition.blocked_gate"
        out = capsys.readouterr().out
        assert "items.blocked=1" in out
        assert "Reason: upstream unresolved" in out
        assert f"Run /yoke unblock {TEST_ITEM_REF} first." in out

    def test_not_blocked_returns_none(self, monkeypatch):
        _install(
            monkeypatch,
            lambda **k: _resp("done_transition.blocked_gate", {"blocked": False}),
            [gates],
        )
        assert gates._check_blocked_flag(42) is None

    def test_degrades_to_none_on_failure(self, monkeypatch):
        _install(
            monkeypatch,
            lambda **k: _resp("done_transition.blocked_gate", success=False),
            [gates],
        )
        assert gates._check_blocked_flag(42) is None


class TestProjectContextRelay:
    def test_default_branch_relays(self, monkeypatch):
        def fake(**kwargs):
            assert kwargs["function_id"] == "projects.get"
            assert kwargs["payload"]["field"] == "default_branch"
            return _resp("projects.get", {"value": "trunk"})

        _install(monkeypatch, fake, [gates])
        assert gates._resolve_default_branch("acme") == "trunk"

    def test_default_branch_degrades_on_failure(self, monkeypatch):
        _install(
            monkeypatch,
            lambda **k: _resp("projects.get", success=False),
            [gates],
        )
        assert gates._resolve_default_branch("acme") == ""

    def test_project_context_uses_checkout_and_branch(self, monkeypatch, tmp_path):
        monkeypatch.setattr(
            "yoke_core.domain.project_checkout_locations.checkout_for_project_slug",
            lambda slug, **_k: tmp_path,
        )
        _install(
            monkeypatch,
            lambda **k: _resp("projects.get", {"value": "trunk"}),
            [gates],
        )
        repo, branch = gates._resolve_project_context(42, "acme", tmp_path / "main")
        assert repo == tmp_path
        assert branch == "trunk"


class TestPreconditionsRelay:
    def test_relays_allowed(self, monkeypatch):
        calls = []

        def fake(**kwargs):
            calls.append(kwargs)
            return _resp("done_transition.done_preconditions", {
                "allowed": True, "reason": None,
            })

        _install(monkeypatch, fake, [preconditions])
        allowed, reason = preconditions.check_done_preconditions(42, "", False)
        assert (allowed, reason) == (True, None)
        assert calls[0]["function_id"] == "done_transition.done_preconditions"
        assert calls[0]["payload"] == {
            "deploy_flow": "", "require_plan_verdict": False,
        }

    def test_relays_blocked_reason(self, monkeypatch):
        _install(
            monkeypatch,
            lambda **k: _resp("done_transition.done_preconditions", {
                "allowed": False,
                "reason": "deployed_to is empty for deployment_flow=acme-prod",
            }),
            [preconditions],
        )
        allowed, reason = preconditions.check_done_preconditions(42, "acme-prod", False)
        assert allowed is False
        assert "deployed_to is empty" in reason

    def test_failure_raises(self, monkeypatch):
        _install(
            monkeypatch,
            lambda **k: _resp("done_transition.done_preconditions", success=False),
            [preconditions],
        )
        with pytest.raises(RuntimeError):
            preconditions.check_done_preconditions(42, "", False)
