"""Documented Cursor CLI exact-session resume transport.

Resume prompts a session that already exists and already registered, so a
detached print-mode turn against it is bounded by a session Yoke can already
see. Creating a session this way is not: nothing owns the resulting native
and nothing registers it, which is why launches use the ACP transport.

The turn runs under the shared native supervisor, the same one Claude resumes
use. This transport used to send both of the native's streams to ``/dev/null``,
so a cursor resume that refused reported a bare exit code and its reason was
gone the moment the process was.
"""

from __future__ import annotations

import subprocess
import time
from typing import Callable
from uuid import UUID

from yoke_contracts.session_control.launch_permission_bypass import (
    CURSOR_CLI_BYPASS_ARGUMENTS,
)
from yoke_harness.session_relay_cursor import (
    CursorNativeResult,
    CursorWakeRequest,
)
from yoke_harness.session_relay_environment import native_session_environment
from yoke_harness.session_relay_inventory import resolve_native_cli
from yoke_harness.session_relay_native_spawn import (
    SupervisedNative,
    spawn_supervised_native,
)


CURSOR_AGENT_EXECUTABLE = "cursor-agent"

ProcessFactory = Callable[..., subprocess.Popen[bytes]]


def _elapsed_ms(started: float) -> int:
    return max(0, int((time.monotonic() - started) * 1000))


def _session_id(value: str) -> str | None:
    try:
        return str(UUID(value.strip()))
    except (AttributeError, TypeError, ValueError):
        return None


def _environment(model: str | None) -> dict[str, str]:
    """Build the child environment, naming the model the turn asked for.

    ``--model`` tells cursor-agent which variant to run; ``YOKE_MODEL``
    tells the session inside it which variant it was asked for. Codex
    passes both, and a child that gets only the flag reports no ask at all
    when its own hooks register it.
    """
    return native_session_environment(
        executor="cursor",
        provider="cursor",
        model=model,
        markers={"CURSOR_INVOKED_AS": "cursor-agent"},
    )


class CursorCliTransport:
    """Resume one installed, documented Cursor CLI session at an exact ID."""

    def __init__(
        self,
        *,
        binary: str = CURSOR_AGENT_EXECUTABLE,
        process_factory: ProcessFactory = subprocess.Popen,
    ) -> None:
        self.binary = binary
        self.process_factory = process_factory

    def _binary(self) -> str | None:
        return resolve_native_cli(self.binary)

    def _start_turn(
        self,
        request: CursorWakeRequest,
        binary: str,
        session_id: str,
    ) -> SupervisedNative | None:
        """Start one supervised print-mode resume, naming the model asked for.

        ``--model`` is the only channel cursor-agent honors for this: the
        ACP ``session/new`` model parameter is accepted and ignored, so a
        session created there is born at the machine default and a resume
        that omits the flag runs the default too. Naming it here sticks —
        the conversation keeps the variant for later resumes that omit it.
        """
        model = request.requested_model
        command = [
            binary,
            "--resume",
            session_id,
            "--print",
            "--output-format",
            "json",
            "--workspace",
            str(request.checkout),
            "--trust",
            *CURSOR_CLI_BYPASS_ARGUMENTS,
        ]
        if model:
            command.extend(("--model", model))
        command.append(request.native_instruction)
        return spawn_supervised_native(
            command,
            checkout=request.checkout,
            environment=_environment(model),
            attempt_id=request.attempt_id,
            native_session_id=session_id,
            binary_source="path",
            lease_id=request.lease_id,
            process_factory=self.process_factory,
        )

    def resume_chat(self, request: CursorWakeRequest) -> CursorNativeResult:
        """Start the turn and report the spawn; the settlement reports its end.

        The relay poll is gone long before a cursor turn finishes, so this
        reports only that the native started. The capture the supervisor is
        streaming into carries the rest, and the shared resume settlement
        turns it into this attempt's terminal result on a later poll.
        """
        started = time.monotonic()
        binary = self._binary()
        session_id = _session_id(request.target_session_id)
        if binary is None or session_id is None or not request.checkout.is_dir():
            return CursorNativeResult("not_found")
        spawned = self._start_turn(request, binary, session_id)
        if spawned is None:
            return CursorNativeResult("failed", duration_ms=_elapsed_ms(started))
        return CursorNativeResult(
            "accepted",
            duration_ms=_elapsed_ms(started),
            diagnostic_ref=spawned.diagnostic_ref,
            capture_path=str(spawned.capture_path),
        )


__all__ = [
    "CURSOR_AGENT_EXECUTABLE",
    "CursorCliTransport",
]
