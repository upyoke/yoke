"""Documented Cursor CLI create-chat and exact-session resume transport."""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import threading
import time
from typing import Callable
from uuid import UUID

from yoke_harness.session_relay_cursor import (
    CursorCreateRequest,
    CursorNativeResult,
    CursorWakeRequest,
)
from yoke_harness.session_relay_environment import native_session_environment


CURSOR_AGENT_EXECUTABLE = "cursor-agent"
CURSOR_NATIVE_TIMEOUT_SECONDS = 20
_STARTUP_SETTLE_SECONDS = 0.05

CommandRunner = Callable[..., subprocess.CompletedProcess[str]]
ProcessFactory = Callable[..., subprocess.Popen[bytes]]


def _elapsed_ms(started: float) -> int:
    return max(0, int((time.monotonic() - started) * 1000))


def _session_id(value: str) -> str | None:
    try:
        return str(UUID(value.strip()))
    except (AttributeError, TypeError, ValueError):
        return None


def _environment(
    *,
    surface_version: str,
    launch_id: str | None = None,
    attestation: str | None = None,
) -> dict[str, str]:
    return native_session_environment(
        executor="cursor",
        executor_version=surface_version,
        provider="cursor",
        markers={"CURSOR_INVOKED_AS": "cursor-agent"},
        launch_id=launch_id,
        launch_attestation=attestation,
    )


def _reap(process: subprocess.Popen[bytes]) -> None:
    def wait() -> None:
        try:
            process.wait()
        except (OSError, subprocess.SubprocessError):
            pass

    threading.Thread(target=wait, daemon=True, name="yoke-cursor-relay-reap").start()


class CursorCliTransport:
    """Run only installed, documented Cursor CLI commands at an exact ID."""

    def __init__(
        self,
        *,
        binary: str = CURSOR_AGENT_EXECUTABLE,
        command_runner: CommandRunner = subprocess.run,
        process_factory: ProcessFactory = subprocess.Popen,
    ) -> None:
        self.binary = binary
        self.command_runner = command_runner
        self.process_factory = process_factory

    def _binary(self) -> str | None:
        if os.sep in self.binary:
            return self.binary if Path(self.binary).is_file() else None
        return shutil.which(self.binary)

    def _create_empty_chat(
        self,
        binary: str,
        checkout: Path,
        surface_version: str,
    ) -> str | None:
        try:
            completed = self.command_runner(
                [binary, "create-chat"],
                cwd=checkout,
                env=_environment(surface_version=surface_version),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                timeout=CURSOR_NATIVE_TIMEOUT_SECONDS,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            return None
        if completed.returncode != 0 or len(completed.stdout) > 256:
            return None
        return _session_id(completed.stdout)

    def _start_turn(
        self,
        binary: str,
        *,
        checkout: Path,
        session_id: str,
        instruction: str,
        surface_version: str,
        model: str | None = None,
        launch_id: str | None = None,
        attestation: str | None = None,
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
        ]
        if model:
            command.extend(("--model", model))
        command.append(instruction)
        try:
            process = self.process_factory(
                command,
                cwd=checkout,
                env=_environment(
                    surface_version=surface_version,
                    launch_id=launch_id,
                    attestation=attestation,
                ),
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

    def create_chat(self, request: CursorCreateRequest) -> CursorNativeResult:
        started = time.monotonic()
        binary = self._binary()
        if binary is None or not request.checkout.is_dir():
            return CursorNativeResult("not_created")
        session_id = self._create_empty_chat(
            binary,
            request.checkout,
            request.surface_version,
        )
        if session_id is None:
            return CursorNativeResult("not_created", duration_ms=_elapsed_ms(started))
        process, returncode = self._start_turn(
            binary,
            checkout=request.checkout,
            session_id=session_id,
            instruction=request.native_instruction,
            surface_version=request.surface_version,
            model=request.requested_model,
            launch_id=request.launch_id,
            attestation=request.launch_attestation,
        )
        if process is None or (returncode is not None and returncode != 0):
            return CursorNativeResult(
                "outcome_unknown",
                native_session_id=session_id,
                exit_code=returncode,
                duration_ms=_elapsed_ms(started),
            )
        return CursorNativeResult(
            "native_created",
            native_session_id=session_id,
            exit_code=returncode,
            duration_ms=_elapsed_ms(started),
        )

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
            surface_version=request.surface_version,
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
    "CURSOR_NATIVE_TIMEOUT_SECONDS",
    "CursorCliTransport",
]
