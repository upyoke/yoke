"""Shared evidence-based diagnosis and recovery for HTTPS failures."""

from __future__ import annotations

import http.client
import urllib.error
from typing import Optional

from yoke_cli.api_urls import FUNCTIONS_CALL_PATH, HEALTH_PATH, join_api_url
from yoke_cli.transport import relay_telemetry
from yoke_cli.transport.json_error_safety import safe_diagnostic_text
from yoke_cli.transport.https_engine_handshake import (
    ServerHandshake,
    observe_server_version,
)
from yoke_cli.transport.https_response_policy import (
    HttpsResponsePolicyError,
    adopt_boundary_error,
    parse_typed_response,
    read_bounded_response,
    redact_text,
    safe_excerpt,
)
from yoke_cli.transport.https_retry_policy import (
    certificate_validation_error,
    connection_refusal_is_conclusive,
    is_sandbox_denial,
)
from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionCallResponse,
    FunctionError,
)
from yoke_contracts.harness_sandbox_recovery import sandbox_recovery

# Canonical definition lives in relay_telemetry (the lower-level module this
# one already imports); re-exported here so existing importers of this
# module's TRANSPORT_FAILED_CODE keep working.
TRANSPORT_FAILED_CODE = relay_telemetry.TRANSPORT_FAILED_CODE
UNREACHABLE_DETAIL = "could not reach the HTTPS function relay endpoint"

_UNREACHABLE_HINT = (
    "The relay did not answer; the cause is unknown. Check endpoint reachability "
    "and DNS. For a transient failure, "
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
    "Start the server (`yoke self-host init --dir <bundle> --protect-existing --start`), or select a "
    "different authority with `yoke env use NAME`; `yoke status` reports "
    "which connection this machine is pointed at."
)


_SANDBOX_HINT = (
    "The operating system denied permission to connect, so retrying will not help. "
    "Check this machine's network access policy; if the harness sandbox denied "
    "access, use its supported permission settings."
)


def certificate_diagnostic(
    error: BaseException | None,
    *,
    sensitive_values: tuple[str, ...] = (),
) -> tuple[str, str] | None:
    """Report only the certificate facts the TLS verifier actually supplied."""
    certificate = certificate_validation_error(error)
    if certificate is None:
        return None
    reason = getattr(certificate, "verify_message", None) or str(certificate)
    detail = safe_diagnostic_text(
        f"certificate_validation_failed: {reason}", sensitive_values=sensitive_values
    )
    code = getattr(certificate, "verify_code", None)
    if code == 10:
        repair = "Renew the expired serving certificate and check the client clock."
    elif code in (62, 64):
        repair = "Correct the endpoint hostname or serve a certificate covering it."
    elif code in (18, 19, 20, 21):
        repair = (
            "Repair the server certificate chain or configure the client's trusted "
            "CA store with the intended certificate authority."
        )
    elif code == 9:
        repair = "Check the client clock and the certificate's validity start time."
    else:
        repair = (
            "Ask the endpoint operator to inspect the certificate and chain; "
            "check the client clock, hostname and trusted CA store."
        )
    return (
        detail,
        f"{repair} Retrying unchanged will not help. Keep TLS verification enabled.",
    )


def http_error_response(
    request: FunctionCallRequest,
    api_url: str,
    exc: urllib.error.HTTPError,
    *,
    deadline: float,
    sensitive_values: tuple[str, ...],
    handshake: Optional[ServerHandshake] = None,
) -> tuple[FunctionCallResponse, bool, str | None]:
    """Decode an HTTP error into its reply shape and response-policy result."""
    observe_server_version(getattr(exc, "headers", None), handshake)
    try:
        raw = read_bounded_response(exc, deadline=deadline)
    except HttpsResponsePolicyError as read_error:
        return (
            transport_error_response(
                request, api_url, str(read_error), sensitive_values=sensitive_values
            ),
            False,
            str(read_error),
        )
    except (OSError, http.client.HTTPException) as exc:
        return (
            transport_error_response(
                request,
                api_url,
                UNREACHABLE_DETAIL,
                attempts=1,
                error=exc,
                sensitive_values=sensitive_values,
            ),
            False,
            "conclusive_connection_failure"
            if connection_refusal_is_conclusive(api_url, exc)
            else None,
        )
    try:
        return parse_typed_response(raw, sensitive_values=sensitive_values), True, None
    except HttpsResponsePolicyError:
        adopted = adopt_boundary_error(request, raw, sensitive_values=sensitive_values)
        if adopted is not None:
            return adopted, True, None
        excerpt = safe_excerpt(raw, sensitive_values=sensitive_values)
        detail = f": {excerpt}" if excerpt else ""
        return (
            transport_error_response(
                request,
                api_url,
                f"{join_api_url(api_url, FUNCTIONS_CALL_PATH)} returned HTTP "
                f"{exc.code} with a non-envelope body{detail}",
                sensitive_values=sensitive_values,
            ),
            False,
            None,
        )


def transport_error_response(
    request: FunctionCallRequest,
    api_url: str,
    detail: str,
    *,
    attempts: Optional[int] = None,
    error: BaseException | None = None,
    sensitive_values: tuple[str, ...] = (),
) -> FunctionCallResponse:
    """Build the typed refusal, naming attempts when more than one was made.

    What the failure *means* is decided here rather than by the caller, so
    the hint and the retry decision cannot end up reading the same error two
    different ways.
    """
    health_url = join_api_url(api_url, HEALTH_PATH)
    certificate = certificate_diagnostic(error, sensitive_values=sensitive_values)
    if certificate is not None:
        detail = certificate[0]
    message = detail
    if attempts is not None and attempts > 1:
        message = f"{detail} after {attempts} attempts"
    if certificate is not None:
        hint = certificate[1]
    elif is_sandbox_denial(error):
        recovery = sandbox_recovery()
        hint = (
            f"{_SANDBOX_HINT} If the sandbox caused this denial: {recovery}"
            if recovery
            else _SANDBOX_HINT
        )
    elif connection_refusal_is_conclusive(api_url, error):
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
    """Count retry delivery separately from the function's final outcome.

    A first-try success is the overwhelming majority and carries no signal,
    so it records nothing — but it is exactly the moment the transport is
    known good, which is when anything spooled earlier can finally be sent.

    The project passed to ``record`` is the FAILING request's own target
    project — already resolved by whatever command built this request, the
    same request/session/connection authority the call itself carried —
    never a project discovered later when the spool happens to drain.
    """
    project = str(request.target.project_id or "")
    delivered = response.error is None or response.error.code != TRANSPORT_FAILED_CODE
    if not delivered:
        relay_telemetry.record(
            function_id=request.function,
            session_id=request.actor.session_id or "",
            env=env,
            attempts=attempts,
            transport_delivered=False,
            application_succeeded=None,
            failure_class=TRANSPORT_FAILED_CODE,
            project=project,
        )
        return
    if attempts > 1:
        relay_telemetry.record(
            function_id=request.function,
            session_id=request.actor.session_id or "",
            env=env,
            attempts=attempts,
            transport_delivered=True,
            application_succeeded=response.success,
            failure_class=response.error.code if response.error else "",
            project=project,
        )
    relay_telemetry.flush()


__all__ = [
    "TRANSPORT_FAILED_CODE",
    "UNREACHABLE_DETAIL",
    "certificate_diagnostic",
    "http_error_response",
    "record_outcome",
    "transport_error_response",
]
