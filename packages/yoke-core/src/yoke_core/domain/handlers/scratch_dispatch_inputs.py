"""Handler for ``scratch.dispatch_inputs``.

Resolves the per-dispatch dispatch-inputs directory through the
project-scoped scratch helper. The handler is a thin read-only resolver
— no events are emitted, no claim is required, and the returned path
is the helper-computed absolute path.
"""

from __future__ import annotations

from typing import Any, Dict, List

from pydantic import BaseModel, Field

from yoke_core.domain.project_scratch_dir import (
    dispatch_inputs_dir,
    resolve_active_project,
)
from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionError,
    HandlerOutcome,
)


class DispatchInputsRequest(BaseModel):
    item_id: int = Field(..., description="Bare integer item id (YOK-N's numeric tail).")
    session_id: str = Field(..., min_length=1, description="Harness session id.")
    attempt: int = Field(..., ge=1, description="Per-dispatch attempt counter (1-based).")


class DispatchInputsResponse(BaseModel):
    path: str = Field(..., description="Absolute filesystem path to the dispatch-inputs directory.")


def _bad_request(message: str) -> HandlerOutcome:
    return HandlerOutcome(
        result_payload={},
        primary_success=False,
        error=FunctionError(code="invalid_payload", message=message),
    )


def handle_dispatch_inputs(request: FunctionCallRequest) -> HandlerOutcome:
    """Resolve the dispatch-inputs directory for the requested dispatch."""

    if request.target.kind != "global":
        return _bad_request("target.kind must be 'global'")

    try:
        payload = DispatchInputsRequest.model_validate(request.payload)
    except Exception as exc:
        return _bad_request(f"payload invalid: {exc}")

    project = resolve_active_project()
    path = dispatch_inputs_dir(
        project, payload.item_id, payload.session_id, payload.attempt,
    )
    response = DispatchInputsResponse(path=str(path))
    return HandlerOutcome(
        result_payload=response.model_dump(),
        primary_success=True,
    )


REGISTRATIONS: List[Dict[str, Any]] = [
    {
        "function_id": "scratch.dispatch_inputs",
        "handler": handle_dispatch_inputs,
        "request_model": DispatchInputsRequest,
        "response_model": DispatchInputsResponse,
        "stability": "stable",
        "owner_module": "yoke_core.domain.project_scratch_dir",
        "target_kinds": ["global"],
        "side_effects": [],
        "emitted_event_names": [],
        "guardrails": [],
        "adapter_status": "live",
        "claim_required_kind": None,
    },
]


__all__ = [
    "DispatchInputsRequest",
    "DispatchInputsResponse",
    "REGISTRATIONS",
    "handle_dispatch_inputs",
]
