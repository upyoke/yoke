"""Bounded evidence shared by relay clients and the control plane."""

from __future__ import annotations

import re
from typing import Any, Mapping


_TEXT_FIELDS = frozenset(
    {
        "adapter_revision",
        "diagnostic_availability",
        "machine_id",
        "native_diagnostic_ref",
        "native_error_class",
        "native_error_sha256",
        "native_error_step",
        "native_instruction_sha256",
        "relay_id",
        "result_code",
        "surface",
    }
)
_INTEGER_FIELDS = frozenset({"diagnostic_expires_at", "duration_ms", "exit_code"})
_MAX_TEXT_LENGTH = 128
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
            clean[key] = item.strip()[:_MAX_TEXT_LENGTH]
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
