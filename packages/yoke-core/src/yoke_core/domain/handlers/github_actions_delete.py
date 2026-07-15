"""Authenticated GitHub Actions secret/variable retirement handlers."""

from __future__ import annotations

from importlib import import_module
from typing import Any, Dict, List, Mapping

from pydantic import BaseModel, Field

from yoke_contracts.api.function_call import FunctionCallRequest, HandlerOutcome
from yoke_contracts.github_app_installation_permissions import (
    GITHUB_SECRETS_WRITE_PERMISSION_LEVELS,
    GITHUB_VARIABLES_WRITE_PERMISSION_LEVELS,
)
from yoke_core.domain.github_actions_identifiers import (
    CONFIG_NAME_PATTERN,
)


class ConfigDeleteRequest(BaseModel):
    repo: str = Field(..., min_length=3)
    name: str = Field(..., pattern=CONFIG_NAME_PATTERN)
    project: str = Field(..., min_length=1)


class ConfigDeleteResponse(BaseModel):
    repo: str
    name: str
    result: str


def handle_secret_delete(request: FunctionCallRequest) -> HandlerOutcome:
    return _handle_delete(
        request,
        function_id="github_actions.secret.delete",
        required_permissions=GITHUB_SECRETS_WRITE_PERMISSION_LEVELS,
        module_name="github_secrets_rest",
        operation_name="delete_repo_secret",
    )


def handle_variable_delete(request: FunctionCallRequest) -> HandlerOutcome:
    return _handle_delete(
        request,
        function_id="github_actions.variable.delete",
        required_permissions=GITHUB_VARIABLES_WRITE_PERMISSION_LEVELS,
        module_name="github_variables_rest",
        operation_name="delete_repo_variable",
    )


def _handle_delete(
    request: FunctionCallRequest,
    *,
    function_id: str,
    required_permissions: Mapping[str, str],
    module_name: str,
    operation_name: str,
) -> HandlerOutcome:
    from yoke_core.domain.handlers.github_actions_set import (
        _transport_failed,
        _validate_and_resolve,
    )
    payload, token, err = _validate_and_resolve(
        request,
        ConfigDeleteRequest,
        function_id,
        required_permissions=required_permissions,
    )
    if err is not None:
        return err
    from yoke_core.domain.gh_rest_transport import RestTransportError

    try:
        getattr(import_module(f"yoke_core.domain.{module_name}"), operation_name)(
            payload.repo, payload.name, token=token,
        )
    except RestTransportError as exc:
        return _transport_failed(f"{operation_name} failed: {exc}")
    response = ConfigDeleteResponse(
        repo=payload.repo, name=payload.name, result="deleted",
    )
    return HandlerOutcome(result_payload=response.model_dump(), primary_success=True)


def _registration(function_id: str, handler: Any) -> Dict[str, Any]:
    return {
        "function_id": function_id,
        "handler": handler,
        "request_model": ConfigDeleteRequest,
        "response_model": ConfigDeleteResponse,
        "stability": "stable",
        "owner_module": __name__,
        "target_kinds": ["global"],
        "side_effects": ["github_actions_config_write"],
        "emitted_event_names": [],
        "guardrails": ["project_auth_required"],
        "adapter_status": "live",
        "claim_required_kind": None,
    }


REGISTRATIONS: List[Dict[str, Any]] = [
    _registration("github_actions.secret.delete", handle_secret_delete),
    _registration("github_actions.variable.delete", handle_variable_delete),
]


__all__ = [
    "REGISTRATIONS", "ConfigDeleteRequest", "ConfigDeleteResponse",
    "handle_secret_delete", "handle_variable_delete",
]
