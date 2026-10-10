"""HTTP status mapping and fallback envelopes for function-call routes.

Shared by every route that answers a function-call envelope — the bearer
route, the browser web-session route, and the read-only SQL route — so the
same error code always carries the same HTTP status.
"""

from __future__ import annotations

from typing import Any, Dict

from yoke_contracts.api.function_call import FunctionCallResponse, FunctionError


ERROR_TO_STATUS: Dict[str, int] = {
    "envelope_invalid": 422,
    "empty_body": 422,
    "invalid_payload": 422,
    "payload_invalid": 422,
    "invalid_field": 422,
    "shrinkage": 422,
    "freeze_lock": 409,
    "validation_failed": 422,
    "settings_conflict": 409,
    "function_not_registered": 404,
    "target_not_found": 404,
    "not_found": 404,
    "claim_required": 409,
    "claim_changed": 409,
    "claim_not_held": 409,
    "claim_not_found": 404,
    "claim_error": 409,
    "hook_context": 403,
    "steering_seat_required": 409,
    "human_operator_required": 403,
    "idempotency_key_collision": 409,
    "actor_id_mismatch": 403,
    "actor_session_missing": 403,
    "permission_denied": 403,
    "permission_check_unavailable": 503,
    "machine_retired": 409,
    "machine_credential_required": 409,
    "machine_credential_mismatch": 409,
    "render_failed": 500,
    "write_failed": 500,
    "handler_contract": 500,
    "handler_exception": 500,
    # Per-handler validation/gate codes raised by registered handlers.
    "validation_error": 422,
    "unsupported_field": 422,
    "lifecycle_gate_unmet": 422,
    "frozen": 422,
    "precondition_failed": 422,
    "sql_empty": 422,
    "sql_multiple_statements": 422,
    "sql_not_read_only": 422,
    "sql_write_refused": 422,
    "sql_ddl_refused": 422,
    "sql_execution_failed": 422,
}


def status_for_response(response_envelope: Dict[str, Any]) -> int:
    """Map a function-call response envelope to an HTTP status code."""
    error = response_envelope.get("error")
    if error and error.get("code"):
        return ERROR_TO_STATUS.get(error["code"], 400)
    if response_envelope.get("warnings"):
        return 207
    return 200


def exception_response(
    envelope: Dict[str, Any],
    exc: Exception,
) -> FunctionCallResponse:
    """Return a typed function envelope for unexpected dispatcher failures."""
    function_id = str(envelope.get("function") or "")
    version = str(envelope.get("version") or "v1")
    request_id = envelope.get("request_id")
    if request_id is not None and not isinstance(request_id, str):
        request_id = str(request_id)
    return FunctionCallResponse(
        success=False,
        function=function_id,
        version=version,
        request_id=request_id,
        result={},
        warnings=[],
        error=FunctionError(
            code="handler_exception",
            message=(
                f"function call {function_id!r} raised {type(exc).__name__}: {exc}"
            ),
        ),
        event_ids=[],
    )


__all__ = ["ERROR_TO_STATUS", "exception_response", "status_for_response"]
