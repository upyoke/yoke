"""Name a baseline probe call that raised, keeping only safe typed metadata.

A typed host-control failure already carries its code, phase and recovery; a
staging failure carries bounded staging diagnostics. Both reach the receipt.
Exception text, command argv, owned paths, hashes and command output never do.
"""

from __future__ import annotations

import re
from typing import Any

from yoke_contracts.machine_qa_failures import (
    HostControlLocalError,
    bounded_machine_qa_diagnostic,
)

BRIDGE_CALL_RAISED_CAUSE = "bridge_call_raised"
BRIDGE_CALL_RAISED_REASON = "the GUI-session bridge could not be called at all"
BRIDGE_CALL_RAISED_RECOVERY = (
    "check SSH reachability and Terminal.app control on the host, then "
    "re-run `yoke test-machine verify`"
)
HOST_SESSION_UNAVAILABLE_CAUSE = "host_session_command_unavailable"
HOST_SESSION_UNAVAILABLE_REASON = "the SSH user-session command did not return"
HOST_SESSION_UNAVAILABLE_RECOVERY = (
    "Check SSH reachability and retry the baseline probe."
)
STAGING_STEP_LIMIT = 8
_IDENTIFIER = re.compile(r"[a-z][a-z0-9_]{0,79}")
_LABEL = re.compile(r"[A-Za-z][A-Za-z0-9_ ]{0,63}")
_STAGING_FIELDS = (
    "total_bytes",
    "last_verified_offset",
    "remote_directory_owned",
    "cleanup",
    "local_cleanup",
    "cleanup_exit_code",
    "upload_elapsed_seconds",
)
_STEP_FIELDS = ("phase", "exit_code", "outcome", "duration_seconds")


def _safe_scalar(value: Any) -> bool:
    if isinstance(value, (bool, int, float)):
        return True
    return isinstance(value, str) and _LABEL.fullmatch(value) is not None


def _staging_metadata(error: BaseException) -> dict[str, Any] | None:
    diagnostics = getattr(error, "staging_diagnostics", None)
    if not isinstance(diagnostics, dict):
        return None
    staging = {
        key: diagnostics[key]
        for key in _STAGING_FIELDS
        if _safe_scalar(diagnostics.get(key))
    }
    steps = diagnostics.get("steps")
    if isinstance(steps, list):
        staging["steps"] = [
            {key: step[key] for key in _STEP_FIELDS if _safe_scalar(step.get(key))}
            for step in steps[-STAGING_STEP_LIMIT:]
            if isinstance(step, dict)
        ]
    return staging or None


def _typed_failure(error: HostControlLocalError) -> dict[str, Any] | None:
    code, phase = error.code, error.phase
    recovery = bounded_machine_qa_diagnostic(error.recovery_hint)
    if not (
        isinstance(code, str)
        and _IDENTIFIER.fullmatch(code)
        and isinstance(phase, str)
        and _IDENTIFIER.fullmatch(phase)
        and recovery
    ):
        return None
    failure: dict[str, Any] = {
        "cause": code,
        "phase": phase,
        "reason": f"the host-control phase {phase} failed ({code})",
        "recovery": recovery,
    }
    if isinstance(error.exit_code, int):
        failure["host_exit_code"] = error.exit_code
    return failure


def raised_failure(
    error: BaseException, *, classify_gui_failures: bool
) -> dict[str, Any]:
    """Return the cause, reason and recovery for a probe call that raised."""
    failure = (
        _typed_failure(error) if isinstance(error, HostControlLocalError) else None
    )
    if failure is None:
        failure = (
            {
                "cause": BRIDGE_CALL_RAISED_CAUSE,
                "reason": BRIDGE_CALL_RAISED_REASON,
                "recovery": BRIDGE_CALL_RAISED_RECOVERY,
            }
            if classify_gui_failures
            else {
                "cause": HOST_SESSION_UNAVAILABLE_CAUSE,
                "reason": HOST_SESSION_UNAVAILABLE_REASON,
                "recovery": HOST_SESSION_UNAVAILABLE_RECOVERY,
            }
        )
        failure["error_type"] = type(error).__name__
    staging = _staging_metadata(error)
    if staging:
        failure["staging"] = staging
    return failure


__all__ = [
    "BRIDGE_CALL_RAISED_CAUSE",
    "BRIDGE_CALL_RAISED_REASON",
    "HOST_SESSION_UNAVAILABLE_CAUSE",
    "STAGING_STEP_LIMIT",
    "raised_failure",
]
