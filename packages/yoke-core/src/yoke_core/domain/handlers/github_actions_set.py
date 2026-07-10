"""Handlers for ``github_actions.secret.set`` / ``github_actions.variable.set``.

bearer-token GitHub Actions repo-config writers so CI arming and
rotation recipes run with no host GitHub CLI binary:

- ``github_actions.secret.set`` routes through
  :func:`yoke_core.domain.github_secrets_rest.set_repo_secret`
  (libsodium sealed-box encryption against the repo public key).
- ``github_actions.variable.set`` routes through
  :func:`yoke_core.domain.github_variables_rest.set_repo_variable`
  (PATCH-then-POST upsert).

Secret hygiene: the secret value travels only inside the function-call
payload (the dispatcher records payload byte count + sha256 checksum,
never the payload body). Neither handler echoes the value into result
payloads or error messages, and payload validation errors are
sanitized (``ValidationError.errors(include_input=False)``) so pydantic
never reflects a rejected input value back to the caller.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Tuple, Type

from pydantic import BaseModel, Field, ValidationError

from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionError,
    HandlerOutcome,
)
from yoke_contracts.github_app_installation_permissions import (
    GITHUB_SECRETS_WRITE_PERMISSION_LEVELS,
    GITHUB_VARIABLES_WRITE_PERMISSION_LEVELS,
)


class SecretSetRequest(BaseModel):
    repo: str = Field(..., min_length=3, description="GitHub repo slug (owner/name).")
    name: str = Field(..., min_length=1, description="Actions secret name.")
    value: str = Field(
        ..., min_length=1,
        description="Secret value; never logged, never echoed in responses.",
    )
    project: str = Field(
        ...,
        min_length=1,
        description="Project capability owning the GitHub App repo binding.",
    )


class SecretSetResponse(BaseModel):
    repo: str
    name: str
    result: str  # always "set" — the REST PUT is create-or-update


class VariableSetRequest(BaseModel):
    repo: str = Field(..., min_length=3, description="GitHub repo slug (owner/name).")
    name: str = Field(..., min_length=1, description="Actions variable name.")
    value: str = Field(..., description="Variable value (non-secret plaintext).")
    project: str = Field(
        ...,
        min_length=1,
        description="Project capability owning the GitHub App repo binding.",
    )


class VariableSetResponse(BaseModel):
    repo: str
    name: str
    result: str  # "created" | "updated"


def _bad_request(message: str, *, jsonpath: str = "$.payload") -> HandlerOutcome:
    return HandlerOutcome(
        result_payload={},
        primary_success=False,
        error=FunctionError(
            code="invalid_payload", message=message, jsonpath=jsonpath,
        ),
    )


def _auth_failed(message: str, *, repair_hint: str = "") -> HandlerOutcome:
    full = f"{message}\n  Repair: {repair_hint}" if repair_hint else message
    return HandlerOutcome(
        result_payload={},
        primary_success=False,
        error=FunctionError(code="project_auth_error", message=full),
    )


def _transport_failed(message: str) -> HandlerOutcome:
    return HandlerOutcome(
        result_payload={},
        primary_success=False,
        error=FunctionError(code="rest_transport_error", message=message),
    )


def _sanitized_validation_message(exc: ValidationError) -> str:
    """Render a ValidationError without reflecting input values back."""
    parts: List[str] = []
    for err in exc.errors(include_url=False, include_input=False):
        loc = ".".join(str(p) for p in err.get("loc", ())) or "$"
        parts.append(f"{loc}: {err.get('msg', 'invalid')}")
    return "payload invalid: " + "; ".join(parts)


def _validate_and_resolve(
    request: FunctionCallRequest,
    model: Type[BaseModel],
    function_id: str,
    *,
    required_permissions: Mapping[str, str],
) -> Tuple[Optional[Any], Optional[str], Optional[HandlerOutcome]]:
    """Shared envelope/payload/auth gate for both set handlers.

    Returns ``(payload, token, error_outcome)`` — exactly one of
    ``payload``/``error_outcome`` is set; ``token`` accompanies a
    successful payload.
    """
    payload, resolved, error = _validate_and_resolve_auth(
        request,
        model,
        function_id,
        required_permissions=required_permissions,
    )
    if error is not None:
        return None, None, error
    assert resolved is not None
    return payload, resolved.token, None


def _validate_and_resolve_auth(
    request: FunctionCallRequest,
    model: Type[BaseModel],
    function_id: str,
    *,
    required_permissions: Mapping[str, str],
    missing_permission_error: HandlerOutcome | None = None,
) -> Tuple[Optional[Any], Optional[Any], Optional[HandlerOutcome]]:
    """Validate a GitHub handler request and retain resolved auth metadata."""
    if request.target.kind != "global":
        return None, None, _bad_request(
            f"target.kind must be 'global' ({function_id} has no item binding)",
            jsonpath="$.target.kind",
        )

    try:
        payload = model.model_validate(request.payload or {})
    except ValidationError as exc:
        return None, None, _bad_request(_sanitized_validation_message(exc))

    repo = getattr(payload, "repo", None)
    if repo is not None and "/" not in repo:
        return None, None, _bad_request(
            f"repo must be owner/name, got {repo!r}",
            jsonpath="$.payload.repo",
        )

    from yoke_core.domain.project_github_auth import (
        MissingPermission,
        ProjectGithubAuthError,
        repair_command_hint,
        resolve_project_github_auth,
    )

    try:
        resolved = resolve_project_github_auth(
            payload.project,
            required_permissions=required_permissions,
        )
    except MissingPermission as exc:
        if missing_permission_error is not None:
            return None, None, missing_permission_error
        return None, None, _auth_failed(
            f"{exc.code}: {exc}",
            repair_hint=repair_command_hint(exc, payload.project),
        )
    except ProjectGithubAuthError as exc:
        return None, None, _auth_failed(
            f"{exc.code}: {exc}",
            repair_hint=repair_command_hint(exc, payload.project),
        )
    if repo is not None and repo.casefold() != resolved.repo.casefold():
        return None, None, _bad_request(
            f"repo must match project binding {resolved.repo!r}",
            jsonpath="$.payload.repo",
        )
    return payload, resolved, None


def handle_secret_set(request: FunctionCallRequest) -> HandlerOutcome:
    payload, token, err = _validate_and_resolve(
        request,
        SecretSetRequest,
        "github_actions.secret.set",
        required_permissions=GITHUB_SECRETS_WRITE_PERMISSION_LEVELS,
    )
    if err is not None:
        return err

    from yoke_core.domain import github_secrets_rest
    from yoke_core.domain.gh_rest_transport import RestTransportError

    try:
        github_secrets_rest.set_repo_secret(
            payload.repo, payload.name, payload.value, token=token,
        )
    except RestTransportError as exc:
        return _transport_failed(f"set_repo_secret failed: {exc}")

    response = SecretSetResponse(repo=payload.repo, name=payload.name, result="set")
    return HandlerOutcome(
        result_payload=response.model_dump(),
        primary_success=True,
    )


def handle_variable_set(request: FunctionCallRequest) -> HandlerOutcome:
    payload, token, err = _validate_and_resolve(
        request,
        VariableSetRequest,
        "github_actions.variable.set",
        required_permissions=GITHUB_VARIABLES_WRITE_PERMISSION_LEVELS,
    )
    if err is not None:
        return err

    from yoke_core.domain import github_variables_rest
    from yoke_core.domain.gh_rest_transport import RestTransportError

    try:
        outcome = github_variables_rest.set_repo_variable(
            payload.repo, payload.name, payload.value, token=token,
        )
    except RestTransportError as exc:
        return _transport_failed(f"set_repo_variable failed: {exc}")

    response = VariableSetResponse(
        repo=payload.repo, name=payload.name, result=outcome,
    )
    return HandlerOutcome(
        result_payload=response.model_dump(),
        primary_success=True,
    )


REGISTRATIONS: List[Dict[str, Any]] = [
    {
        "function_id": "github_actions.secret.set",
        "handler": handle_secret_set,
        "request_model": SecretSetRequest,
        "response_model": SecretSetResponse,
        "stability": "stable",
        "owner_module": "yoke_core.domain.handlers.github_actions_set",
        "target_kinds": ["global"],
        "side_effects": ["github_actions_config_write"],
        "emitted_event_names": [],
        "guardrails": ["project_auth_required"],
        "adapter_status": "live",
        "claim_required_kind": None,
    },
    {
        "function_id": "github_actions.variable.set",
        "handler": handle_variable_set,
        "request_model": VariableSetRequest,
        "response_model": VariableSetResponse,
        "stability": "stable",
        "owner_module": "yoke_core.domain.handlers.github_actions_set",
        "target_kinds": ["global"],
        "side_effects": ["github_actions_config_write"],
        "emitted_event_names": [],
        "guardrails": ["project_auth_required"],
        "adapter_status": "live",
        "claim_required_kind": None,
    },
]


__all__ = [
    "REGISTRATIONS",
    "SecretSetRequest",
    "SecretSetResponse",
    "VariableSetRequest",
    "VariableSetResponse",
    "handle_secret_set",
    "handle_variable_set",
]
