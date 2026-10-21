"""Send a self-deploy driver's calls over https, keeping the door as fallback.

A driver holding the self-deploy declaration on a ``*-db-admin`` door would
otherwise run every handler on this machine, each query a tunnel round trip.
The paired https env serves the same database beside it, so each call goes
there first. Only a call that env cannot serve — no connection, the API down
or mid-replacement, or a serving build that lacks the function — runs through
the door, with a one-line note. The door re-sends the same request id, so a
call the API may already have applied replays from the shared ledger instead
of repeating. A timed-out QA dispatch waits for that replay over HTTPS;
an unconfirmed recovery returns to the driver without using this door.
"""

from __future__ import annotations

import sys
from typing import Callable

from yoke_cli.transport import https as https_transport
from yoke_cli.transport.function_version_skew import (
    ARGUMENT_SKEW_ERROR_CODE,
    SKEW_ERROR_CODE,
)
from yoke_cli.transport.relay_telemetry import TRANSPORT_FAILED_CODE
from yoke_contracts.api.function_call import FunctionCallRequest, FunctionCallResponse

#: Answers meaning the https env could not serve the call at all.
UNSERVED_CODES = frozenset(
    {TRANSPORT_FAILED_CODE, SKEW_ERROR_CODE, ARGUMENT_SKEW_ERROR_CODE}
)

Relay = Callable[["https_transport.HttpsConnection"], FunctionCallResponse]
Door = Callable[[], FunctionCallResponse]


def relay_or_door(
    request: FunctionCallRequest, https_env: str, relay: Relay, door: Door
) -> FunctionCallResponse:
    """Answer *request* from *https_env* when it serves it, else from *door*."""
    try:
        connection = https_transport.resolve_https_connection(explicit_env=https_env)
    except https_transport.TransportError as exc:
        reason = str(exc)
    else:
        if connection is None:
            reason = "it resolves to no https connection on this machine"
        else:
            response = relay(connection)
            error = response.error
            if response.success or error is None or error.code not in UNSERVED_CODES:
                return response
            reason = f"{error.code}: {error.message}"
    print(
        f"note: {https_env!r} could not serve {request.function} ({reason}); "
        "sending it through the self-deploy database door",
        file=sys.stderr,
        flush=True,
    )
    return door()


__all__ = ["UNSERVED_CODES", "relay_or_door"]
