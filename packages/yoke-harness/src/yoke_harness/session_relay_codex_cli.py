"""Supported ``codex exec`` create and exact stopped-thread resume port."""

from __future__ import annotations

import json
import os
import selectors
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Callable

from yoke_harness.session_relay_codex import CodexNativeOutcome, CodexNativeRequest


LAUNCH_CONTEXT_ENV = "YOKE_SESSION_LAUNCH_CONTEXT"
_MAX_LINE_BYTES = 1024 * 1024
_MAX_CAPTURE_BYTES = 4 * 1024 * 1024
ThreadIdentityResolver = Callable[[str, Path], tuple[str, str] | None]


def _default_identity_resolver(thread_id: str, checkout: Path) -> tuple[str, str] | None:
    from yoke_harness.session_relay_codex_app_server import resolve_thread_identity

    return resolve_thread_identity(thread_id, checkout)


def _launch_environment(request: CodexNativeRequest) -> dict[str, str]:
    env = dict(os.environ)
    env["YOKE_EXECUTOR"] = "codex"
    env["CODEX_INTERNAL_ORIGINATOR_OVERRIDE"] = request.surface
    if request.job_kind == "launch" and request.launch_attestation:
        env[LAUNCH_CONTEXT_ENV] = json.dumps(
            {
                "launch_id": request.job_id,
                "attestation": request.launch_attestation,
            },
            separators=(",", ":"),
        )
    return env


def _base_command(binary: str, request: CodexNativeRequest) -> list[str]:
    command = [
        binary,
        "exec",
        "--json",
        "--sandbox",
        "read-only",
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

    threading.Thread(target=drain, daemon=True, name="yoke-codex-relay-reap").start()


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
        identity_resolver: ThreadIdentityResolver = _default_identity_resolver,
    ) -> None:
        self.binary = binary
        self.startup_timeout = startup_timeout
        self.identity_resolver = identity_resolver

    def _binary(self) -> str | None:
        return shutil.which(self.binary) if os.sep not in self.binary else self.binary

    def _spawn(
        self, request: CodexNativeRequest, *, resume: bool
    ) -> subprocess.Popen[bytes] | None:
        binary = self._binary()
        if not binary or not request.checkout.is_dir():
            return None
        command = _base_command(binary, request)
        if resume:
            command.extend(["resume", str(request.target_session_id)])
        command.append(request.native_instruction)
        try:
            return subprocess.Popen(
                command,
                cwd=request.checkout,
                env=_launch_environment(request),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
        except OSError:
            return None

    def _await_identity(
        self,
        process: subprocess.Popen[bytes],
        request: CodexNativeRequest,
    ) -> CodexNativeOutcome:
        if process.stdout is None:
            _stop(process)
            return CodexNativeOutcome("outcome_unknown")
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
            return CodexNativeOutcome("outcome_unknown", exit_code=exit_code)
        try:
            identity = self.identity_resolver(found, request.checkout)
        except Exception:
            identity = None
        expected = request.target_session_id if request.job_kind == "wake" else found
        correlated = bool(identity == (found, found) and found == expected)
        if not correlated:
            _stop(process)
            return CodexNativeOutcome(
                "outcome_unknown",
                native_session_id=found,
                identity_correlated=False,
                exit_code=process.poll(),
            )
        _discard_and_reap(process)
        return CodexNativeOutcome(
            "accepted",
            native_session_id=found,
            identity_correlated=True,
        )

    def create(self, request: CodexNativeRequest) -> CodexNativeOutcome:
        process = self._spawn(request, resume=False)
        if process is None:
            return CodexNativeOutcome("not_created")
        return self._await_identity(process, request)

    def wake(self, request: CodexNativeRequest) -> CodexNativeOutcome:
        if request.target_liveness != "ended" or not request.target_session_id:
            return CodexNativeOutcome("unsupported_surface")
        process = self._spawn(request, resume=True)
        if process is None:
            return CodexNativeOutcome("not_found")
        return self._await_identity(process, request)


__all__ = ["CodexCliTransport", "LAUNCH_CONTEXT_ENV"]
