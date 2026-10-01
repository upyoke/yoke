"""Named failure diagnostics for a partially composed HTTPS Doctor report."""

from __future__ import annotations

from yoke_contracts.api.function_call import FunctionCallResponse, FunctionError


TRANSPORT_FAILURE_CODE = "https_transport_failed"
_PARTIAL_FAILURE_CODE = "doctor_control_plane_partial"


def control_plane_failure_row(response: FunctionCallResponse) -> dict[str, str]:
    error = response.error
    code = error.code if error else TRANSPORT_FAILURE_CODE
    message = error.message if error else "the relay returned no diagnosis"
    return {
        "hc": "HC-doctor-control-plane-batch",
        "name": "Relayed control-plane Doctor batch",
        "severity": "FAIL",
        "detail": (
            f"{code}: {message}. Machine-local checks and --fix actions "
            "still ran; retry the same command after ingress or control-plane "
            "health recovers."
        ),
    }


def partial_error(response: FunctionCallResponse) -> FunctionError:
    original = response.error
    code = original.code if original else TRANSPORT_FAILURE_CODE
    message = original.message if original else "relay failed without detail"
    return FunctionError(
        code=_PARTIAL_FAILURE_CODE,
        message=(
            f"bounded control-plane Doctor batch failed ({code}); the attached "
            f"report is partial and machine-local checks completed: {message}"
        ),
        recovery_hint=(
            "Retry the same `yoke doctor run` command after ingress or "
            "control-plane health recovers; the report remains failing until "
            "every relayed batch completes."
        ),
    )
