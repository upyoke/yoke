"""Mutation commands emit a durable receipt before local cleanup."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import patch

from yoke_cli.commands import _helpers
from yoke_contracts.api.function_call import FunctionCallResponse, TargetRef
from runtime.api.cli.test_yoke_operations_cli_deployment import _run_capture


def _response(request, result: dict) -> FunctionCallResponse:
    return FunctionCallResponse(
        success=True,
        function=request.function,
        version=request.version,
        request_id=request.request_id,
        result=result,
    )


def test_terminal_lifecycle_receipt_precedes_lane_cleanup(monkeypatch) -> None:
    detail = FunctionCallResponse(
        success=True,
        function="items.detail.get",
        version="v1",
        result={"item": {"public_ref": "ITEM-7"}},
    )
    transition = FunctionCallResponse(
        success=True,
        function="lifecycle.transition.execute",
        version="v1",
        result={"item_id": 7, "to_status": "done"},
    )
    responses = iter((detail, transition))
    timeline: list[str] = []
    monkeypatch.setattr(_helpers, "ensure_handlers_loaded", lambda: None)
    monkeypatch.setattr(
        _helpers, "build_actor", lambda **_kwargs: SimpleNamespace(session_id="s-1")
    )
    monkeypatch.setattr(_helpers, "call_dispatcher", lambda **_kwargs: next(responses))
    monkeypatch.setattr(
        _helpers,
        "emit_response",
        lambda *_args, **_kwargs: timeline.append("receipt") or 0,
    )

    def cleanup(*_args, **_kwargs):
        timeline.append("cleanup")
        return ()

    monkeypatch.setattr(
        _helpers.importlib,
        "import_module",
        lambda _name: SimpleNamespace(cleanup_terminal_item_lanes=cleanup),
    )

    result = _helpers.dispatch_and_emit(
        function_id="lifecycle.transition.execute",
        target=TargetRef(kind="item", item_id=7),
        payload={"target_status": "done"},
        session_id="s-1",
        json_mode=False,
    )

    assert result == 0
    assert timeline == ["receipt", "cleanup"]


def test_lifecycle_transition_prints_structured_success(monkeypatch) -> None:
    monkeypatch.setattr(
        "yoke_cli.transport.public_ref_display.lookup_public_refs",
        lambda ids: {7: "ITEM-7"} if 7 in ids else {},
    )

    def stub(request):
        result = (
            {}
            if request.function == "items.detail.get"
            else {"item_id": 7, "to_status": "done"}
        )
        return _response(request, result)

    rc, out, err = _run_capture(
        stub,
        "lifecycle",
        "transition",
        "7",
        "--from",
        "reviewing-implementation",
        "--to",
        "done",
    )

    assert rc == 0, err
    assert json.loads(out) == {"public_ref": "ITEM-7", "to_status": "done"}


def test_deployment_run_create_falls_back_to_structured_receipt() -> None:
    def stub(request):
        return _response(request, {"status": "created"})

    with patch(
        "yoke_cli.commands.adapters.deployment_run_create."
        "https_product_plane_create_error",
        return_value=None,
    ):
        rc, out, err = _run_capture(
            stub, "deployment-runs", "create", "acme", "acme-prod"
        )

    assert rc == 0, err
    assert json.loads(out) == {"status": "created"}


def test_start_for_item_falls_back_to_structured_receipt() -> None:
    def stub(request):
        return _response(request, {"status": "created"})

    with patch(
        "yoke_cli.commands.adapters.deployment_composed."
        "https_product_plane_create_error",
        return_value=None,
    ):
        rc, out, err = _run_capture(stub, "deployment-runs", "start-for-item", "ITEM-7")

    assert rc == 0, err
    assert json.loads(out) == {"status": "created"}
