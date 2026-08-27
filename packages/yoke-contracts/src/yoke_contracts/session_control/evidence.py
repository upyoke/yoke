"""Bounded evidence shared by relay clients and the control plane."""

from __future__ import annotations

import re
from typing import Any, Mapping


_TEXT_FIELDS = frozenset(
    {
        "adapter_revision",
        "background_agent_result",
        "background_agent_stop",
        # Why the control plane closed an attempt itself, how far the launch
        # had got, and whether the relay holding it was still connected. A
        # server-side closure runs because nothing was reported, so these are
        # the only diagnosable facts such an attempt carries.
        "closure_reason",
        "launch_phase_reached",
        "transport_state",
        "diagnostic_availability",
        "driver_surface",
        "driver_version",
        # Which hook event handled the receipt, and — when that event
        # attached nothing — the classification of what declined. An
        # operator following a message reads this table, so a delivery
        # step that says nothing here says nothing anywhere.
        "hook_event",
        "probe_detail",
        "identity_output_snippet",
        "identity_parse_expectation",
        "machine_id",
        "native_binary_source",
        "native_binary",
        "native_capture_path",
        "native_diagnostic_ref",
        "native_error_class",
        "native_error_sha256",
        "native_error_step",
        "native_instruction_sha256",
        "native_launch_phase",
        "native_started_at",
        "relay_id",
        # Which session the launch was talking about, why the control plane
        # turned it away, and the model labels the two sides carried. A native
        # that tried and was refused is otherwise indistinguishable from one
        # that never came up — exactly the pair an operator must tell apart.
        "registered_model",
        "registration_refusal_code",
        "registration_session_id",
        "requested_model",
        "result_code",
        "surface",
        # Why a wake fired against a session whose liveness read active. The
        # attempt is otherwise identical to an ordinary stopped-session
        # resume, and the escalation is the half an operator would question.
        "wake_escalation",
    }
)
_INTEGER_FIELDS = frozenset(
    {
        "background_agent_lookup_attempts",
        "background_agent_stop_duration_ms",
        "diagnostic_expires_at",
        "duration_ms",
        "exit_code",
        "handles_considered",
        "native_launch_pid",
        "native_pid",
    }
)
_MAX_TEXT_LENGTH = 128
_MAX_CAPTURE_PATH_LENGTH = 512
_NATIVE_DIAGNOSTIC_COMMAND = "yoke relay diagnostic"
NATIVE_DIAGNOSTIC_REFERENCE_PATTERN = re.compile(r"nd-[0-9a-f]{32}")


def valid_native_diagnostic_reference(value: object) -> str | None:
    """Return an exact opaque native-diagnostic reference, never shell text."""
    if not isinstance(value, str):
        return None
    if NATIVE_DIAGNOSTIC_REFERENCE_PATTERN.fullmatch(value) is None:
        return None
    return value


def native_diagnostic_command(reference: str) -> str:
    """Return the copyable machine-local retrieval recipe for an opaque ref."""
    valid_reference = valid_native_diagnostic_reference(reference)
    if valid_reference is None:
        raise ValueError("native diagnostic reference is invalid")
    return f"{_NATIVE_DIAGNOSTIC_COMMAND} {valid_reference}"


def redacted_evidence_document(
    value: Mapping[str, Any] | None,
) -> dict[str, str | int]:
    """Keep bounded non-secret facts and omit every unknown field."""
    source = value if isinstance(value, Mapping) else {}
    clean: dict[str, str | int] = {}
    for key in sorted(_TEXT_FIELDS):
        if key == "native_diagnostic_ref":
            continue
        item = source.get(key)
        if isinstance(item, str) and item.strip():
            limit = (
                _MAX_CAPTURE_PATH_LENGTH
                if key in {"native_capture_path", "identity_output_snippet"}
                else _MAX_TEXT_LENGTH
            )
            clean[key] = item.strip()[:limit]
    for key in sorted(_INTEGER_FIELDS):
        item = source.get(key)
        if isinstance(item, int) and not isinstance(item, bool):
            clean[key] = item
    reference = valid_native_diagnostic_reference(source.get("native_diagnostic_ref"))
    if reference is not None:
        clean["native_diagnostic_ref"] = reference
        clean["native_diagnostic_command"] = native_diagnostic_command(reference)
    return clean


__all__ = [
    "NATIVE_DIAGNOSTIC_REFERENCE_PATTERN",
    "native_diagnostic_command",
    "redacted_evidence_document",
    "valid_native_diagnostic_reference",
]
