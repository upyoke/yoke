"""Correlated and one-shot GitHub Actions workflow dispatch handlers.

The correlated handler delegates durable intent recovery to the workflow
dispatch domain owner.  The one-shot handler performs exactly one GitHub REST
POST for workflows that do not expose Yoke's correlation input.
"""

from __future__ import annotations

from typing import Any, Dict, Literal, Optional

from pydantic import BaseModel, Field, model_validator

from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionError,
    HandlerOutcome,
)
from yoke_contracts.github_app_installation_permissions import (
    GITHUB_ACTIONS_WRITE_PERMISSION_LEVELS,
)
from yoke_contracts.github_workflow_dispatch import (
    WORKFLOW_DISPATCH_CORRELATION_INPUT,
)
from yoke_core.domain.github_actions_identifiers import WorkflowIdentifier
from yoke_core.domain.handlers.github_actions_set import _validate_and_resolve


OWNER_MODULE = __name__


class WorkflowDispatchRequest(BaseModel):
    repo: str = Field(..., min_length=3)
    workflow: WorkflowIdentifier
    ref: str = Field("main", min_length=1)
    inputs: Dict[str, str] = Field(default_factory=dict)
    project: str = Field(..., min_length=1)
    correlation_input: Literal[WORKFLOW_DISPATCH_CORRELATION_INPUT]

    @model_validator(mode="after")
    def _correlation_input_is_reserved(self) -> "WorkflowDispatchRequest":
        if self.correlation_input in self.inputs:
            raise ValueError(
                f"inputs must not set reserved key {self.correlation_input!r}"
            )
        return self


class WorkflowDispatchOnceRequest(BaseModel):
    """Explicit non-retrying dispatch for workflows not yet correlation-aware."""

    repo: str = Field(..., min_length=3)
    workflow: WorkflowIdentifier
    ref: str = Field("main", min_length=1)
    inputs: Dict[str, str] = Field(default_factory=dict)
    project: str = Field(..., min_length=1)

    @model_validator(mode="after")
    def _reserved_input_is_forbidden(self) -> "WorkflowDispatchOnceRequest":
        if WORKFLOW_DISPATCH_CORRELATION_INPUT in self.inputs:
            raise ValueError(
                f"inputs must not set reserved key "
                f"{WORKFLOW_DISPATCH_CORRELATION_INPUT!r}"
            )
        return self


class WorkflowDispatchResponse(BaseModel):
    dispatched: bool
    run_id: str
    run_url: Optional[str] = None
    html_url: Optional[str] = None


def handle_workflow_dispatch(request: FunctionCallRequest) -> HandlerOutcome:
    payload, token, error = _validate_and_resolve(
        request,
        WorkflowDispatchRequest,
        "github_actions.workflow.dispatch",
        required_permissions=GITHUB_ACTIONS_WRITE_PERMISSION_LEVELS,
    )
    if error is not None:
        return error

    from yoke_core.domain.github_workflow_dispatch import (
        dispatch_workflow_with_intent,
    )

    return dispatch_workflow_with_intent(request, payload, token)


def handle_workflow_dispatch_once(request: FunctionCallRequest) -> HandlerOutcome:
    """Send exactly one POST with no durable replay or correlation contract."""
    payload, token, error = _validate_and_resolve(
        request,
        WorkflowDispatchOnceRequest,
        "github_actions.workflow.dispatch_once",
        required_permissions=GITHUB_ACTIONS_WRITE_PERMISSION_LEVELS,
    )
    if error is not None:
        return error

    from yoke_core.domain.gh_rest_transport import RestTransportError
    from yoke_core.domain.github_actions_rest import rest_post

    body: Dict[str, Any] = {
        "ref": payload.ref,
        "return_run_details": True,
    }
    if payload.inputs:
        body["inputs"] = dict(payload.inputs)
    try:
        result = rest_post(
            f"/repos/{payload.repo}/actions/workflows/{payload.workflow}/dispatches",
            body=body,
            token=token,
            max_attempts=1,
        )
    except RestTransportError as exc:
        definitive = exc.status is not None and 400 <= exc.status < 500
        return HandlerOutcome(
            primary_success=False,
            error=FunctionError(
                code=(
                    "workflow_dispatch_rejected"
                    if definitive
                    else "workflow_dispatch_ambiguous"
                ),
                message=(
                    f"GitHub definitively rejected one-shot workflow dispatch: {exc}"
                    if definitive
                    else "one-shot workflow dispatch response was lost; no retry "
                    "was sent because this workflow has no correlation contract"
                ),
            ),
        )
    if not isinstance(result, dict) or not result.get("workflow_run_id"):
        return HandlerOutcome(
            primary_success=False,
            error=FunctionError(
                code="workflow_dispatch_ambiguous",
                message=(
                    "one-shot workflow dispatch response omitted workflow_run_id; "
                    "no retry was sent because this workflow has no correlation "
                    "contract"
                ),
            ),
        )
    return HandlerOutcome(
        result_payload=WorkflowDispatchResponse(
            dispatched=True,
            run_id=str(result["workflow_run_id"]),
            run_url=str(result.get("run_url") or "") or None,
            html_url=str(result.get("html_url") or "") or None,
        ).model_dump(),
        primary_success=True,
    )


__all__ = [
    "OWNER_MODULE",
    "WorkflowDispatchOnceRequest",
    "WorkflowDispatchRequest",
    "WorkflowDispatchResponse",
    "handle_workflow_dispatch",
    "handle_workflow_dispatch_once",
]
