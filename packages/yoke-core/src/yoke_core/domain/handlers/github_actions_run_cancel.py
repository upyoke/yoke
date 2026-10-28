"""Handler for ``github_actions.run.cancel``.

Cancels one workflow run in the project's bound repository with the project's
GitHub App authority. A release workflow uses it to stop the downstream run it
dispatched when it is itself cancelled or failing, so the downstream run does
not deploy later on its own.
"""

from __future__ import annotations

from typing import Any, Dict, List

from pydantic import BaseModel, Field
from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionError,
    HandlerOutcome,
)
from yoke_contracts.github_app_installation_permissions import (
    GITHUB_ACTIONS_WRITE_PERMISSION_LEVELS,
)
from yoke_contracts.refusal_recovery import compose_refusal

from yoke_core.domain.github_actions_identifiers import WorkflowRunId
from yoke_core.domain.handlers.github_actions_set import _validate_and_resolve

FUNCTION_ID = "github_actions.run.cancel"


class RunCancelRequest(BaseModel):
    repo: str = Field(..., min_length=3, description="GitHub repo slug (owner/name).")
    run_id: WorkflowRunId = Field(..., description="GitHub Actions run id.")
    project: str = Field(
        ...,
        min_length=1,
        description="Project capability owning the GitHub App repo binding.",
    )


class RunCancelResponse(BaseModel):
    repo: str
    run_id: str
    #: ``cancel_requested`` or ``already_completed``.
    outcome: str


def handle_run_cancel(request: FunctionCallRequest) -> HandlerOutcome:
    payload, token, error = _validate_and_resolve(
        request,
        RunCancelRequest,
        FUNCTION_ID,
        required_permissions=GITHUB_ACTIONS_WRITE_PERMISSION_LEVELS,
    )
    if error is not None:
        return error

    from yoke_core.domain.github_actions_run_cancel import RunCancelError, cancel_run

    try:
        outcome = cancel_run(repo=payload.repo, run_id=str(payload.run_id), token=token)
    except RunCancelError as exc:
        return HandlerOutcome(
            result_payload={},
            primary_success=False,
            error=FunctionError(
                code="workflow_run_cancel_refused",
                message=(
                    compose_refusal(
                        f"{exc}.",
                        recovery=(
                            "open the run in GitHub and cancel it there. A QA case gate force-cancels "
                            "a run that never starts and redispatches it."
                        ),
                    )
                ),
            ),
        )
    return HandlerOutcome(
        result_payload=RunCancelResponse(
            repo=payload.repo, run_id=str(payload.run_id), outcome=outcome
        ).model_dump(),
        primary_success=True,
    )


REGISTRATIONS: List[Dict[str, Any]] = [
    {
        "function_id": FUNCTION_ID,
        "handler": handle_run_cancel,
        "request_model": RunCancelRequest,
        "response_model": RunCancelResponse,
        "stability": "stable",
        "owner_module": __name__,
        "target_kinds": ["global"],
        "side_effects": ["github:cancel_workflow_run"],
        "emitted_event_names": [],
        "guardrails": ["project_auth_required"],
        "adapter_status": "live",
        "claim_required_kind": None,
        "ambient_session_required": False,
        "minimum_serving_version": "next-release",
    },
]


__all__ = [
    "FUNCTION_ID",
    "REGISTRATIONS",
    "RunCancelRequest",
    "RunCancelResponse",
    "handle_run_cancel",
]
