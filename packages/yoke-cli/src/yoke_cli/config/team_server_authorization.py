"""Discover the team server's configured machine sign-in method."""

import urllib.request
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


def browser_sign_in_available(url: str) -> bool:
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
    if not isinstance(response.payload, dict) or not isinstance(
        response.payload.get("device_code"), bool
    ):
        raise HostedMachineAuthorizationError(
            "machine_sign_in_contract_invalid: server did not declare its sign-in method; ask its operator to check the served build, or use --token-stdin"
        )
    return response.payload["device_code"]
