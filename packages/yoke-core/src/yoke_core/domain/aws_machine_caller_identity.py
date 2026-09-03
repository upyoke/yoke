"""Redacted AWS caller identity from a project's machine-local capability.

The capability resolver owns credential selection and custody. This module
passes only the selected values to boto3, asks STS who they represent, and
returns non-secret identity facts. Raw SDK exceptions are never surfaced: an
AWS error code or exception class is enough to diagnose the failure without
risking credential-bearing request state.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping

from yoke_core.domain import aws_machine_client


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
        client = aws_machine_client.machine_aws_client(
            "sts",
            project_slug,
            region,
            client_factory=client_factory,
        )
    except Exception as exc:  # noqa: BLE001 - converted to a safe named reason
        raise CallerIdentityVerificationError(
            "Yoke could not prepare the stored AWS credentials "
            f"({aws_machine_client.safe_aws_error_reason(exc)})."
        ) from exc

    try:
        payload = client.get_caller_identity()
    except Exception as exc:  # noqa: BLE001 - raw SDK state may contain secrets
        raise CallerIdentityVerificationError(
            "Yoke could not verify the AWS credentials "
            f"({aws_machine_client.safe_aws_error_reason(exc)})."
        ) from exc
    return _identity_from_payload(payload)


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


__all__ = [
    "CallerIdentity",
    "CallerIdentityVerificationError",
    "verify_machine_caller_identity",
]
