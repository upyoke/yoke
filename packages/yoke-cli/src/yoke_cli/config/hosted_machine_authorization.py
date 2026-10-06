"""Browser-approved machine authorization for Cloud and self-hosted servers."""

from __future__ import annotations

import json
import math
import time
from email.utils import parsedate_to_datetime
from typing import Any, Callable, Mapping
import urllib.request

from yoke_contracts.machine_authorization import (
    START_PATH,
    POLL_PATH,
    HostedMachineAuthorizationError,
    HostedMachineAuthorizationDenied,
    HostedMachineAuthorizationCancelled,
    PendingMachineAuthorization,
    HostedMachineCredential,
    authorization_origin,
    same_origin_url,
    parse_authorization_response,
    MachineAuthorizationStarted,
    MachineAuthorizationApproved,
    MachineAuthorizationRefused,
    BROWSER_VERIFICATION_PATHS,
    RETRYABLE_POLL_ERRORS,
    credential_api_url,
)
from yoke_cli.config import machine_config_mutation
from yoke_cli.config.hosted_machine_browser import BrowserOpenResult, open_browser
from yoke_cli.transport.bounded_json_http import (
    BoundedJsonHttpError,
    BoundedJsonHttpStatusError,
    request_json,
)
from yoke_contracts.machine_config.machine_name import machine_display_name


def start(
    platform_url: str,
    *,
    opener: Callable[..., Any] | None = None,
    timeout_seconds: float = 15.0,
    self_host: bool = False,
) -> PendingMachineAuthorization:
    """Begin one authorization without opening a browser or persisting state."""
    origin = authorization_origin(platform_url)
    try:
        payload, status, _headers = _post_json(
            f"{origin}{START_PATH}",
            _machine_identity() if self_host else {},
            opener=opener,
            timeout_seconds=timeout_seconds,
        )
    except BoundedJsonHttpStatusError as exc:
        parse_authorization_response(exc.payload, exc.status, operation="start")
        _raise_admission_refusal(exc.payload, exc.status)
        raise HostedMachineAuthorizationError(
            f"hosted authorization could not start (HTTP {exc.status})"
        ) from None
    if status != 200:
        parse_authorization_response(payload, status, operation="start")
        _raise_admission_refusal(payload, status)
        raise HostedMachineAuthorizationError(
            f"hosted authorization could not start (HTTP {status})"
        )
    response = parse_authorization_response(payload, status, operation="start")
    assert isinstance(response, MachineAuthorizationStarted)
    verification_uri = same_origin_url(
        response.verification_uri,
        origin,
        expected_paths=BROWSER_VERIFICATION_PATHS,
    )
    verification_uri_complete = same_origin_url(
        response.verification_uri_complete,
        origin,
        expected_paths=BROWSER_VERIFICATION_PATHS,
    )
    return PendingMachineAuthorization(
        platform_url=origin,
        device_code=response.device_code,
        user_code=response.user_code,
        verification_uri=verification_uri,
        verification_uri_complete=verification_uri_complete,
        expires_in=response.expires_in,
        interval=response.interval,
        self_host=self_host,
    )


def complete(
    authorization: PendingMachineAuthorization,
    *,
    opener: Callable[..., Any] | None = None,
    sleep: Callable[[float], Any] = time.sleep,
    monotonic: Callable[[], float] = time.monotonic,
    timeout_seconds: float = 15.0,
    cancelled: Callable[[], bool] | None = None,
) -> HostedMachineCredential:
    """Poll until a browser-approved org credential is delivered exactly once.
    ``cancelled`` is consulted after every wait; pair it with a ``sleep`` that
    wakes early (``threading.Event.wait``) so an abandoned wait ends at once
    rather than at the next poll tick.
    """
    machine_identity = _machine_identity()
    deadline = monotonic() + authorization.expires_in
    token_url = f"{authorization.platform_url}{POLL_PATH}"
    delay = float(authorization.interval)
    while monotonic() < deadline:
        sleep(min(delay, max(0.0, deadline - monotonic())))
        if cancelled is not None and cancelled():
            raise HostedMachineAuthorizationCancelled(
                "browser approval wait cancelled; the one-time code expires on its own"
            )
        if monotonic() >= deadline:
            break
        delay = float(authorization.interval)
        try:
            payload, status, headers = _post_json(
                token_url,
                {"device_code": authorization.device_code, **machine_identity},
                opener=opener,
                timeout_seconds=min(timeout_seconds, max(0.1, deadline - monotonic())),
                sensitive_values=(authorization.device_code,),
            )
        except BoundedJsonHttpStatusError as exc:
            payload = exc.payload if isinstance(exc.payload, Mapping) else {}
            status, headers = exc.status, exc.headers
        response = parse_authorization_response(dict(payload), status, operation="poll")
        error = (
            response.error
            if isinstance(response, MachineAuthorizationRefused)
            else None
        )
        if status == 429 and error == "authorization_poll_rate_limited":
            delay = _poll_retry_delay(headers, authorization.interval)
            continue
        if _poll_is_retryable(status, error):
            continue
        if status == 410 and error == "authorization_denied":
            raise HostedMachineAuthorizationDenied(
                "authorization_denied: authorization denied in the browser; start a fresh connection"
            )
        if error in {"authorization_expired", "authorization_consumed"}:
            raise HostedMachineAuthorizationError(
                f"{error}: {str(error).replace('_', ' ')}; start a fresh connection"
            )
        if error == "machine_identity_required":
            raise HostedMachineAuthorizationError(
                "machine_identity_required: run `yoke status` to inspect this "
                "machine's configured identity, repair it, then retry"
            )
        if status != 200:
            _raise_admission_refusal(payload, status)
            raise HostedMachineAuthorizationError(
                f"hosted authorization polling failed (HTTP {status})"
            )
        assert isinstance(response, MachineAuthorizationApproved)
        org = response.org
        api_url = credential_api_url(
            response.api_url,
            authorization.platform_url,
            org,
            self_host=authorization.self_host,
        )
        return HostedMachineCredential(api_url=api_url, org=org, token=response.token)
    raise HostedMachineAuthorizationError(
        "hosted authorization expired before approval"
    )


