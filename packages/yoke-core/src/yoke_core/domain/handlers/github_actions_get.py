"""Handler for ``github_actions.variable.get``.

Read-only bearer-token sibling of the ``github_actions.variable.set``
writer: confirms Actions repo-variable state (arming gates such as the
CI-enable flag) without mutating repo config and with no host GitHub
CLI binary. Surfaced because the write-only family left a self-skipped
workflow's gate state undiagnosable from the laptop.

Routes through
:func:`yoke_core.domain.github_variables_rest.get_repo_variable`;
shares the envelope/payload/auth gate with the set handlers.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from yoke_contracts.github_app_installation_permissions import (
    GITHUB_VARIABLES_READ_PERMISSION_LEVELS,
)
from yoke_core.domain.handlers.github_actions_set import (
    _transport_failed,
    _validate_and_resolve,
)
from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    HandlerOutcome,
)


class VariableGetRequest(BaseModel):
    repo: str = Field(..., min_length=3, description="GitHub repo slug (owner/name).")
    name: str = Field(..., min_length=1, description="Actions variable name.")
    project: str = Field(
        ..., min_length=1,
        description="Project capability owning the GitHub App repo binding.",
    )


class VariableGetResponse(BaseModel):
    repo: str
    name: str
    exists: bool
    value: Optional[str] = None  # None when the variable is absent


def handle_variable_get(request: FunctionCallRequest) -> HandlerOutcome:
    payload, token, err = _validate_and_resolve(
        request,
        VariableGetRequest,
        "github_actions.variable.get",
        required_permissions=GITHUB_VARIABLES_READ_PERMISSION_LEVELS,
    )
    if err is not None:
        return err

    from yoke_core.domain import github_variables_rest
    from yoke_core.domain.gh_rest_transport import RestTransportError

    try:
        value = github_variables_rest.get_repo_variable(
            payload.repo, payload.name, token=token,
        )
    except RestTransportError as exc:
        return _transport_failed(f"get_repo_variable failed: {exc}")

    response = VariableGetResponse(
        repo=payload.repo,
        name=payload.name,
        exists=value is not None,
        value=value,
    )
    return HandlerOutcome(
        result_payload=response.model_dump(),
        primary_success=True,
    )


REGISTRATIONS: List[Dict[str, Any]] = [
    {
        "function_id": "github_actions.variable.get",
        "handler": handle_variable_get,
        "request_model": VariableGetRequest,
        "response_model": VariableGetResponse,
        "stability": "stable",
        "owner_module": "yoke_core.domain.handlers.github_actions_get",
        "target_kinds": ["global"],
        "side_effects": [],
        "emitted_event_names": [],
        "guardrails": ["project_auth_required"],
        "adapter_status": "live",
        "claim_required_kind": None,
    },
]


__all__ = [
    "REGISTRATIONS",
    "VariableGetRequest",
    "VariableGetResponse",
    "handle_variable_get",
]
