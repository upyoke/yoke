"""Regression checks for worktree preflight claim routing."""

from __future__ import annotations

from runtime.api.domain.test_worktree_preflight_steps import (
    FunctionCallResponse as FunctionCallResponse,
    FunctionError as FunctionError,
    _patch_facade as _patch_facade,
    _resp as _resp,
    steps as steps,
)


class TestLocalCheckoutForItem:
    def test_resolves_project_checkout(self, monkeypatch, tmp_path):
        def router(*, function_id, target, payload=None, **_k):
            assert function_id == "items.detail.get"
            return _resp(
                function_id,
                result={
                    "item": {"id": 1599, "project": {"id": 5}},
                },
            )

        _patch_facade(monkeypatch, router)
        monkeypatch.setattr(
            "yoke_core.domain.project_checkout_locations.checkout_for_project_id",
            lambda pid, **_k: tmp_path if pid == 5 else None,
        )
        assert steps._local_checkout_for_item("YOK-1599") == str(tmp_path)

    def test_returns_none_when_detail_get_fails(self, monkeypatch):
        _patch_facade(
            monkeypatch,
            lambda **_k: _resp(
                "items.detail.get",
                success=False,
                error=FunctionError(code="not_found", message="no"),
            ),
        )
        assert steps._local_checkout_for_item("YOK-1599") is None


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
                success=True,
                function="claims.work.acquire",
                version="v1",
                result={"claim": "held"},
            ),
        )
        ok, msg = steps.claim_work("YOK-1599")
        assert ok is True
        assert msg  # non-empty status string
        assert calls[0]["function_id"] == "claims.work.acquire"
        assert calls[0]["target"].kind == "item"
        assert calls[0]["target"].item_id == 1599

    def test_other_session_holding_returns_failure(self, monkeypatch):
        self._patch_dispatch(
            monkeypatch,
            FunctionCallResponse(
                success=False,
                function="claims.work.acquire",
                version="v1",
                error=FunctionError(
                    code="active_claim_conflict",
                    message="already claimed by session 'alt'",
                ),
            ),
        )
        ok, msg = steps.claim_work("YOK-1599")
        assert ok is False
        assert "already claimed by session" in msg
