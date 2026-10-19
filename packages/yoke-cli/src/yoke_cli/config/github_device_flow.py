"""GitHub App device authorization with browser-assisted polling."""

from __future__ import annotations

from dataclasses import dataclass, field
import time
from typing import Any, Callable, Mapping
import urllib.request

from yoke_cli.config import setup_browser

from yoke_cli.config import github_git_credential_store as credential_store
from yoke_cli.config import github_device_transport
from yoke_cli.config import github_response_safety
from yoke_cli.config.github_device_flow_checks import (
    GitHubDeviceFlowError,
    raise_initial_oauth_error,
    required_string,
    same_origin_verification_uri,
    validate_expiring_token_response,
    validated_user_code,
)
from yoke_contracts import github_app_tokens as token_contract
from yoke_contracts import github_origin


_MAX_DEVICE_CODE_CHARS = 1_024


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
            "browser_action": setup_browser.action(
                self.verification_uri,
                "Enter the code in GitHub, approve access, then return here.",
                user_code=self.user_code,
            ),
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


def start(
    *,
    client_id: str,
    web_url: str,
    opener: Callable[..., Any] | None = None,
    monotonic: Callable[[], float] = time.monotonic,
    timeout_seconds: float = 30.0,
) -> DeviceAuthorization:
    """Ask GitHub for a device code; nothing is opened or polled."""
    selected_client_id = required_string(client_id, "client_id")
    base = credential_store.validated_web_url(web_url)
    configured_origin = github_origin.validate_github_web_endpoint(base).origin
    try:
        payload = github_device_transport.post_form(
            f"{base}{token_contract.GITHUB_OAUTH_DEVICE_CODE_PATH}",
            {"client_id": selected_client_id},
            opener=opener or _urlopen,
            timeout_seconds=timeout_seconds,
            deadline=monotonic() + timeout_seconds,
            monotonic=monotonic,
            error_type=GitHubDeviceFlowError,
        )
    except GitHubDeviceFlowError as exc:
        raise GitHubDeviceFlowError(
            f"{exc}. {token_contract.GITHUB_APP_USER_AUTH_CONFIGURATION_HINT}"
        ) from exc
    raise_initial_oauth_error(payload, client_id=selected_client_id)
    return _parse_authorization(payload, expected_origin=configured_origin)


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
    client_id = required_string(client_id, "client_id")
    authorization = start(
        client_id=client_id,
        web_url=web_url,
        opener=opener,
        monotonic=monotonic,
        timeout_seconds=timeout_seconds,
    )
    if notify is not None:
        notify({"phase": "device_authorization", **authorization.public_dict()})
    browser = setup_browser.open_requested(authorization.verification_uri, browser_open)
    browser_opened = browser.opened
    if notify is not None:
        notify(
            {
                "phase": "device_browser",
                "browser_opened": browser_opened,
                "browser_attempted": browser.attempted,
                "browser_reason": browser.reason,
                **authorization.public_dict(),
            }
        )
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
        answer = _poll(
            authorization,
            client_id=client_id,
            web_url=web_url,
            opener=opener,
            timeout_seconds=min(timeout_seconds, remaining),
            deadline=deadline,
            monotonic=monotonic,
        )
        if answer == "slow_down":
            interval = min(
                interval + token_contract.GITHUB_OAUTH_SLOW_DOWN_SECONDS,
                token_contract.GITHUB_OAUTH_POLL_INTERVAL_MAX_SECONDS,
            )
        elif isinstance(answer, dict):
            return DeviceFlowResult(answer, authorization, browser_opened)
    raise GitHubDeviceFlowError(_EXPIRED)


def poll_once(
    authorization: DeviceAuthorization,
    *,
    client_id: str,
    web_url: str,
    opener: Callable[..., Any] | None = None,
    monotonic: Callable[[], float] = time.monotonic,
    timeout_seconds: float = 30.0,
) -> dict[str, Any] | None:
    """Ask GitHub once for the token; None until the person finishes.
    ``expires_in`` is the time left: a lapsed code refuses without GitHub."""
    if authorization.expires_in <= 0:
        raise GitHubDeviceFlowError(_EXPIRED)
    answer = _poll(
        authorization,
        client_id=client_id,
        web_url=web_url,
        opener=opener,
        timeout_seconds=min(timeout_seconds, authorization.expires_in),
        deadline=monotonic() + authorization.expires_in,
        monotonic=monotonic,
    )
    return answer if isinstance(answer, dict) else None


_EXPIRED = (
    "github_device_authorization_expired: GitHub device authorization expired; "
    "start a fresh GitHub connection and approve its new code"
)


def _poll(
    authorization: DeviceAuthorization,
    *,
    client_id: str,
    web_url: str,
    opener: Callable[..., Any] | None,
    timeout_seconds: float,
    deadline: float,
    monotonic: Callable[[], float],
) -> dict[str, Any] | str:
    """One token request: the token response, or the code to wait on."""
    base = credential_store.validated_web_url(web_url)
    try:
        payload = github_device_transport.post_form(
            f"{base}{token_contract.GITHUB_OAUTH_ACCESS_TOKEN_PATH}",
            {
                "client_id": client_id,
                "device_code": authorization.device_code,
                "grant_type": token_contract.GITHUB_OAUTH_DEVICE_GRANT_TYPE,
            },
            opener=opener or _urlopen,
            timeout_seconds=timeout_seconds,
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
        validate_expiring_token_response(payload)
        return payload
    secrets = (authorization.device_code, authorization.user_code, client_id)
    error_code = github_response_safety.safe_oauth_error_code(
        raw_error_code, secrets=secrets
    )
    if error_code in {"authorization_pending", "slow_down"}:
        return error_code
    description = github_response_safety.safe_error_text(
        payload.get("error_description") or error_code, secrets=secrets
    )
    raise GitHubDeviceFlowError(
        f"GitHub device authorization failed ({error_code}): {description}"
    )


def _parse_authorization(
    payload: Mapping[str, Any],
    *,
    expected_origin: str,
) -> DeviceAuthorization:
    if isinstance(payload.get("expires_in"), bool) or isinstance(
        payload.get("interval"), bool
    ):
        raise GitHubDeviceFlowError("GitHub device authorization timing is invalid")
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
    verification_uri = same_origin_verification_uri(
        payload.get("verification_uri"), expected_origin=expected_origin
    )
    return DeviceAuthorization(
        device_code=required_string(
            payload.get("device_code"),
            "device_code",
            maximum_chars=_MAX_DEVICE_CODE_CHARS,
        ),
        user_code=validated_user_code(payload.get("user_code")),
        verification_uri=verification_uri,
        expires_in=expires_in,
        interval=interval,
    )


__all__ = [
    "DeviceAuthorization",
    "DeviceFlowResult",
    "GitHubDeviceFlowError",
    "authorize",
    "poll_once",
    "start",
]
