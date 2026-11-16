"""One finished native's own account, bounded for remote readers.

The relay's liveness and launch-death reports both carry what a native said
as it ended: its exit, when it exited, and the last of its stderr. Both read
it here from the capture retained under the attempt's diagnostic reference.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from yoke_contracts.session_control.evidence import native_stderr_excerpt
from yoke_contracts.timestamps import format_instant
from yoke_harness.session_relay_native_diagnostics import (
    NativeDiagnosticError,
    diagnostic_reference,
    native_diagnostic_path,
    read_native_capture,
)


def native_account(launch_id: str, *, state_dir: Path | None) -> dict[str, Any]:
    """Read bounded native diagnostics for remote readers."""
    try:
        reference = diagnostic_reference(launch_id)
        capture = read_native_capture(
            native_diagnostic_path(reference, state_dir=state_dir, create=False)
        )
    except NativeDiagnosticError:
        return {}
    if capture is None:
        return {}
    account: dict[str, Any] = {"native_diagnostic_ref": reference}
    if capture.exit_code is not None:
        account["exit_code"] = capture.exit_code
    if capture.exit_at is not None:
        account["native_exit_at"] = format_instant(capture.exit_at)
    tail = capture.tail
    if tail:
        account["native_stderr_tail"] = tail
    excerpt = native_stderr_excerpt(capture.stderr.decode("utf-8", errors="replace"))
    if excerpt:
        account["native_stderr_excerpt"] = excerpt
    return account


__all__ = ["native_account"]
