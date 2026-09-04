"""Write a Cursor ACP turn's own account where every other harness writes one.

A Claude or Codex launch runs under the supervisor, which streams the native's
output into ``nd-<launch-id>.capture`` and stamps how it exited. A Cursor
launch has no such process to watch: the relay speaks the ACP protocol itself,
so the only account of the turn lives in memory — the child's stderr in a
bounded drain, and the turn's fate in a thread that used to discard it inside
a bare ``except``. A Cursor launch that failed therefore closed with nothing
at all to read, on either the relay or the control plane.

This turns those two facts into the same envelope every other harness writes.
The turn's outcome goes in the stdout half because the ACP child's real stdout
is the protocol stream the client already consumed and must not repeat; the
child's stderr goes in the stderr half unchanged. The account is written once
while the child is still alive and again once it has exited, so a reader that
arrives between those two moments — the relay poll that watches for exactly
this death — still finds the reason rather than an empty directory.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import logging
from pathlib import Path
import time
from typing import Any

from yoke_harness.session_relay_native_capture_format import (
    STATE_EXITED,
    STATE_RUNNING,
    compose_capture,
    utc_stamp,
)
from yoke_harness.session_relay_native_diagnostics import (
    NativeDiagnosticError,
    cleanup_native_diagnostics,
    diagnostic_reference,
    native_diagnostic_path,
    write_native_capture,
)


#: How long the relay follows one prompted turn before it stops reading it.
CURSOR_ACP_TURN_SECONDS = 120.0
#: One turn outcome, bounded the way the capture's own tail line is.
OUTCOME_MAX_CHARS = 240
_LOGGER = logging.getLogger(__name__)


def _bounded(text: str) -> str:
    return " ".join(str(text).split())[:OUTCOME_MAX_CHARS]


@dataclass
class AcpTurnRecord:
    """One prompted ACP turn, and the capture its outcome is written to."""

    #: Absent for a turn nobody can name a capture for — a resume, whose
    #: attempt is settled from its own report rather than from a file.
    capture: Path | None = None
    outcome: str = field(
        default_factory=lambda: (
            f"turn did not answer within {CURSOR_ACP_TURN_SECONDS:.0f}s"
        )
    )

    def deadline(self) -> float:
        """The monotonic instant after which this turn stops being followed."""
        return time.monotonic() + CURSOR_ACP_TURN_SECONDS

    def answered(self, payload: dict[str, Any]) -> None:
        """Record the agent's own response to the prompt that started this."""
        error = payload.get("error")
        if error is not None:
            self.outcome = _bounded(f"turn refused: {json.dumps(error, default=str)}")
            return
        result = payload.get("result")
        stop = (result or {}).get("stopReason") if isinstance(result, dict) else None
        self.outcome = _bounded(f"turn answered: stopReason={stop or 'unspecified'}")

    def failed(self, error: BaseException) -> None:
        """Record — never discard — whatever ended the turn early."""
        self.outcome = _bounded(f"turn failed: {type(error).__name__}: {error}")
        _LOGGER.warning("cursor ACP turn failed: %s", self.outcome, exc_info=error)

    def record_open(self, stderr: bytes) -> None:
        """Write the account while the child that produced it is still alive."""
        self._write(stderr, state=STATE_RUNNING, exit_code=None)

    def record_exit(self, stderr: bytes, exit_code: int | None) -> None:
        """Write the settled account, which is what names how the child ended."""
        self._write(stderr, state=STATE_EXITED, exit_code=exit_code)

    def _write(self, stderr: bytes, *, state: str, exit_code: int | None) -> None:
        if self.capture is None:
            return
        payload = compose_capture(
            stdout=f"{self.outcome}\n".encode(),
            stderr=bytes(stderr),
            state=state,
            exit_code=exit_code,
            exit_at=utc_stamp(time.time()) if state == STATE_EXITED else None,
        )
        try:
            write_native_capture(self.capture, payload)
        except NativeDiagnosticError as exc:
            # The turn's outcome is the caller's; losing its transcript must
            # not also lose the process the caller is still shutting down.
            _LOGGER.warning("cursor ACP capture unavailable: %s", exc)


def turn_record(
    launch_id: str | None,
    *,
    state_dir: Path | None = None,
) -> AcpTurnRecord:
    """Return the record for one turn, capturing it when a launch names one."""
    if not launch_id:
        return AcpTurnRecord()
    try:
        reference = diagnostic_reference(launch_id)
        cleanup_native_diagnostics(state_dir)
        return AcpTurnRecord(native_diagnostic_path(reference, state_dir=state_dir))
    except RuntimeError as exc:
        # Where the capture lives resolves through this machine's relay
        # instance, which an unconfigured machine or a test process cannot
        # answer. Every one of those refusals is a RuntimeError, and none of
        # them is a reason to fail the turn the capture merely describes.
        _LOGGER.warning("cursor ACP capture could not be opened: %s", exc)
        return AcpTurnRecord()


__all__ = [
    "AcpTurnRecord",
    "CURSOR_ACP_TURN_SECONDS",
    "OUTCOME_MAX_CHARS",
    "turn_record",
]
