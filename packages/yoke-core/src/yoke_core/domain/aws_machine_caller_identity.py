"""Redacted AWS caller identity from a project's machine-local capability.

The capability resolver owns credential selection and custody. This module
passes only the selected values to boto3, asks STS who they represent, and
returns non-secret identity facts. Raw SDK exceptions are never surfaced: an
AWS error code or exception class is enough to diagnose the failure without
risking credential-bearing request state.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Callable, Mapping

from yoke_core.domain import deploy_remote

_CONNECT_TIMEOUT_SECONDS = 5
_READ_TIMEOUT_SECONDS = 15
_MAX_ATTEMPTS = 2
_SAFE_REASON = re.compile(r"^[A-Za-z][A-Za-z0-9._-]{0,127}$")


class CallerIdentityVerificationError(RuntimeError):
    """AWS caller identity could not be obtained without exposing secrets."""


@dataclass(frozen=True)
class CallerIdentity:
    """The non-secret facts returned by STS GetCallerIdentity."""

    account: str
    identity: str


def verify_machine_caller_identity(
    project_slug: str,
    region: str,
    *,
    client_factory: Callable[..., Any] | None = None,
) -> CallerIdentity:
    """Verify the selected machine credential through in-process boto3 STS."""
    try:
        env = deploy_remote.aws_machine_capability_env(project_slug, region)
        client_kwargs = _client_kwargs(env, region)
    except Exception as exc:  # noqa: BLE001 - converted to a safe named reason
        raise CallerIdentityVerificationError(
            f"Yoke could not prepare the stored AWS credentials ({_reason(exc)})."
        ) from exc

    try:
        factory = client_factory or _boto3_client
        client = factory("sts", **client_kwargs)
        payload = client.get_caller_identity()
    except Exception as exc:  # noqa: BLE001 - raw SDK state may contain secrets
        raise CallerIdentityVerificationError(
            f"Yoke could not verify the AWS credentials ({_reason(exc)})."
        ) from exc
    return _identity_from_payload(payload)


def _client_kwargs(env: Mapping[str, str], region: str) -> dict[str, Any]:
    access_key = _required(env, "AWS_ACCESS_KEY_ID")
    secret_key = _required(env, "AWS_SECRET_ACCESS_KEY")
    resolved_region = str(env.get("AWS_REGION") or region or "").strip()
    if not resolved_region:
        raise RuntimeError("AWS region is missing")
    kwargs: dict[str, Any] = {
        "aws_access_key_id": access_key,
        "aws_secret_access_key": secret_key,
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


def _identity_from_payload(payload: Any) -> CallerIdentity:
    if not isinstance(payload, Mapping):
        raise CallerIdentityVerificationError(
            "AWS returned an unreadable caller identity."
        )
    account = str(payload.get("Account") or "").strip()
    arn = str(payload.get("Arn") or "").strip()
    identity = arn.rsplit("/", 1)[-1] if arn else ""
    if not account or not identity:
        raise CallerIdentityVerificationError(
            "AWS returned an incomplete caller identity."
        )
    return CallerIdentity(account=account, identity=identity)


def _reason(exc: BaseException) -> str:
    response = getattr(exc, "response", None)
    if isinstance(response, Mapping):
        error = response.get("Error")
        if isinstance(error, Mapping):
            code = str(error.get("Code") or "").strip()
            if _SAFE_REASON.fullmatch(code):
                return code
    name = type(exc).__name__
    return name if _SAFE_REASON.fullmatch(name) else "verification-error"


__all__ = [
    "CallerIdentity",
    "CallerIdentityVerificationError",
    "verify_machine_caller_identity",
]
