"""Supported ``codex exec`` create and exact stopped-thread resume port."""

from __future__ import annotations

import json
import os
import selectors
import subprocess
import threading
import time

from yoke_harness.session_relay_codex import (
    CodexNativeOutcome,
    CodexNativeRequest,
    NativePhase,
)
from yoke_harness.session_relay_detached_worker import MAX_HANDOFF_BYTES
from yoke_harness.session_launch_handoff import LAUNCH_CONTEXT_ENV
from yoke_harness.session_relay_environment import native_session_environment
from yoke_harness.session_relay_inventory import (
    ResolvedNativeCli,
    resolve_native_cli_source,
)
from yoke_harness.session_relay_runtime import wake_operation


_MAX_LINE_BYTES = 1024 * 1024
_MAX_CAPTURE_BYTES = 4 * 1024 * 1024


class _NativePhaseError(Exception):
    """The native never reached the next phase; the phase is the evidence."""

    def __init__(
        self,
        phase: NativePhase,
        *,
        binary_source: str | None = None,
        pid: int | None = None,
    ) -> None:
        super().__init__(phase)
        self.phase = phase
        self.binary_source = binary_source
        self.pid = pid


def _launch_environment(request: CodexNativeRequest) -> dict[str, str]:
    return native_session_environment(
        executor="codex",
        provider="openai",
        model=request.requested_model,
        markers={"CODEX_INTERNAL_ORIGINATOR_OVERRIDE": request.surface},
        launch_id=request.job_id if request.job_kind == "launch" else None,
        launch_attestation=request.launch_attestation,
    )


def _base_command(binary: str, request: CodexNativeRequest) -> list[str]:
    command = [
        binary,
        "exec",
        "--json",
        "--skip-git-repo-check",
    ]
    if request.requested_model:
        command.extend(["--model", request.requested_model])
    return command


def _thread_id(event: object) -> str | None:
    if not isinstance(event, dict) or event.get("type") != "thread.started":
        return None
    value = event.get("thread_id")
    return str(value).strip() if isinstance(value, str) and value.strip() else None


def _discard_and_reap(process: subprocess.Popen[bytes]) -> None:
    def drain() -> None:
        try:
            if process.stdout is not None:
                while process.stdout.read(65_536):
                    pass
            process.wait()
        except (OSError, subprocess.SubprocessError):
            return

    threading.Thread(target=drain, daemon=False, name="yoke-codex-relay-reap").start()


def _stop(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=2)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=2)


