"""Typed, bounded failures from credential-local Machine QA execution."""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Any


MACHINE_QA_DIAGNOSTIC_LIMIT = 512
_PRIVATE_KEY_BLOCK = re.compile(
    r"-----BEGIN [^-\n]*PRIVATE KEY-----.*?"
    r"-----END [^-\n]*PRIVATE KEY-----",
    re.DOTALL,
)


def bounded_machine_qa_diagnostic(
    value: Any,
    secrets: Sequence[str] = (),
) -> str:
    """Return one single-line, secret-free diagnostic excerpt."""
    text = str(value or "")
    for secret in sorted(
        {secret for secret in secrets if secret}, key=len, reverse=True
    ):
        text = text.replace(secret, "[REDACTED]")
    text = _PRIVATE_KEY_BLOCK.sub("[REDACTED]", text)
    text = " ".join(text.split())
    if len(text) <= MACHINE_QA_DIAGNOSTIC_LIMIT:
        return text
    return text[: MACHINE_QA_DIAGNOSTIC_LIMIT - 1] + "…"


class HostControlLocalError(RuntimeError):
    """One executing-machine host-control phase failed with safe evidence."""

    def __init__(
        self,
        *,
        code: str,
        phase: str,
        detail: str,
        recovery_hint: str,
        exit_code: int | None = None,
        stderr: str = "",
    ) -> None:
        self.code = code
        self.phase = phase
        self.exit_code = exit_code
        self.stderr = bounded_machine_qa_diagnostic(stderr)
        self.recovery_hint = recovery_hint
        safe_detail = bounded_machine_qa_diagnostic(detail)
        fields = [f"phase={phase}", f"exit_code={exit_code}"]
        if self.stderr:
            fields.append(f"stderr={self.stderr}")
        super().__init__(f"{safe_detail} ({'; '.join(fields)})")


def host_control_failure(
    error: BaseException,
    *,
    phase: str,
) -> tuple[str, str, str]:
    """Classify a local failure without exposing an untrusted exception body."""
    if isinstance(error, HostControlLocalError):
        return error.code, str(error), error.recovery_hint
    return (
        "host_control_local_execution_failed",
        "Local host-control execution failed "
        f"(phase={phase}; error_type={type(error).__name__})",
        "Inspect the named phase, repair that host operation, then retry.",
    )


__all__ = [
    "MACHINE_QA_DIAGNOSTIC_LIMIT",
    "HostControlLocalError",
    "bounded_machine_qa_diagnostic",
    "host_control_failure",
]
