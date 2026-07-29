"""Transport-aware routing regression tests for the advance
implementation-entry orchestrator.

The orchestrator's control-plane reads and writes must route through the
transport-aware ``call_dispatcher`` facade so the flow works over an https
control plane, not only a local Postgres connection. These tests
monkeypatch ``call_dispatcher`` in the orchestrator namespace and assert
each control-plane touch relays instead of opening a bare local connection.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Dict, List

import pytest

from yoke_contracts.api.function_call import (
    FunctionCallResponse,
    FunctionError,
)
from yoke_core.engines import advance_implementation_entry as orch


def _detail_response(item: Dict[str, Any]) -> FunctionCallResponse:
    return FunctionCallResponse(
        success=True, function="items.detail.get", version="v1",
        result={"item": item},
    )


def _ok_response() -> FunctionCallResponse:
    return FunctionCallResponse(
        success=True, function="lifecycle.transition.execute", version="v1",
        result={"from_status": "refined-idea", "to_status": "implementing"},
    )


def _record_calls(monkeypatch) -> List[Dict[str, Any]]:
    calls: List[Dict[str, Any]] = []

    def fake(**kwargs):
        calls.append(kwargs)
        function_id = kwargs.get("function_id")
        if function_id == "items.detail.get":
            return _detail_response({
                "id": 1920, "status": "idea", "title": "T",
                "project": {"id": 1, "slug": "yoke", "name": "Yoke"},
                "workflow": {"id": "dash", "version_id": 41},
            })
        return _ok_response()

    monkeypatch.setattr(orch, "call_dispatcher", fake)
    return calls


def test_read_item_relays_items_detail_get(monkeypatch):
    calls = _record_calls(monkeypatch)
    item = orch._read_item(1920)
    assert calls[0]["function_id"] == "items.detail.get"
    target = calls[0]["target"]
    assert target.kind == "item" and target.item_id == 1920
    assert item == {
        "id": 1920, "workflow_id": "dash", "workflow_version_id": 41,
        "status": "idea", "title": "T", "project": "yoke",
    }


def test_read_item_returns_none_when_relay_refuses(monkeypatch):
    def fake(**_kwargs):
        return FunctionCallResponse(
            success=False, function="items.detail.get", version="v1",
            error=FunctionError(code="not_found", message="missing"),
        )

    monkeypatch.setattr(orch, "call_dispatcher", fake)
    assert orch._read_item(9999) is None


def test_flip_status_routes_through_call_dispatcher(monkeypatch):
    """The status flip must use the transport-aware relay, not an in-process
    dispatch that only reaches a local Postgres connection."""
    calls = _record_calls(monkeypatch)
    # An in-process dispatch import would bypass the relay; assert it is not
    # the path by proving nothing consults the in-process dispatch symbol.
    sentinel: List[Any] = []
    monkeypatch.setattr(
        "yoke_core.domain.yoke_function_dispatch.dispatch",
        lambda *_a, **_k: sentinel.append("in-process") or _ok_response(),
    )
    response = orch._flip_status(
        42, from_status="refined-idea", to_status="implementing",
        session_id="sess", force=False, qa_bypass=False,
    )
    assert response.success
    assert sentinel == [], "flip must relay, not dispatch in-process"
    call = calls[0]
    assert call["function_id"] == "lifecycle.transition.execute"
    assert call["intent"] == "advance_finalize"
    assert call["actor"].session_id == "sess"
    assert (call["actor"].actor_id or "") == ""
    assert call["target"].kind == "item" and call["target"].item_id == 42
    assert call["payload"]["target_status"] == "implementing"
    assert call["payload"]["source_status"] == "refined-idea"
    assert call["payload"]["force"] is False
    assert call["payload"]["qa_bypass"] is False
    assert call["options"]["sync_github_body"] is True


def test_release_claim_routes_through_call_dispatcher(monkeypatch):
    calls = _record_calls(monkeypatch)
    orch._release_claim(42, "sess", orch.RELEASE_WORKTREE_CREATE_FAILED)
    call = calls[0]
    assert call["function_id"] == "claims.work.release"
    assert call["target"].kind == "item" and call["target"].item_id == 42
    assert call["actor"].session_id == "sess"
    assert call["payload"]["reason"] == orch.RELEASE_WORKTREE_CREATE_FAILED


def test_release_claim_never_raises_on_relay_failure(monkeypatch):
    def boom(**_kwargs):
        raise RuntimeError("relay unavailable")

    monkeypatch.setattr(orch, "call_dispatcher", boom)
    # Best-effort: must swallow relay failures.
    orch._release_claim(42, "sess", "reason")


def test_record_phase_best_effort_over_https_transport(monkeypatch):
    """A ``transport_no_local_db`` emission is a best-effort drop over https,
    not a fatal failure — the phase is still recorded and no error raises."""
    monkeypatch.setattr(
        orch, "emit_event",
        lambda *_a, **_k: SimpleNamespace(
            ok=False, reason=orch.TRANSPORT_NO_LOCAL_DB_REASON,
        ),
    )
    summary: Dict[str, Any] = {"phases": []}
    orch._record_phase(
        summary, item_id=42, phase="preflight", outcome="completed",
        duration_ms=1, session_id="sess",
    )
    assert summary["phases"] == [
        {"phase": "preflight", "outcome": "completed", "duration_ms": 1}
    ]


def test_record_phase_still_raises_on_non_transport_failure(monkeypatch):
    monkeypatch.setattr(
        orch, "emit_event",
        lambda *_a, **_k: SimpleNamespace(ok=False, reason="exception"),
    )
    with pytest.raises(RuntimeError, match="AdvancePhaseCompleted"):
        orch._record_phase(
            {"phases": []}, item_id=42, phase="preflight",
            outcome="completed", duration_ms=1, session_id="sess",
        )
