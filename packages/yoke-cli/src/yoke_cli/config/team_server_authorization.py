"""Discover the team server's configured machine sign-in method.

Discovery answers two facts. ``device_code`` says the server takes
``yoke connect URL`` approvals at all; ``company_sign_in`` says a person can
approve their own machine by signing in with the company identity provider.
Without company sign-in only an already-connected machine can approve, and
the credential binds to that approver, so a teammate's first machine still
connects with an API token. A server that predates ``company_sign_in``
offered device codes only with company sign-in, so its absence reads as
``device_code``.
"""

import urllib.request
from dataclasses import dataclass
from yoke_cli.transport import server_reach_failure
from yoke_cli.transport.bounded_json_http import (
    BoundedJsonHttpError,
    BoundedJsonHttpStatusError,
    request_json,
)
from yoke_contracts.machine_authorization import (
    HostedMachineAuthorizationError,
    START_PATH,
    authorization_origin,
)


@dataclass(frozen=True)
class SignInMethods:
    device_code: bool
    company_sign_in: bool


def browser_sign_in_available(url: str) -> bool:
    """Whether a person can approve their own machine via company sign-in."""
    return sign_in_methods(url).company_sign_in


def sign_in_methods(url: str) -> SignInMethods:
    try:
        origin = authorization_origin(url)
    except HostedMachineAuthorizationError as exc:
        raise HostedMachineAuthorizationError(
            f"{exc}. {server_reach_failure.CHECK_SERVER_MACHINE}"
        ) from None
    try:
        response = request_json(
            urllib.request.Request(origin + START_PATH, method="GET"),
            timeout_seconds=15,
            replay_safe=True,
            allow_loopback_http=True,
        )
    except BoundedJsonHttpError as exc:
        # A 404 here may be a Yoke server older than this discovery path,
        # so it keeps the token-entry recovery below.
        older_server = isinstance(exc, BoundedJsonHttpStatusError) and exc.status == 404
        failure = (
            None
            if older_server
            else server_reach_failure.describe(exc, origin, check_server_machine=True)
        )
        if failure is not None:
            raise HostedMachineAuthorizationError(failure) from None
        if not isinstance(exc, BoundedJsonHttpStatusError):
            raise HostedMachineAuthorizationError(
                f"machine_sign_in_unavailable: {exc}; check the server URL and retry"
            ) from None
        reason = (
            "oidc_misconfigured"
            if isinstance(exc.payload, dict)
            and exc.payload.get("error") == "oidc_misconfigured"
            else "machine_sign_in_unavailable"
        )
        raise HostedMachineAuthorizationError(
            f"{reason}: the server's sign-in discovery returned HTTP {exc.status}; "
            "ask its operator to check the served build and company sign-in settings, "
            "or connect with an API token using --token-stdin"
        ) from None
    payload = response.payload
    device_code = payload.get("device_code") if isinstance(payload, dict) else None
    company = payload.get("company_sign_in", device_code) if device_code else False
    if not isinstance(device_code, bool) or not isinstance(company, bool):
        raise HostedMachineAuthorizationError(
            "machine_sign_in_contract_invalid: server did not declare its sign-in method; ask its operator to check the served build, or use --token-stdin"
        )
    return SignInMethods(device_code=device_code, company_sign_in=company)
