"""GitHub App device authorization with browser-assisted polling."""

from __future__ import annotations

from dataclasses import dataclass, field
import re
import time
from typing import Any, Callable, Mapping
import urllib.request
import webbrowser

from yoke_cli.config import github_git_credential_store as credential_store
from yoke_cli.config import github_device_transport
from yoke_cli.config import github_response_safety
from yoke_contracts import github_app_tokens as token_contract
from yoke_contracts import github_origin


_USER_CODE = re.compile(r"[A-Z0-9]{4}-[A-Z0-9]{4}")
_MAX_VERIFICATION_URI_CHARS = 2_048
_MAX_DEVICE_CODE_CHARS = 1_024


class GitHubDeviceFlowError(RuntimeError):
    """GitHub App device authorization could not complete."""


@dataclass(frozen=True)
class DeviceAuthorization:
    device_code: str = field(repr=False)
    user_code: str
    verification_uri: str
    expires_in: int
    interval: int

    def public_dict(self) -> dict[str, Any]:
        return {
            "user_code": self.user_code,
            "verification_uri": self.verification_uri,
            "expires_in": self.expires_in,
            "interval": self.interval,
        }


@dataclass(frozen=True)
class DeviceFlowResult:
    token_response: dict[str, Any] = field(repr=False)
    authorization: DeviceAuthorization
    browser_opened: bool


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_urlopen = urllib.request.build_opener(_NoRedirectHandler()).open


def authorize(
    *,
    client_id: str,
    web_url: str,
    opener: Callable[..., Any] | None = None,
    browser_open: Callable[[str], Any] | None = None,
    notify: Callable[[Mapping[str, Any]], None] | None = None,
    sleep: Callable[[float], None] = time.sleep,
    monotonic: Callable[[], float] = time.monotonic,
    timeout_seconds: float = 30.0,
) -> DeviceFlowResult:
    """Authorize a GitHub App user and return its expiring token response."""
    selected_client_id = _required_string(client_id, "client_id")
    base = credential_store.validated_web_url(web_url)
    configured_origin = github_origin.validate_github_web_endpoint(base).origin
    try:
        payload = github_device_transport.post_form(
            f"{base}{token_contract.GITHUB_OAUTH_DEVICE_CODE_PATH}",
            {"client_id": selected_client_id}, opener=opener or _urlopen,
            timeout_seconds=timeout_seconds,
            deadline=monotonic() + timeout_seconds,
            monotonic=monotonic,
            error_type=GitHubDeviceFlowError,
        )
    except GitHubDeviceFlowError as exc:
        raise GitHubDeviceFlowError(
            f"{exc}. {token_contract.GITHUB_APP_USER_AUTH_CONFIGURATION_HINT}"
        ) from exc
    _raise_initial_oauth_error(payload, client_id=selected_client_id)
    authorization = _parse_authorization(
        payload, expected_origin=configured_origin
    )
    if notify is not None:
        notify({"phase": "device_authorization", **authorization.public_dict()})
    browser_opened = _open_browser(
        authorization.verification_uri, browser_open or webbrowser.open
    )
    if notify is not None:
        notify({
            "phase": "device_browser",
            "browser_opened": browser_opened,
            **authorization.public_dict(),
        })
    token_response = _poll_for_token(
        authorization,
        client_id=selected_client_id,
        token_url=(
            f"{base}{token_contract.GITHUB_OAUTH_ACCESS_TOKEN_PATH}"
        ),
        opener=opener,
        sleep=sleep,
        monotonic=monotonic,
        timeout_seconds=timeout_seconds,
    )
    return DeviceFlowResult(token_response, authorization, browser_opened)


def _poll_for_token(
    authorization: DeviceAuthorization,
    *,
    client_id: str,
    token_url: str,
    opener: Callable[..., Any] | None,
    sleep: Callable[[float], None],
    monotonic: Callable[[], float],
    timeout_seconds: float,
) -> dict[str, Any]:
    interval = authorization.interval
    deadline = monotonic() + authorization.expires_in
    while True:
        remaining = deadline - monotonic()
        if remaining <= 0:
            break
        sleep(min(interval, remaining))
        remaining = deadline - monotonic()
        if remaining <= 0:
            break
        try:
            payload = github_device_transport.post_form(
                token_url,
                {
                    "client_id": client_id,
                    "device_code": authorization.device_code,
                    "grant_type": token_contract.GITHUB_OAUTH_DEVICE_GRANT_TYPE,
                },
                opener=opener or _urlopen,
                timeout_seconds=min(timeout_seconds, remaining),
                deadline=deadline,
                monotonic=monotonic,
                error_type=GitHubDeviceFlowError,
            )
        except GitHubDeviceFlowError as exc:
            raise GitHubDeviceFlowError(
                github_response_safety.safe_error_text(
                    exc,
                    secrets=(authorization.device_code, authorization.user_code),
                )
            ) from exc
        raw_error_code = str(payload.get("error") or "").strip()
        if not raw_error_code:
            _validate_expiring_token_response(payload)
            return payload
        error_code = github_response_safety.safe_oauth_error_code(
            raw_error_code,
            secrets=(authorization.device_code, authorization.user_code, client_id),
        )
        if error_code == "authorization_pending":
            continue
        if error_code == "slow_down":
            interval = min(
                interval + token_contract.GITHUB_OAUTH_SLOW_DOWN_SECONDS,
                token_contract.GITHUB_OAUTH_POLL_INTERVAL_MAX_SECONDS,
            )
            continue
        description = github_response_safety.safe_error_text(
            payload.get("error_description") or error_code,
            secrets=(
                authorization.device_code, authorization.user_code, client_id,
            ),
        )
        raise GitHubDeviceFlowError(
            f"GitHub device authorization failed ({error_code}): {description}"
        )
    raise GitHubDeviceFlowError("GitHub device authorization expired")