def _raise_admission_refusal(payload: object, status: int) -> None:
    error = payload.get("error") if isinstance(payload, Mapping) else None
    if status == 429 and error in {
        "authorization_start_rate_limited",
        "authorization_client_capacity",
        "authorization_capacity",
    }:
        raise HostedMachineAuthorizationError(
            f"{error}: finish pending machine approvals or wait for the server's admission budget to recover, then reconnect"
        ) from None


def _poll_is_retryable(status: int, error: object) -> bool:
    expected_error = RETRYABLE_POLL_ERRORS.get(status)
    return expected_error is not None and expected_error == error


def _poll_retry_delay(headers: Mapping[str, str], interval: int) -> float:
    raw = next(
        (value for key, value in headers.items() if key.casefold() == "retry-after"),
        "",
    )
    try:
        seconds = float(raw)
    except (TypeError, ValueError):
        try:
            seconds = parsedate_to_datetime(raw).timestamp() - time.time()
        except (TypeError, ValueError, OverflowError):
            return float(interval)
    return max(float(interval), seconds) if math.isfinite(seconds) else float(interval)


def authorize(
    platform_url: str,
    *,
    opener: Callable[..., Any] | None = None,
    browser_open: Callable[[str], Any] | None = None,
    notify: Callable[[PendingMachineAuthorization, BrowserOpenResult], None]
    | None = None,
    sleep: Callable[[float], Any] = time.sleep,
    monotonic: Callable[[], float] = time.monotonic,
    self_host: bool = False,
) -> HostedMachineCredential:
    pending = start(platform_url, opener=opener, self_host=self_host)
    browser = open_browser(pending, browser_open=browser_open)
    if notify is not None:
        notify(pending, browser)
    return complete(pending, opener=opener, sleep=sleep, monotonic=monotonic)


def _post_json(
    url: str,
    payload: Mapping[str, Any],
    *,
    opener: Callable[..., Any] | None,
    timeout_seconds: float,
    sensitive_values: tuple[str, ...] = (),
) -> tuple[Mapping[str, Any], int, Mapping[str, str]]:
    request = urllib.request.Request(
        url,
        method="POST",
        data=json.dumps(dict(payload), separators=(",", ":")).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    try:
        response = request_json(
            request,
            timeout_seconds=timeout_seconds,
            replay_safe=False,
            allow_loopback_http=True,
            sensitive_values=sensitive_values,
            opener=opener,
        )
    except BoundedJsonHttpStatusError:
        raise
    except BoundedJsonHttpError as exc:
        raise HostedMachineAuthorizationError(str(exc)) from None
    if not isinstance(response.payload, Mapping):
        raise HostedMachineAuthorizationError(
            "hosted authorization returned invalid JSON"
        )
    return response.payload, int(response.status), response.headers


def _machine_identity() -> dict[str, str]:
    try:
        resolved_machine_id = machine_config_mutation.ensure_local_machine_identity()
    except machine_config_mutation.MachineConfigWriteError as exc:
        raise HostedMachineAuthorizationError(
            f"machine_identity_required: {exc}; create or restore this machine's "
            "config, then retry"
        ) from None
    return {
        "machine_id": resolved_machine_id,
        "machine_name": machine_display_name(),
    }
