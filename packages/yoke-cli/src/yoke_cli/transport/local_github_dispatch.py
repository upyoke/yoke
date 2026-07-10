"""Machine-local GitHub App authorization context for in-process dispatch."""

from __future__ import annotations

import importlib
from typing import Callable

from yoke_cli.config import machine_config
from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionCallResponse,
    FunctionError,
)
from yoke_contracts.github_origin import (
    GitHubApiOriginError,
    validate_github_api_endpoint,
)


def call_with_machine_github_authorization(
    request: FunctionCallRequest,
    local_dispatch: Callable[[FunctionCallRequest], FunctionCallResponse],
    *,
    core_available: bool,
) -> FunctionCallResponse:
    """Expose lazy machine user auth only to in-process core dispatch."""
    try:
        auth_module = importlib.import_module(
            "yoke_core.domain.project_github_auth"
        )
    except ImportError:
        if core_available:
            return _error(
                request,
                "local_postgres_core_unavailable",
                "the local yoke-core engine does not provide GitHub App "
                "authorization context",
                "Repair the install so yoke-cli and yoke-core are from "
                "the same release.",
            )
        return local_dispatch(request)

    config_error = ""
    try:
        github = machine_config.github_config()
        api_url = github.get("api_url") if isinstance(github, dict) else None
        endpoint = validate_github_api_endpoint(
            str(api_url).strip() if api_url else None
        )
    except (GitHubApiOriginError, machine_config.MachineConfigError) as exc:
        endpoint = validate_github_api_endpoint(None)
        config_error = str(exc)

    def _access_token() -> str:
        if config_error:
            raise RuntimeError(
                f"machine GitHub App configuration is invalid: {config_error}. "
                "Run `yoke github status`, then reconnect GitHub."
            )
        token_module = importlib.import_module(
            "yoke_cli.config.github_user_tokens"
        )
        return token_module.access_token_from_machine_config().access_token

    with auth_module.bind_local_github_user_token_provider(
        _access_token,
        api_url=endpoint,
    ):
        return local_dispatch(request)


def _error(
    request: FunctionCallRequest,
    code: str,
    message: str,
    recovery_hint: str,
) -> FunctionCallResponse:
    return FunctionCallResponse(
        success=False,
        function=request.function,
        version=request.version,
        request_id=request.request_id,
        error=FunctionError(
            code=code,
            message=message,
            recovery_hint=recovery_hint,
        ),
    )


__all__ = ["call_with_machine_github_authorization"]
