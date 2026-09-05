"""Documented Cursor CLI transport for relay-owned creates and resumes.

Both routes run one print-mode ``cursor-agent`` turn and exit. A create uses
the native new-chat path and lets Cursor assign the conversation identity; a
resume alone names an existing conversation with ``--resume``.

The turn runs under the shared native supervisor, the same one Claude creates
and resumes use, so the native's own account survives the process. A create
also reads that capture for the moment it takes to see a native reject its
own flags: a refusal reported now names the model or credential that failed,
where silence would burn the whole registration deadline instead.

Registration is the native's own: cursor-agent runs the installed hook chain
in print mode, so the launch attestation it inherits registers the
vendor-created identity and the relay binds that registered candidate.
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
    CursorCreateRequest,
    CursorNativeResult,
    CursorWakeRequest,
)
from yoke_harness.session_relay_environment import native_session_environment
from yoke_harness.session_relay_inventory import resolve_native_cli
from yoke_harness.session_relay_native_create import immediate_native_refusal
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


def cursor_environment(
    request: CursorCreateRequest | CursorWakeRequest,
) -> dict[str, str]:
    """Build the child environment, naming the model the turn asked for.

    ``--model`` tells cursor-agent which variant to run; ``YOKE_MODEL``
    tells the session inside it which variant it was asked for. Codex
    passes both, and a child that gets only the flag reports no ask at all
    when its own hooks register it. A create also carries the launch
    context its first hook registers from.
    """
    launch = request if isinstance(request, CursorCreateRequest) else None
    return native_session_environment(
        executor="cursor",
        provider="cursor",
        model=request.requested_model,
        markers={"CURSOR_INVOKED_AS": "cursor-agent"},
        launch_id=launch.launch_id if launch else None,
        launch_attestation=launch.launch_attestation if launch else None,
    )


def cursor_turn_command(
    binary: str,
    *,
    resume_session_id: str | None,
    checkout: str,
    instruction: str,
    model: str | None,
) -> list[str]:
    """Return a native new-chat or exact-resume print-mode invocation.

    Omitting ``resume_session_id`` is the create contract. Passing even a
    fresh id to ``--resume`` selects Cursor's resume branch, which suppresses
    the opening ``sessionStart`` hook that launch registration depends on.
    """
    command = [binary]
    if resume_session_id is not None:
        command.extend(("--resume", resume_session_id))
    command.extend(
        (
            "--print",
            "--output-format",
            "json",
            "--workspace",
            checkout,
            "--trust",
            *CURSOR_CLI_BYPASS_ARGUMENTS,
        )
    )
    if model:
        command.extend(("--model", model))
    command.append(instruction)
    return command


class CursorCliTransport:
    """Create a native Cursor chat or resume one exact existing chat."""

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
        request: CursorCreateRequest | CursorWakeRequest,
        binary: str,
        resume_session_id: str | None,
        *,
        supervision_kind: str,
        attempt_id: str,
        lease_id: str,
    ) -> SupervisedNative | None:
        return spawn_supervised_native(
            cursor_turn_command(
                binary,
                resume_session_id=resume_session_id,
                checkout=str(request.checkout),
                instruction=request.native_instruction,
                model=request.requested_model,
            ),
            checkout=request.checkout,
            environment=cursor_environment(request),
            attempt_id=attempt_id,
            native_session_id=resume_session_id,
            binary_source="path",
            supervision_kind=supervision_kind,
            lease_id=lease_id,
            process_factory=self.process_factory,
        )

    def new_session(self, request: CursorCreateRequest) -> CursorNativeResult:
        """Start the launch's first turn through Cursor's native new-chat path."""
        started = time.monotonic()
        binary = self._binary()
        if binary is None or not request.checkout.is_dir():
            return CursorNativeResult("not_created")
        spawned = self._start_turn(
            request,
            binary,
            None,
            supervision_kind="launch",
            attempt_id=request.launch_id,
            lease_id="",
        )
        if spawned is None:
            return CursorNativeResult("not_created", duration_ms=_elapsed_ms(started))
        refusal = immediate_native_refusal(spawned.capture_path)
        if refusal is not None and refusal.exit_code != 0:
            output = refusal.stderr + b"\n" + refusal.stdout
            return CursorNativeResult(
                "not_created",
                exit_code=-1 if refusal.exit_code is None else refusal.exit_code,
                duration_ms=_elapsed_ms(started),
                native_stderr=output,
                phase="spawn",
                diagnostic_ref=spawned.diagnostic_ref,
                capture_path=str(spawned.capture_path),
                native_pid=spawned.pid,
            )
        return CursorNativeResult(
            "native_created",
            duration_ms=_elapsed_ms(started),
            phase="registration_pending",
            diagnostic_ref=spawned.diagnostic_ref,
            capture_path=str(spawned.capture_path),
            native_pid=spawned.pid,
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
        spawned = self._start_turn(
            request,
            binary,
            session_id,
            supervision_kind="resume",
            attempt_id=request.attempt_id,
            lease_id=request.lease_id,
        )
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
    "cursor_environment",
    "cursor_turn_command",
]
