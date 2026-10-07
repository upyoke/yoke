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
    origin = authorization_origin(url)
    try:
        response = request_json(
            urllib.request.Request(origin + START_PATH, method="GET"),
            timeout_seconds=15,
            replay_safe=True,
            allow_loopback_http=True,
        )
    except BoundedJsonHttpStatusError as exc:
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
    except BoundedJsonHttpError as exc:
        raise HostedMachineAuthorizationError(
            f"machine_sign_in_unavailable: {exc}; check the server URL and retry"
        ) from None
    payload = response.payload
    device_code = payload.get("device_code") if isinstance(payload, dict) else None
    company = payload.get("company_sign_in", device_code) if device_code else False
    if not isinstance(device_code, bool) or not isinstance(company, bool):
        raise HostedMachineAuthorizationError(
            "machine_sign_in_contract_invalid: server did not declare its sign-in method; ask its operator to check the served build, or use --token-stdin"
        )
    return SignInMethods(device_code=device_code, company_sign_in=company)
