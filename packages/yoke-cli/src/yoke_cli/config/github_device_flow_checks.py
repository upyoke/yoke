"""Checks on GitHub's device-authorization answers, and the flow's one error."""

from __future__ import annotations

import re
from typing import Any, Mapping

from yoke_cli.config import github_response_safety
from yoke_contracts import github_app_tokens as token_contract
from yoke_contracts import github_origin

_USER_CODE = re.compile(r"[A-Z0-9]{4}-[A-Z0-9]{4}")
_MAX_VERIFICATION_URI_CHARS = 2_048


class GitHubDeviceFlowError(RuntimeError):
    """GitHub App device authorization could not complete."""


def raise_initial_oauth_error(
    payload: Mapping[str, Any],
    *,
    client_id: str,
) -> None:
    raw_error_code = str(payload.get("error") or "").strip()
    if not raw_error_code:
        return
    error_code = github_response_safety.safe_oauth_error_code(
        raw_error_code,
        secrets=(client_id,),
    )
    description = github_response_safety.safe_error_text(
        payload.get("error_description") or error_code,
        secrets=(client_id,),
    )
    raise GitHubDeviceFlowError(
        f"GitHub device authorization is unavailable ({error_code}): "
        f"{description}. {token_contract.GITHUB_APP_USER_AUTH_CONFIGURATION_HINT}"
    )


def validate_expiring_token_response(payload: Mapping[str, Any]) -> None:
    try:
        required_string(payload.get("access_token"), "access_token")
        required_string(payload.get("refresh_token"), "refresh_token")
        bounded_positive_seconds(
            payload.get("expires_in"),
            maximum=token_contract.GITHUB_APP_USER_ACCESS_TOKEN_MAX_SECONDS,
        )
        bounded_positive_seconds(
            payload.get("refresh_token_expires_in"),
            maximum=token_contract.GITHUB_APP_USER_REFRESH_TOKEN_MAX_SECONDS,
        )
    except (GitHubDeviceFlowError, TypeError, ValueError) as exc:
        raise GitHubDeviceFlowError(
            "GitHub did not return an expiring, refreshable App user token. "
            f"{token_contract.GITHUB_APP_USER_AUTH_CONFIGURATION_HINT}"
        ) from exc


def same_origin_verification_uri(value: Any, *, expected_origin: str) -> str:
    candidate = str(value or "").strip()
    if (
        len(candidate) > _MAX_VERIFICATION_URI_CHARS
        or github_response_safety.terminal_safe_text(
            candidate,
            maximum_chars=len(candidate),
        )
        != candidate
    ):
        raise GitHubDeviceFlowError(
            "verification_uri contains unsupported characters or is too long"
        )
    try:
        endpoint = github_origin.validate_github_web_endpoint(candidate)
    except github_origin.GitHubApiOriginError as exc:
        raise GitHubDeviceFlowError(
            "verification_uri must be an HTTPS GitHub URL"
        ) from exc
    if endpoint.origin != expected_origin:
        raise GitHubDeviceFlowError(
            "GitHub device verification URI crossed the configured web origin"
        )
    return endpoint.base_url


def validated_user_code(value: Any) -> str:
    code = required_string(value, "user_code", maximum_chars=9)
    if _USER_CODE.fullmatch(code) is None:
        raise GitHubDeviceFlowError(
            "GitHub device authorization user_code has an invalid format"
        )
    return code


def required_string(
    value: Any,
    label: str,
    *,
    maximum_chars: int | None = None,
) -> str:
    if not isinstance(value, str):
        raise GitHubDeviceFlowError(f"{label} must be a string")
    text = value.strip()
    if not text:
        raise GitHubDeviceFlowError(f"{label} is required")
    if maximum_chars is not None and len(text) > maximum_chars:
        raise GitHubDeviceFlowError(f"{label} is too long")
    return text


def bounded_positive_seconds(value: Any, *, maximum: int) -> int:
    if isinstance(value, bool):
        raise ValueError("timing")
    seconds = int(value)
    if seconds <= 0 or seconds > maximum:
        raise ValueError("timing")
    return seconds


__all__ = [
    "GitHubDeviceFlowError",
    "bounded_positive_seconds",
    "raise_initial_oauth_error",
    "required_string",
    "same_origin_verification_uri",
    "validate_expiring_token_response",
    "validated_user_code",
]
