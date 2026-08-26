"""Documented Cursor CLI exact-session resume transport.

Resume prompts a session that already exists and already registered, so a
detached print-mode turn against it is bounded by a session Yoke can already
see. Creating a session this way is not: nothing owns the resulting native
and nothing registers it, which is why launches use the ACP transport.
"""

from __future__ import annotations

from pathlib import Path
import subprocess
import threading
import time
from typing import Callable
from uuid import UUID

from yoke_harness.session_relay_cursor import (
    CursorNativeResult,
    CursorWakeRequest,
)
from yoke_harness.session_relay_environment import native_session_environment
from yoke_harness.session_relay_inventory import resolve_native_cli


CURSOR_AGENT_EXECUTABLE = "cursor-agent"
_STARTUP_SETTLE_SECONDS = 0.05

ProcessFactory = Callable[..., subprocess.Popen[bytes]]


def _elapsed_ms(started: float) -> int:
    return max(0, int((time.monotonic() - started) * 1000))


def _session_id(value: str) -> str | None:
    try:
        return str(UUID(value.strip()))
    except (AttributeError, TypeError, ValueError):
        return None


def _environment() -> dict[str, str]:
    return native_session_environment(
        executor="cursor",
        provider="cursor",
        markers={"CURSOR_INVOKED_AS": "cursor-agent"},
    )


def _reap(process: subprocess.Popen[bytes]) -> None:
    def wait() -> None:
        try:
            process.wait()
        except (OSError, subprocess.SubprocessError):
            pass

    threading.Thread(target=wait, daemon=True, name="yoke-cursor-relay-reap").start()


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
        binary: str,
        *,
        checkout: Path,
        session_id: str,
        instruction: str,
        model: str | None = None,
    ) -> tuple[subprocess.Popen[bytes] | None, int | None]:
        command = [
            binary,
            "--resume",
            session_id,
            "--print",
            "--output-format",
            "json",
            "--workspace",
            str(checkout),
            "--trust",
        ]
        if model:
            command.extend(("--model", model))
        command.append(instruction)
        try:
            process = self.process_factory(
                command,
                cwd=checkout,
                env=_environment(),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
        except OSError:
            return None, None
        try:
            returncode = process.wait(timeout=_STARTUP_SETTLE_SECONDS)
        except subprocess.TimeoutExpired:
            _reap(process)
            return process, None
        return process, int(returncode)

    def resume_chat(self, request: CursorWakeRequest) -> CursorNativeResult:
        started = time.monotonic()
        binary = self._binary()
        session_id = _session_id(request.target_session_id)
        if binary is None or session_id is None or not request.checkout.is_dir():
            return CursorNativeResult("not_found")
        process, returncode = self._start_turn(
            binary,
            checkout=request.checkout,
            session_id=session_id,
            instruction=request.native_instruction,
        )
        if process is None:
            return CursorNativeResult("failed", duration_ms=_elapsed_ms(started))
        code = "accepted" if returncode in {None, 0} else "failed"
        return CursorNativeResult(
            code,
            exit_code=returncode,
            duration_ms=_elapsed_ms(started),
        )


__all__ = [
    "CURSOR_AGENT_EXECUTABLE",
    "CursorCliTransport",
]
