"""Credential-scoped boto3 clients for machine-local AWS authority.

The capability resolver owns credential selection and custody. Callers receive
an in-process SDK client configured with only the selected values; credentials
are never exported into the operator shell or included in diagnosed errors.

"Only the selected values" is enforced, not assumed: the client is built on a
botocore session with the shared config and credentials files detached, so the
operator's ambient AWS setup can neither answer a lookup the resolver owns nor
make a client build wait on the filesystem behind ``~/.aws``.
"""

from __future__ import annotations

import os
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


#: Overrides for the botocore session variables that would otherwise reach the
#: operator's ambient AWS setup. Each value is botocore's
#: ``(config_file_key, env_var_names, default, conversion_func)`` tuple, so
#: ``None`` for the env-var slot detaches the variable from the environment and
#: the third slot replaces botocore's ``~/.aws`` default. Credentials, region,
#: and timeouts all arrive from the capability resolver, so nothing here is a
#: lost input — but reading the shared files is an active hazard: on a machine
#: where ``~/.aws`` is a cloud-synced directory, materialising an evicted file
#: blocked a client build for minutes, and an ambient profile could silently
#: answer a lookup the resolver is supposed to own.
_DETACHED_SESSION_VARS: dict[str, tuple[None, None, Any, None]] = {
    "config_file": (None, None, os.devnull, None),
    "credentials_file": (None, None, os.devnull, None),
    "profile": (None, None, None, None),
}


def _isolated_botocore_session() -> Any:
    """Build a botocore session that consults no shared AWS config on disk."""
    from botocore.session import Session

    return Session(session_vars=dict(_DETACHED_SESSION_VARS))


def _boto3_client(service_name: str, **kwargs: Any) -> Any:
    import boto3

    session = boto3.Session(botocore_session=_isolated_botocore_session())
    return session.client(service_name, **kwargs)


__all__ = ["machine_aws_client", "safe_aws_error_reason"]