class CodexCliTransport:
    """Start one CLI process and return once its exact persistent ID is known."""

    def __init__(
        self,
        *,
        binary: str = "codex",
        startup_timeout: float = 30.0,
        worker: bool = False,
    ) -> None:
        self.binary = binary
        self.startup_timeout = startup_timeout
        self.worker = worker

    @staticmethod
    def _detached(request: CodexNativeRequest) -> CodexNativeOutcome:
        from yoke_harness.session_relay_codex_cli_process import (
            run_detached_operation,
        )

        return run_detached_operation(request)

    def _resolve_binary(self) -> ResolvedNativeCli | None:
        return resolve_native_cli_source(self.binary)

    def _spawn(
        self, request: CodexNativeRequest, *, resume: bool
    ) -> tuple[subprocess.Popen[bytes], str]:
        """Start the native, raising the phase that stopped it short."""
        resolved = self._resolve_binary()
        if resolved is None or not request.checkout.is_dir():
            raise _NativePhaseError("binary_resolve")
        instruction = request.native_instruction.encode()
        if not instruction or len(instruction) > MAX_HANDOFF_BYTES:
            raise _NativePhaseError("instruction_write", binary_source=resolved.source)
        command = _base_command(resolved.path, request)
        if resume:
            command.extend(["resume", str(request.target_thread_id)])
        command.append("-")
        process: subprocess.Popen[bytes] | None = None
        try:
            process = subprocess.Popen(
                command,
                cwd=request.checkout,
                env=_launch_environment(request),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            if process.stdin is None:
                raise OSError("native stdin unavailable")
            process.stdin.write(instruction)
            process.stdin.flush()
            process.stdin.close()
            return process, resolved.source
        except (OSError, subprocess.SubprocessError) as exc:
            started = process is not None
            if process is not None:
                _stop(process)
            raise _NativePhaseError(
                "instruction_write" if started else "spawn",
                binary_source=resolved.source,
                pid=process.pid if process is not None else None,
            ) from exc

    def _await_identity(
        self,
        process: subprocess.Popen[bytes],
        request: CodexNativeRequest,
        *,
        binary_source: str,
    ) -> CodexNativeOutcome:
        """Correlate the native from its own stream, never a second process.

        ``codex exec`` announces the thread it opened on its own stdout, and
        that announcement is the identity. Confirming it through a separate
        ``codex app-server`` cannot work: the vendor exposes a thread only
        once its rollout is persisted, which happens after the turn ends, so
        a create that waited for that confirmation killed every native it
        had just started and reported an unproven outcome instead.
        """
        if process.stdout is None:
            _stop(process)
            return CodexNativeOutcome(
                "outcome_unknown",
                phase="spawn",
                binary_source=binary_source,
                pid=process.pid,
            )
        selector = selectors.DefaultSelector()
        selector.register(process.stdout, selectors.EVENT_READ)
        deadline = time.monotonic() + self.startup_timeout
        buffer = bytearray()
        captured = 0
        found: str | None = None
        try:
            while time.monotonic() < deadline and found is None:
                if process.poll() is not None and not selector.select(0):
                    break
                ready = selector.select(max(0.0, deadline - time.monotonic()))
                if not ready:
                    break
                chunk = os.read(process.stdout.fileno(), 65_536)
                if not chunk:
                    break
                captured += len(chunk)
                if captured > _MAX_CAPTURE_BYTES:
                    break
                buffer.extend(chunk)
                while b"\n" in buffer:
                    raw, _, remainder = buffer.partition(b"\n")
                    buffer = bytearray(remainder)
                    if len(raw) > _MAX_LINE_BYTES:
                        continue
                    try:
                        found = _thread_id(json.loads(raw))
                    except (UnicodeDecodeError, json.JSONDecodeError):
                        continue
                    if found:
                        break
        finally:
            selector.close()
        if not found:
            exit_code = process.poll()
            _stop(process)
            return CodexNativeOutcome(
                "outcome_unknown",
                exit_code=exit_code,
                phase="thread_identity",
                binary_source=binary_source,
                pid=process.pid,
            )
        if request.job_kind == "wake" and found != request.target_thread_id:
            _stop(process)
            return CodexNativeOutcome(
                "outcome_unknown",
                native_session_id=found,
                identity_correlated=False,
                exit_code=process.poll(),
                phase="identity_match",
                binary_source=binary_source,
                pid=process.pid,
            )
        _discard_and_reap(process)
        return CodexNativeOutcome(
            "accepted",
            native_session_id=found,
            identity_correlated=True,
            phase="native_running",
            binary_source=binary_source,
            pid=process.pid,
        )

    def _run(self, request: CodexNativeRequest, *, resume: bool) -> CodexNativeOutcome:
        try:
            process, binary_source = self._spawn(request, resume=resume)
        except _NativePhaseError as failure:
            return CodexNativeOutcome(
                "not_found" if request.job_kind == "wake" else "not_created",
                phase=failure.phase,
                binary_source=failure.binary_source,
                pid=failure.pid,
            )
        return self._await_identity(process, request, binary_source=binary_source)

    def create(self, request: CodexNativeRequest) -> CodexNativeOutcome:
        if not self.worker:
            return self._detached(request)
        return self._run(request, resume=False)

    def wake(self, request: CodexNativeRequest) -> CodexNativeOutcome:
        if not self.worker:
            return self._detached(request)
        if (
            wake_operation(request.wake_mode, request.target_liveness)
            != "message_stopped"
            or not request.target_thread_id
        ):
            return CodexNativeOutcome("unsupported_surface")
        return self._run(request, resume=True)


__all__ = ["CodexCliTransport", "LAUNCH_CONTEXT_ENV"]
