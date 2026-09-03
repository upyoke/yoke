"""Credential-scoped boto3 clients for machine-local AWS authority.

The capability resolver owns credential selection and custody. Callers receive
an in-process SDK client configured with only the selected values; credentials
are never exported into the operator shell or included in diagnosed errors.
"""

from __future__ import annotations

import re
from typing import Any, Callable, Mapping

from yoke_core.domain import deploy_remote

_CONNECT_TIMEOUT_SECONDS = 5
_READ_TIMEOUT_SECONDS = 15
_MAX_ATTEMPTS = 2
_SAFE_REASON = re.compile(r"^[A-Za-z][A-Za-z0-9._-]{0,127}$")


def machine_aws_client(
    service_name: str,
    project_slug: str,
    region: str,
    *,
    client_factory: Callable[..., Any] | None = None,
) -> Any:
    """Build a boto3 client from the project's machine-local capability."""
    env = deploy_remote.aws_machine_capability_env(project_slug, region)
    factory = client_factory or _boto3_client
    return factory(service_name, **_client_kwargs(env, region))


def safe_aws_error_reason(exc: BaseException) -> str:
    """Return an AWS code or exception class without request or secret state."""
    response = getattr(exc, "response", None)
    if isinstance(response, Mapping):
        error = response.get("Error")
        if isinstance(error, Mapping):
            code = str(error.get("Code") or "").strip()
            if _SAFE_REASON.fullmatch(code):
                return code
    name = type(exc).__name__
    return name if _SAFE_REASON.fullmatch(name) else "aws-operation-error"


def _client_kwargs(env: Mapping[str, str], region: str) -> dict[str, Any]:
    resolved_region = str(env.get("AWS_REGION") or region or "").strip()
    if not resolved_region:
        raise RuntimeError("AWS region is missing")
    kwargs: dict[str, Any] = {
        "aws_access_key_id": _required(env, "AWS_ACCESS_KEY_ID"),
        "aws_secret_access_key": _required(env, "AWS_SECRET_ACCESS_KEY"),
        "region_name": resolved_region,
        "config": _client_config(),
    }
    session_token = str(env.get("AWS_SESSION_TOKEN") or "").strip()
    if session_token:
        kwargs["aws_session_token"] = session_token
    return kwargs


def _required(env: Mapping[str, str], name: str) -> str:
    value = str(env.get(name) or "").strip()
    if not value:
        raise RuntimeError(f"{name} is missing")
    return value


def _client_config() -> Any:
    from botocore.config import Config

    return Config(
        connect_timeout=_CONNECT_TIMEOUT_SECONDS,
        read_timeout=_READ_TIMEOUT_SECONDS,
        retries={"max_attempts": _MAX_ATTEMPTS, "mode": "standard"},
    )


def _boto3_client(service_name: str, **kwargs: Any) -> Any:
    import boto3

    return boto3.client(service_name, **kwargs)


__all__ = ["machine_aws_client", "safe_aws_error_reason"]