def _parse_authorization(
    payload: Mapping[str, Any], *, expected_origin: str,
) -> DeviceAuthorization:
    if isinstance(payload.get("expires_in"), bool) or isinstance(
        payload.get("interval"), bool
    ):
        raise GitHubDeviceFlowError(
            "GitHub device authorization timing is invalid"
        )
    try:
        expires_in = int(payload.get("expires_in"))
        interval = int(payload.get("interval") or 5)
    except (TypeError, ValueError) as exc:
        raise GitHubDeviceFlowError(
            "GitHub device authorization timing is invalid"
        ) from exc
    if expires_in <= 0 or interval <= 0:
        raise GitHubDeviceFlowError(
            "GitHub device authorization timing must be positive"
        )
    if (
        expires_in > token_contract.GITHUB_OAUTH_DEVICE_CODE_MAX_SECONDS
        or interval > token_contract.GITHUB_OAUTH_POLL_INTERVAL_MAX_SECONDS
    ):
        raise GitHubDeviceFlowError(
            "GitHub device authorization timing exceeds supported limits"
        )
    verification_uri = _same_origin_verification_uri(
        payload.get("verification_uri"), expected_origin=expected_origin
    )
    return DeviceAuthorization(
        device_code=_required_string(
            payload.get("device_code"), "device_code",
            maximum_chars=_MAX_DEVICE_CODE_CHARS,
        ),
        user_code=_validated_user_code(payload.get("user_code")),
        verification_uri=verification_uri,
        expires_in=expires_in,
        interval=interval,
    )


def _raise_initial_oauth_error(
    payload: Mapping[str, Any], *, client_id: str,
) -> None:
    raw_error_code = str(payload.get("error") or "").strip()
    if not raw_error_code:
        return
    error_code = github_response_safety.safe_oauth_error_code(
        raw_error_code, secrets=(client_id,),
    )
    description = github_response_safety.safe_error_text(
        payload.get("error_description") or error_code,
        secrets=(client_id,),
    )
    raise GitHubDeviceFlowError(
        f"GitHub device authorization is unavailable ({error_code}): "
        f"{description}. {token_contract.GITHUB_APP_USER_AUTH_CONFIGURATION_HINT}"
    )


def _validate_expiring_token_response(payload: Mapping[str, Any]) -> None:
    try:
        _required_string(payload.get("access_token"), "access_token")
        _required_string(payload.get("refresh_token"), "refresh_token")
        _bounded_positive_seconds(
            payload.get("expires_in"),
            maximum=token_contract.GITHUB_APP_USER_ACCESS_TOKEN_MAX_SECONDS,
        )
        _bounded_positive_seconds(
            payload.get("refresh_token_expires_in"),
            maximum=token_contract.GITHUB_APP_USER_REFRESH_TOKEN_MAX_SECONDS,
        )
    except (GitHubDeviceFlowError, TypeError, ValueError) as exc:
        raise GitHubDeviceFlowError(
            "GitHub did not return an expiring, refreshable App user token. "
            f"{token_contract.GITHUB_APP_USER_AUTH_CONFIGURATION_HINT}"
        ) from exc


def _open_browser(url: str, browser_open: Callable[[str], Any]) -> bool:
    try:
        return bool(browser_open(url))
    except Exception:
        return False


def _same_origin_verification_uri(value: Any, *, expected_origin: str) -> str:
    candidate = str(value or "").strip()
    if (
        len(candidate) > _MAX_VERIFICATION_URI_CHARS
        or github_response_safety.terminal_safe_text(
            candidate, maximum_chars=len(candidate),
        ) != candidate
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


def _validated_user_code(value: Any) -> str:
    code = _required_string(value, "user_code", maximum_chars=9)
    if _USER_CODE.fullmatch(code) is None:
        raise GitHubDeviceFlowError(
            "GitHub device authorization user_code has an invalid format"
        )
    return code


def _required_string(
    value: Any, label: str, *, maximum_chars: int | None = None,
) -> str:
    if not isinstance(value, str):
        raise GitHubDeviceFlowError(f"{label} must be a string")
    text = value.strip()
    if not text:
        raise GitHubDeviceFlowError(f"{label} is required")
    if maximum_chars is not None and len(text) > maximum_chars:
        raise GitHubDeviceFlowError(f"{label} is too long")
    return text


def _bounded_positive_seconds(value: Any, *, maximum: int) -> int:
    if isinstance(value, bool):
        raise ValueError("timing")
    seconds = int(value)
    if seconds <= 0 or seconds > maximum:
        raise ValueError("timing")
    return seconds


__all__ = [
    "DeviceAuthorization",
    "DeviceFlowResult",
    "GitHubDeviceFlowError",
    "authorize",
]
