"""What the caller is told when the relay could not answer, and what counts.

The old hint sent operators to check their env and credential. That advice
was wrong for the failure that actually fires: the credential was valid and
the env was right, the relay was simply unreachable for a moment. Saying so
— and saying how many attempts went into that conclusion — is the difference
between an operator who retries and an operator who starts editing config
that was never broken.
"""

from __future__ import annotations

from typing import Optional

from yoke_cli.api_urls import HEALTH_PATH, join_api_url
from yoke_cli.transport import relay_telemetry
from yoke_cli.transport.https_response_policy import redact_text
from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionCallResponse,
    FunctionError,
)

TRANSPORT_FAILED_CODE = "https_transport_failed"

_UNREACHABLE_HINT = (
    "The relay did not answer; the env and credential are not implicated. "
    "Retrying is the repair — a call that changes state may or may not have "
    "been applied already, and re-running it is safe because the same "
    "request_id replays a completed call instead of repeating it."
)
_MALFORMED_HINT = (
    "The relay answered with something that is not a Yoke envelope, so the "
    "call cannot be reported either way."
)
# A refused loopback connection is answered, not unlucky: retrying it just
# asks the same kernel the same question. Sending the operator to "retry"
# here is what turns a five-second fix into a five-minute one.
_CONCLUSIVE_HINT = (
    "Nothing is listening on that address, so retrying will not help. "
    "Start the server (`cd <bundle> && docker compose up -d`), or select a "
    "different authority with `yoke env use NAME`; `yoke status` reports "
    "which connection this machine is pointed at."
)


def transport_error_response(
    request: FunctionCallRequest,
    api_url: str,
    detail: str,
    *,
    attempts: Optional[int] = None,
    conclusive: bool = False,
    sensitive_values: tuple[str, ...] = (),
) -> FunctionCallResponse:
    """Build the typed refusal, naming attempts when more than one was made."""
    health_url = join_api_url(api_url, HEALTH_PATH)
    message = detail
    if attempts is not None and attempts > 1:
        message = f"{detail} after {attempts} attempts"
    if conclusive:
        hint = _CONCLUSIVE_HINT
    else:
        hint = _UNREACHABLE_HINT if attempts is not None else _MALFORMED_HINT
    return FunctionCallResponse(
        success=False,
        function=request.function,
        version=request.version,
        request_id=request.request_id,
        error=FunctionError(
            code=TRANSPORT_FAILED_CODE,
            message=redact_text(message, sensitive_values),
            recovery_hint=redact_text(
                f"{hint} The env's public health endpoint is {health_url}.",
                sensitive_values,
            ),
        ),
    )


def record_outcome(
    request: FunctionCallRequest,
    response: FunctionCallResponse,
    *,
    env: str,
    attempts: int,
) -> None:
    """Count a relay that had to try again, then drain the spool on success.

    A first-try success is the overwhelming majority and carries no signal,
    so it records nothing — but it is exactly the moment the transport is
    known good, which is when anything spooled earlier can finally be sent.
    """
    relayed = response.error is None or response.error.code != TRANSPORT_FAILED_CODE
    if not relayed:
        relay_telemetry.record(
            function_id=request.function,
            session_id=request.actor.session_id or "",
            env=env,
            attempts=attempts,
            succeeded=False,
            failure_class=TRANSPORT_FAILED_CODE,
        )
        return
    if attempts > 1:
        relay_telemetry.record(
            function_id=request.function,
            session_id=request.actor.session_id or "",
            env=env,
            attempts=attempts,
            succeeded=True,
            failure_class="",
        )
    relay_telemetry.flush()


__all__ = [
    "TRANSPORT_FAILED_CODE",
    "record_outcome",
    "transport_error_response",
]
