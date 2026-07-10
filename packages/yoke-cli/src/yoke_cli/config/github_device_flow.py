"""GitHub App device authorization with browser-assisted polling."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import time
from typing import Any, Callable, Mapping
import urllib.error
import urllib.parse
import urllib.request
import webbrowser

from yoke_cli.config import github_git_credential_store as credential_store
from yoke_contracts import github_app_tokens as token_contract
from yoke_contracts import github_origin


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
        payload = _post_form(
            f"{base}{token_contract.GITHUB_OAUTH_DEVICE_CODE_PATH}",
            {"client_id": selected_client_id}, opener=opener,
            timeout_seconds=timeout_seconds,
        )
    except GitHubDeviceFlowError as exc:
        raise GitHubDeviceFlowError(
            f"{exc}. {token_contract.GITHUB_APP_USER_AUTH_CONFIGURATION_HINT}"
        ) from exc
    _raise_initial_oauth_error(payload)
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
    while monotonic() < deadline:
        sleep(interval)
        payload = _post_form(
            token_url,
            {
                "client_id": client_id,
                "device_code": authorization.device_code,
                "grant_type": token_contract.GITHUB_OAUTH_DEVICE_GRANT_TYPE,
            },
            opener=opener,
            timeout_seconds=timeout_seconds,
        )
        error_code = str(payload.get("error") or "").strip()
        if not error_code:
            _validate_expiring_token_response(payload)
            return payload
        if error_code == "authorization_pending":
            continue
        if error_code == "slow_down":
            interval += token_contract.GITHUB_OAUTH_SLOW_DOWN_SECONDS
            continue
        description = str(payload.get("error_description") or error_code)
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
    verification_uri = _same_origin_verification_uri(
        payload.get("verification_uri"), expected_origin=expected_origin
    )
    return DeviceAuthorization(
        device_code=_required_string(payload.get("device_code"), "device_code"),
        user_code=_required_string(payload.get("user_code"), "user_code"),
        verification_uri=verification_uri,
        expires_in=expires_in,
        interval=interval,
    )


def _raise_initial_oauth_error(payload: Mapping[str, Any]) -> None:
    error_code = str(payload.get("error") or "").strip()
    if not error_code:
        return
    description = str(payload.get("error_description") or error_code).strip()
    raise GitHubDeviceFlowError(
        f"GitHub device authorization is unavailable ({error_code}): "
        f"{description}. {token_contract.GITHUB_APP_USER_AUTH_CONFIGURATION_HINT}"
    )


def _validate_expiring_token_response(payload: Mapping[str, Any]) -> None:
    try:
        _required_string(payload.get("access_token"), "access_token")
        _required_string(payload.get("refresh_token"), "refresh_token")
        for field_name in ("expires_in", "refresh_token_expires_in"):
            raw = payload.get(field_name)
            if isinstance(raw, bool) or int(raw) <= 0:
                raise ValueError(field_name)
    except (GitHubDeviceFlowError, TypeError, ValueError) as exc:
        raise GitHubDeviceFlowError(
            "GitHub did not return an expiring, refreshable App user token. "
            f"{token_contract.GITHUB_APP_USER_AUTH_CONFIGURATION_HINT}"
        ) from exc


def _post_form(
    url: str,
    values: Mapping[str, str],
    *,
    opener: Callable[..., Any] | None,
    timeout_seconds: float,
) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        data=urllib.parse.urlencode(values).encode("utf-8"),
        headers={
            "Accept": token_contract.GITHUB_JSON_ACCEPT,
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": token_contract.GITHUB_APP_USER_AGENT,
        },
        method="POST",
    )
    try:
        with (opener or _urlopen)(request, timeout=timeout_seconds) as response:
            raw = response.read()
    except urllib.error.HTTPError as exc:
        raise GitHubDeviceFlowError(
            f"GitHub device authorization failed with HTTP {exc.code}"
        ) from exc
    except urllib.error.URLError as exc:
        raise GitHubDeviceFlowError(
            f"GitHub device authorization failed: {exc.reason}"
        ) from exc
    try:
        payload = json.loads(raw.decode("utf-8") or "{}")
    except ValueError as exc:
        raise GitHubDeviceFlowError(
            "GitHub device authorization response is not JSON"
        ) from exc
    if not isinstance(payload, dict):
        raise GitHubDeviceFlowError(
            "GitHub device authorization response must be an object"
        )
    return payload


def _open_browser(url: str, browser_open: Callable[[str], Any]) -> bool:
    try:
        return bool(browser_open(url))
    except Exception:
        return False


def _same_origin_verification_uri(value: Any, *, expected_origin: str) -> str:
    candidate = str(value or "").strip()
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


def _required_string(value: Any, label: str) -> str:
    if not isinstance(value, str):
        raise GitHubDeviceFlowError(f"{label} must be a string")
    text = value.strip()
    if not text:
        raise GitHubDeviceFlowError(f"{label} is required")
    return text


__all__ = [
    "DeviceAuthorization",
    "DeviceFlowResult",
    "GitHubDeviceFlowError",
    "authorize",
]
