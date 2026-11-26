"""Browser-approved machine authorization for Cloud and self-hosted servers."""

from __future__ import annotations

import json
import platform
import time
import uuid
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
from yoke_contracts.bounded_json_http import (
    BoundedJsonHttpError,
    BoundedJsonHttpStatusError,
    request_json,
)
from yoke_contracts.machine_config.machine_name import machine_display_name
from yoke_contracts.machine_config.runtime import machine_id


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
    try:
        configured_id = machine_id()
    except machine_config_mutation.machine_runtime.MachineConfigError as exc:
        raise HostedMachineAuthorizationError(
            f"machine_identity_required: {exc}; repair this machine's config and retry"
        ) from None
    draft_id = None if configured_id else str(uuid.uuid4())
    identity = {"machine_id": configured_id or draft_id, "machine_name": machine_display_name()}
    payload, status = _request_start(origin, identity, opener, timeout_seconds)
    retired_machine_id = None
    if _is_retired(payload, status):
        retired_machine_id = configured_id
        draft_id = identity["machine_id"] = str(uuid.uuid4())
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
        draft_machine_id=draft_id,
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
    deadline = monotonic() + authorization.expires_in
    delay = float(authorization.interval)
    while True:
        remaining = deadline - monotonic()
        if remaining > 0:
            sleep(min(delay, remaining))
        if cancelled is not None and cancelled():
            raise HostedMachineAuthorizationCancelled(
                "browser approval wait cancelled; the match code expires on its own"
            )
        remaining = deadline - monotonic()
        outcome = _poll(
            authorization,
            opener=opener,
            retry_bad_gateway=True,
            timeout_seconds=min(timeout_seconds, max(0.1, remaining))
            if remaining > 0 else timeout_seconds,
        )
        if isinstance(outcome, HostedMachineCredential):
            return outcome
        if remaining <= 0:
            break
        delay = outcome
    raise HostedMachineAuthorizationError(
        "authorization_expired: hosted authorization expired before approval; "
        "start a fresh connection"
    )


def poll_once(
    authorization: PendingMachineAuthorization,
    *,
    opener: Callable[..., Any] | None = None,
    timeout_seconds: float = 15.0,
) -> HostedMachineCredential | None:
    """Ask once whether the browser approved; None while approval is pending.
    A lapsed code still asks: only the server knows it was approved in time."""
    outcome = _poll(authorization, opener=opener, timeout_seconds=timeout_seconds)
    return outcome if isinstance(outcome, HostedMachineCredential) else None


def _poll(
    authorization: PendingMachineAuthorization,
    *,
    opener: Callable[..., Any] | None,
    timeout_seconds: float,
    retry_bad_gateway: bool = False,
) -> HostedMachineCredential | float:
    """Persist the draft before polling, which can create the registry row."""
    identity = (
        _machine_identity(authorization.draft_machine_id, retired_id=authorization.retired_machine_id)
        if authorization.draft_machine_id else _machine_identity()
    )
    try:
        payload, status, headers = _post_json(
            f"{authorization.platform_url}{POLL_PATH}",
            {"device_code": authorization.device_code, **identity},
            opener=opener,
            timeout_seconds=timeout_seconds,
            sensitive_values=(authorization.device_code,),
        )
    except BoundedJsonHttpStatusError as exc:
        payload = exc.payload if isinstance(exc.payload, Mapping) else {}
        status, headers = exc.status, exc.headers
    if retry_bad_gateway and status == 502:
        return float(authorization.interval)
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
        reason = recovery(response).removeprefix(f"{error}: ")
        raise HostedMachineAuthorizationError(f"{error}: {reason}")
    if error == "machine_identity_required":
        raise HostedMachineAuthorizationError(
            f"machine_identity_required: {recovery(response)}; run `yoke status` to inspect this "
            "machine's configured identity, repair it, then retry"
        )
    if _is_retired(payload, status):
        _machine_identity(retired_id=identity["machine_id"])
        raise HostedMachineAuthorizationError(
            f"{MACHINE_RETIRED}: machine {identity['machine_id']} was "
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
    return HostedMachineCredential(api_url=api_url, org=response.org, token=response.token)


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
            allow_private_http=True,
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


def _machine_identity(draft_id: str | None = None, *, retired_id: str | None = None) -> dict[str, str]:
    try:
        if draft_id is not None:
            resolved_machine_id = machine_config_mutation.bind_draft_machine_identity(draft_id, replacing=retired_id)
        elif retired_id is not None:
            resolved_machine_id = machine_config_mutation.replace_retired_machine_identity(retired_id)
        else:
            resolved_machine_id = machine_config_mutation.ensure_local_machine_identity()
    except machine_config_mutation.MachineConfigWriteError as exc:
        if retired_id is not None:
            raise HostedMachineAuthorizationError(
                f"{MACHINE_RETIRED}: machine {retired_id} is retired and the new identity "
                f"could not be saved: {exc}; repair the config, then run `yoke connect` again"
            ) from None
        raise HostedMachineAuthorizationError(
            f"machine_identity_required: {exc}; create or restore this machine's "
            "config, then retry"
        ) from None
    return {"machine_id": resolved_machine_id, "machine_name": machine_display_name()}
