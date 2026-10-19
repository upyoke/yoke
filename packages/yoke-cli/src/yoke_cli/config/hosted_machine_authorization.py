"""Browser-approved machine authorization for Cloud and self-hosted servers."""

from __future__ import annotations

import json
import platform
import time
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
    MACHINE_RETIRED,
    authorization_origin,
    same_origin_url,
    parse_authorization_response,
    MachineAuthorizationStarted,
    MachineAuthorizationApproved,
    MachineAuthorizationRefused,
    BROWSER_VERIFICATION_PATHS,
    credential_api_url,
)
from yoke_cli.config import machine_config_mutation
from yoke_cli.config.hosted_machine_authorization_refusals import (
    poll_is_retryable,
    poll_retry_delay,
    raise_admission_refusal,
    recovery,
)
from yoke_cli.config.hosted_machine_browser import (
    BrowserOpenResult,
    open_browser as open_browser,
)
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
    """Begin one authorization without opening a browser or persisting state.

    A server that refuses this computer's id as retired gets one more start
    with a new machine identity; the retired row keeps its history.
    """
    origin = authorization_origin(platform_url)
    identity = _machine_identity()
    payload, status = _request_start(origin, identity, opener, timeout_seconds)
    retired_machine_id = None
    if _is_retired(payload, status):
        retired_machine_id = identity["machine_id"]
        identity = _replace_retired_identity(retired_machine_id)
        payload, status = _request_start(origin, identity, opener, timeout_seconds)
        if _is_retired(payload, status):
            raise HostedMachineAuthorizationError(
                f"{MACHINE_RETIRED}: the server refused this computer's new machine "
                f"identity {identity['machine_id']} as retired too; ask the server "
                "operator to inspect its machine registry, then run `yoke connect` again"
            )
    if status != 200:
        response = parse_authorization_response(payload, status, operation="start")
        raise_admission_refusal(payload, status)
        raise HostedMachineAuthorizationError(
            f"authorization_refused: hosted authorization could not start (HTTP {status}); "
            f"{recovery(response)}"
        )
    response = parse_authorization_response(payload, status, operation="start")
    if not isinstance(response, MachineAuthorizationStarted):
        raise HostedMachineAuthorizationError(
            "authorization_response_invalid: expected a machine sign-in start response; "
            "correct the server contract, then reconnect"
        )
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
        retired_machine_id=retired_machine_id,
    )


def _request_start(
    origin: str,
    identity: Mapping[str, str],
    opener: Callable[..., Any] | None,
    timeout_seconds: float,
) -> tuple[object, int]:
    try:
        payload, status, _headers = _post_json(
            f"{origin}{START_PATH}",
            {
                **identity,
                "platform": "macOS"
                if platform.system() == "Darwin"
                else platform.system(),
            },
            opener=opener,
            timeout_seconds=timeout_seconds,
        )
    except BoundedJsonHttpStatusError as exc:
        return exc.payload, exc.status
    return payload, status


def _is_retired(payload: object, status: int) -> bool:
    return (
        status in {403, 409}
        and isinstance(payload, Mapping)
        and payload.get("error") == MACHINE_RETIRED
    )


def _replace_retired_identity(retired_machine_id: str) -> dict[str, str]:
    try:
        machine_config_mutation.replace_retired_machine_identity(retired_machine_id)
    except machine_config_mutation.MachineConfigWriteError as exc:
        raise HostedMachineAuthorizationError(
            f"{MACHINE_RETIRED}: machine {retired_machine_id} is retired and this "
            f"computer's new machine identity could not be saved: {exc}; repair "
            "~/.yoke/config.json, then run `yoke connect` again"
        ) from None
    return _machine_identity()


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
    delay = float(authorization.interval)
    while monotonic() < deadline:
        sleep(min(delay, max(0.0, deadline - monotonic())))
        if cancelled is not None and cancelled():
            raise HostedMachineAuthorizationCancelled(
                "browser approval wait cancelled; the match code expires on its own"
            )
        if monotonic() >= deadline:
            break
        outcome = _poll(
            authorization,
            machine_identity,
            opener=opener,
            timeout_seconds=min(timeout_seconds, max(0.1, deadline - monotonic())),
        )
        if isinstance(outcome, HostedMachineCredential):
            return outcome
        delay = outcome
    raise HostedMachineAuthorizationError(
        "hosted authorization expired before approval"
    )


def poll_once(
    authorization: PendingMachineAuthorization,
    *,
    opener: Callable[..., Any] | None = None,
    timeout_seconds: float = 15.0,
) -> HostedMachineCredential | None:
    """Ask once whether the browser approved; None while approval is pending.
    ``expires_in`` is the time left: a lapsed code refuses without the server."""
    if authorization.expires_in <= 0:
        raise HostedMachineAuthorizationError(
            "authorization_expired: the match code expired before approval; "
            "start a fresh connection"
        )
    outcome = _poll(
        authorization,
        _machine_identity(),
        opener=opener,
        timeout_seconds=min(timeout_seconds, float(authorization.expires_in)),
    )
    return outcome if isinstance(outcome, HostedMachineCredential) else None


def _poll(
    authorization: PendingMachineAuthorization,
    machine_identity: dict[str, str],
    *,
    opener: Callable[..., Any] | None,
    timeout_seconds: float,
) -> HostedMachineCredential | float:
    """One poll: the credential, or the seconds to wait before asking again."""
    try:
        payload, status, headers = _post_json(
            f"{authorization.platform_url}{POLL_PATH}",
            {"device_code": authorization.device_code, **machine_identity},
            opener=opener,
            timeout_seconds=timeout_seconds,
            sensitive_values=(authorization.device_code,),
        )
    except BoundedJsonHttpStatusError as exc:
        payload = exc.payload if isinstance(exc.payload, Mapping) else {}
        status, headers = exc.status, exc.headers
    response = parse_authorization_response(dict(payload), status, operation="poll")
    error = (
        response.error if isinstance(response, MachineAuthorizationRefused) else None
    )
    if status == 429 and error == "authorization_poll_rate_limited":
        return poll_retry_delay(headers, authorization.interval)
    if poll_is_retryable(status, error):
        return float(authorization.interval)
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
            f"machine_identity_required: {recovery(response)}; run `yoke status` to inspect this "
            "machine's configured identity, repair it, then retry"
        )
    if _is_retired(payload, status):
        _replace_retired_identity(machine_identity["machine_id"])
        raise HostedMachineAuthorizationError(
            f"{MACHINE_RETIRED}: machine {machine_identity['machine_id']} was "
            "retired before its credential was delivered; this computer now has "
            "a new machine identity, so run `yoke connect` again for a fresh code"
        )
    if status != 200:
        raise_admission_refusal(payload, status)
        raise HostedMachineAuthorizationError(
            f"{error or 'authorization_refused'}: hosted authorization polling failed (HTTP {status}); "
            f"{recovery(response)}"
        )
    if not isinstance(response, MachineAuthorizationApproved):
        raise HostedMachineAuthorizationError(
            "authorization_response_invalid: expected an approved machine credential; "
            "correct the server contract, then reconnect"
        )
    api_url = credential_api_url(
        response.api_url,
        authorization.platform_url,
        response.org,
        self_host=authorization.self_host,
    )
    return HostedMachineCredential(
        api_url=api_url, org=response.org, token=response.token
    )


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
    from yoke_cli.config.setup_browser import open_requested

    pending = start(platform_url, opener=opener, self_host=self_host)
    browser = open_requested(pending.verification_uri_complete, browser_open)
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
