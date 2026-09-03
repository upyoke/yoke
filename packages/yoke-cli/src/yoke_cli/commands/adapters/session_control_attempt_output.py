"""The delivery-attempt table an operator reads when a message went quiet."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any, TextIO

from yoke_contracts.session_control.evidence import redacted_evidence_document
from yoke_contracts.session_control.wake_delivery import (
    delivery_attempt_diagnostic,
)
from yoke_cli.commands.adapters.session_control_native_diagnostic_output import (
    native_diagnostic_fields,
)


def attempt_evidence(attempt: Mapping[str, Any]) -> dict[str, str | int]:
    evidence = attempt.get("evidence")
    return redacted_evidence_document(
        evidence if isinstance(evidence, Mapping) else None
    )


def attempt_diagnostic(attempt: Mapping[str, Any]) -> str:
    """Name why this attempt failed, preferring a retrievable native capture.

    The stored result code is coarse: one `failed` covers a refused
    instruction, a missing binary, a resume that would not spawn, and a
    native that raised. When the relay captured the native's own streams the
    opaque reference is the better answer, because it leads somewhere; when
    it did not, the evidence's named code is what is left, and printing it
    is the difference between an operator diagnosing a stuck wake and one
    reading `failed` against an empty column for two hours.
    """
    evidence = attempt_evidence(attempt)
    reference = evidence.get("native_diagnostic_ref")
    if isinstance(reference, str) and reference:
        return reference
    return delivery_attempt_diagnostic(attempt.get("result_code"), evidence)


def write_attempts(attempts: Iterable[Mapping[str, Any]], stdout: TextIO) -> None:
    from yoke_cli.commands.adapters.session_control_human_output import (
        Column,
        humanize,
        write_summary,
        write_table,
    )

    rows = list(attempts)
    if not rows:
        return
    columns: tuple[Column, ...] = (
        ("ATTEMPT", lambda row: row.get("attempt_id"), None),
        ("TARGET", lambda row: row.get("target_session_id"), None),
        ("TYPE", lambda row: humanize(row.get("attempt_kind")), 16),
        ("RESULT", lambda row: humanize(row.get("result_code")), 18),
        # Escalation says why a wake fired against a live-looking session.
        ("ESCALATION", lambda row: attempt_evidence(row).get("wake_escalation"), 24),
        ("DIAGNOSTIC", attempt_diagnostic, None),
    )
    write_table("DELIVERY ATTEMPTS", columns, rows, stdout, empty="")
    for row in rows:
        fields = native_diagnostic_fields(attempt_evidence(row))
        if not fields:
            continue
        write_summary("NATIVE DIAGNOSTIC", fields, stdout)


__all__ = ["attempt_diagnostic", "attempt_evidence", "write_attempts"]
