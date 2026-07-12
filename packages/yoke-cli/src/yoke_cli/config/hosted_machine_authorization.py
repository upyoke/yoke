"""Browser-approved machine authorization for the hosted Platform."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import time
from typing import Any, Callable, Mapping
import urllib.parse
import urllib.request
import webbrowser

from yoke_cli.transport.bounded_json_http import (
    BoundedJsonHttpError,
    BoundedJsonHttpStatusError,
    request_json,
)


class HostedMachineAuthorizationError(RuntimeError):
    """The hosted browser authorization could not complete safely."""


@dataclass(frozen=True)
class PendingMachineAuthorization:
    platform_url: str
    device_code: str = field(repr=False)
    user_code: str
    verification_uri: str
    verification_uri_complete: str
    expires_in: int
    interval: int


@dataclass(frozen=True)
class HostedMachineCredential:
    api_url: str
    org: str
    token: str = field(repr=False)


def start(
    platform_url: str,
    *,
    opener: Callable[..., Any] | None = None,
    timeout_seconds: float = 15.0,
) -> PendingMachineAuthorization:
    """Begin one authorization without opening a browser or persisting state."""
    origin = _platform_origin(platform_url)
    try:
        payload, status = _post_json(
            f"{origin}/api/machine/authorizations",
            {},
            opener=opener,
            timeout_seconds=timeout_seconds,
        )
    except BoundedJsonHttpStatusError as exc:
        raise HostedMachineAuthorizationError(
            f"hosted authorization could not start (HTTP {exc.status})"
        ) from None
    if status != 200:
        raise HostedMachineAuthorizationError(
            f"hosted authorization could not start (HTTP {status})"
        )
    device_code = _required(payload, "device_code")
    user_code = _required(payload, "user_code")
    verification_uri = _same_origin_url(
        _required(payload, "verification_uri"), origin, expected_path="/machine"
    )
    verification_uri_complete = _same_origin_url(
        _required(payload, "verification_uri_complete"),
        origin,
        expected_path="/machine",
    )
    expires_in = _bounded_integer(payload.get("expires_in"), 60, 1800, "expires_in")
    interval = _bounded_integer(payload.get("interval"), 1, 30, "interval")
    return PendingMachineAuthorization(
        platform_url=origin,
        device_code=device_code,
        user_code=user_code,
        verification_uri=verification_uri,
        verification_uri_complete=verification_uri_complete,
        expires_in=expires_in,
        interval=interval,
    )


def open_browser(
    authorization: PendingMachineAuthorization,
    *,
    browser_open: Callable[[str], Any] | None = None,
) -> bool:
    try:
        return bool(
            (browser_open or webbrowser.open)(authorization.verification_uri_complete)
        )
    except Exception:  # noqa: BLE001 - the visible URL remains the fallback
        return False


def complete(
    authorization: PendingMachineAuthorization,
    *,
    opener: Callable[..., Any] | None = None,
    sleep: Callable[[float], None] = time.sleep,
    monotonic: Callable[[], float] = time.monotonic,
    timeout_seconds: float = 15.0,
) -> HostedMachineCredential:
    """Poll until a browser-approved org credential is delivered exactly once."""
    deadline = monotonic() + authorization.expires_in
    token_url = f"{authorization.platform_url}/api/machine/authorizations/token"
    while monotonic() < deadline:
        sleep(min(authorization.interval, max(0.0, deadline - monotonic())))
        if monotonic() >= deadline:
            break
        try:
            payload, status = _post_json(
                token_url,
                {"device_code": authorization.device_code},
                opener=opener,
                timeout_seconds=min(timeout_seconds, max(0.1, deadline - monotonic())),
                sensitive_values=(authorization.device_code,),
            )
        except BoundedJsonHttpStatusError as exc:
            error = (
                exc.payload.get("error") if isinstance(exc.payload, Mapping) else None
            )
            if exc.status == 202 and error == "authorization_pending":
                continue
            if error in {"authorization_expired", "authorization_consumed"}:
                raise HostedMachineAuthorizationError(
                    str(error).replace("_", " ")
                ) from None
            raise HostedMachineAuthorizationError(
                f"hosted authorization polling failed (HTTP {exc.status})"
            ) from None
        error = payload.get("error")
        if status == 202 and error == "authorization_pending":
            continue
        if error in {"authorization_expired", "authorization_consumed"}:
            raise HostedMachineAuthorizationError(
                str(error).replace("_", " ")
            )
        if status != 200:
            raise HostedMachineAuthorizationError(
                f"hosted authorization polling failed (HTTP {status})"
            )
        if error:
            raise HostedMachineAuthorizationError(
                "hosted authorization returned an error"
            )
        token = _required(payload, "token")
        org = _required(payload, "org")
        api_url = _same_origin_api_url(
            _required(payload, "api_url"), authorization.platform_url
        )
        expected_path = f"/api/orgs/{urllib.parse.quote(org, safe='')}"
        if urllib.parse.urlsplit(api_url).path != expected_path:
            raise HostedMachineAuthorizationError(
                "hosted authorization returned a mismatched organization authority"
            )
        return HostedMachineCredential(api_url=api_url, org=org, token=token)
    raise HostedMachineAuthorizationError(
        "hosted authorization expired before approval"
    )


def authorize(
    platform_url: str,
    *,
    opener: Callable[..., Any] | None = None,
    browser_open: Callable[[str], Any] | None = None,
    notify: Callable[[PendingMachineAuthorization, bool], None] | None = None,
    sleep: Callable[[float], None] = time.sleep,
    monotonic: Callable[[], float] = time.monotonic,
) -> HostedMachineCredential:
    pending = start(platform_url, opener=opener)
    opened = open_browser(pending, browser_open=browser_open)
    if notify is not None:
        notify(pending, opened)
    return complete(pending, opener=opener, sleep=sleep, monotonic=monotonic)


def _post_json(
    url: str,
    payload: Mapping[str, Any],
    *,
    opener: Callable[..., Any] | None,
    timeout_seconds: float,
    sensitive_values: tuple[str, ...] = (),
) -> tuple[Mapping[str, Any], int]:
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
    return response.payload, int(response.status)


def _platform_origin(value: str) -> str:
    parsed = urllib.parse.urlsplit(str(value or "").strip().rstrip("/"))
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
    ):
        raise HostedMachineAuthorizationError(
            "hosted Platform URL must be an HTTPS origin"
        )
    if parsed.path or parsed.query or parsed.fragment:
        raise HostedMachineAuthorizationError(
            "hosted Platform URL must not include a path"
        )
    return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, "", "", ""))


def _same_origin_url(value: str, origin: str, *, expected_path: str) -> str:
    parsed = urllib.parse.urlsplit(value)
    expected = urllib.parse.urlsplit(origin)
    if (
        parsed.scheme != expected.scheme
        or parsed.netloc != expected.netloc
        or parsed.path != expected_path
        or parsed.fragment
    ):
        raise HostedMachineAuthorizationError(
            "hosted authorization returned an unsafe browser URL"
        )
    return value


def _same_origin_api_url(value: str, origin: str) -> str:
    parsed = urllib.parse.urlsplit(value.rstrip("/"))
    expected = urllib.parse.urlsplit(origin)
    if (
        parsed.scheme != expected.scheme
        or parsed.netloc != expected.netloc
        or not parsed.path.startswith("/api/orgs/")
        or parsed.query
        or parsed.fragment
    ):
        raise HostedMachineAuthorizationError(
            "hosted authorization returned an unsafe API authority"
        )
    return value.rstrip("/")


def _required(payload: Mapping[str, Any], key: str) -> str:
    value = str(payload.get(key) or "").strip()
    if not value or len(value) > 4096:
        raise HostedMachineAuthorizationError(f"hosted authorization omitted {key}")
    return value


def _bounded_integer(value: Any, minimum: int, maximum: int, label: str) -> int:
    if isinstance(value, bool):
        raise HostedMachineAuthorizationError(
            f"hosted authorization returned invalid {label}"
        )
    try:
        parsed = int(value)
    except (TypeError, ValueError, OverflowError):
        raise HostedMachineAuthorizationError(
            f"hosted authorization returned invalid {label}"
        ) from None
    if parsed < minimum or parsed > maximum:
        raise HostedMachineAuthorizationError(
            f"hosted authorization returned invalid {label}"
        )
    return parsed


__all__ = [
    "HostedMachineAuthorizationError",
    "HostedMachineCredential",
    "PendingMachineAuthorization",
    "authorize",
    "complete",
    "open_browser",
    "start",
]
