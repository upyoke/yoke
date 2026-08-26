"""Operator-first output for machine-user-local native diagnostics."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from yoke_contracts.session_control.evidence import redacted_evidence_document
from yoke_contracts.session_control.launch_permission_bypass import (
    CLAUDE_BYPASS_DISCLAIMER_RECOVERY,
)


# A failure class the operator can act on names its own recovery step here,
# so the answer arrives with the diagnosis instead of in a separate manual.
_FAILURE_RECOVERY = {
    "permission_bypass_unaccepted": CLAUDE_BYPASS_DISCLAIMER_RECOVERY,
}


def native_diagnostic_fields(
    evidence: Mapping[str, Any] | None,
    *,
    fallback_machine: Any = None,
) -> list[tuple[str, Any]]:
    """Return safe fields even when private stream retention was unavailable."""
    safe = redacted_evidence_document(evidence)
    reference = safe.get("native_diagnostic_ref")
    failure_class = safe.get("native_error_class")
    availability = safe.get("diagnostic_availability")
    if not any((reference, failure_class, availability)):
        return []
    location = " / ".join(
        str(value)
        for value in (
            safe.get("machine_id") or fallback_machine,
            safe.get("relay_id"),
        )
        if value
    )
    fields: list[tuple[str, Any]] = [
        ("Native failure", failure_class),
        ("Failure step", safe.get("native_error_step")),
    ]
    recovery = _FAILURE_RECOVERY.get(str(failure_class or ""))
    if recovery:
        fields.append(("Recovery", recovery))
    fields.extend(
        [
            ("Diagnostic availability", availability),
            ("Diagnostic location", location),
        ]
    )
    if reference:
        fields.extend(
            [
                ("Native diagnostic", reference),
                ("Diagnostic expires", safe.get("diagnostic_expires_at")),
                ("Retrieve diagnostic", safe.get("native_diagnostic_command")),
            ]
        )
    else:
        fields.append(("Native detail", "local detail unavailable"))
    return fields


__all__ = ["native_diagnostic_fields"]
