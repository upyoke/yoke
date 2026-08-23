"""Detached owner process for Codex app-server turns."""

from __future__ import annotations

import json
import os
from pathlib import Path
import selectors
import subprocess
import sys
import threading
import time
from typing import BinaryIO, Callable, TextIO

from yoke_harness.session_relay_codex import CodexNativeOutcome, CodexNativeRequest


_MODULE = "yoke_harness.session_relay_codex_app_server_process"
_MAX_MESSAGE_BYTES = 64 * 1024
_START_TIMEOUT_SECONDS = 35.0

ProcessFactory = Callable[..., subprocess.Popen[bytes]]


def _request_payload(request: CodexNativeRequest) -> dict[str, object]:
    return {
        "job_kind": request.job_kind,
        "job_id": request.job_id,
        "surface": request.surface,
        "surface_version": request.surface_version,
        "checkout": str(request.checkout),
        "requested_model": request.requested_model,
        "presentation": request.presentation,
        "target_liveness": request.target_liveness,
        "target_session_id": request.target_session_id,
        "native_instruction": request.native_instruction,
    }


def _request_from_payload(payload: object) -> CodexNativeRequest:
    if not isinstance(payload, dict):
        raise ValueError("worker request must be an object")
    return CodexNativeRequest(
        job_kind=str(payload.get("job_kind") or ""),
        job_id=str(payload.get("job_id") or ""),
        surface=str(payload.get("surface") or ""),
        surface_version=str(payload.get("surface_version") or ""),
        checkout=Path(str(payload.get("checkout") or "")),
        requested_model=(
            str(payload["requested_model"]) if payload.get("requested_model") else None
        ),
        presentation=(
            str(payload["presentation"]) if payload.get("presentation") else None
        ),
        target_liveness=(
            str(payload["target_liveness"]) if payload.get("target_liveness") else None
        ),
        target_session_id=(
            str(payload["target_session_id"])
            if payload.get("target_session_id")
            else None
        ),
        native_instruction=str(payload.get("native_instruction") or ""),
    )


def _outcome_payload(outcome: CodexNativeOutcome) -> dict[str, object]:
    return {
        "state": outcome.state,
        "native_session_id": outcome.native_session_id,
        "identity_correlated": outcome.identity_correlated,
        "exit_code": outcome.exit_code,
    }


def _outcome_from_payload(payload: object) -> CodexNativeOutcome | None:
    if not isinstance(payload, dict):
        return None
    state = payload.get("state")
    if state not in {
        "accepted",
        "failed",
        "not_created",
        "not_found",
        "outcome_unknown",
        "unsupported_surface",
    }:
        return None
    native = payload.get("native_session_id")
    exit_code = payload.get("exit_code")
    return CodexNativeOutcome(
        state,
        str(native) if isinstance(native, str) and native else None,
        bool(payload.get("identity_correlated")),
        int(exit_code) if isinstance(exit_code, int) else None,
    )


def _initial_failure(request: CodexNativeRequest) -> CodexNativeOutcome:
    return CodexNativeOutcome(
        "not_created" if request.job_kind == "launch" else "not_found"
    )


def _uncertain_failure() -> CodexNativeOutcome:
    return CodexNativeOutcome("outcome_unknown")


def _stop(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=2)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=2)


def _reap(process: subprocess.Popen[bytes]) -> None:
    threading.Thread(
        target=process.wait,
        daemon=True,
        name="yoke-codex-app-server-worker-reap",
    ).start()


def _read_outcome(
    process: subprocess.Popen[bytes], timeout: float
) -> CodexNativeOutcome | None:
    if process.stdout is None:
        return None
    selector = selectors.DefaultSelector()
    selector.register(process.stdout, selectors.EVENT_READ)
    deadline = time.monotonic() + timeout
    buffer = bytearray()
    try:
        while time.monotonic() < deadline:
            remaining = deadline - time.monotonic()
            if not selector.select(max(0.0, remaining)):
                break
            chunk = os.read(process.stdout.fileno(), _MAX_MESSAGE_BYTES + 1)
            if not chunk:
                break
            buffer.extend(chunk)
            if len(buffer) > _MAX_MESSAGE_BYTES:
                return None
            if b"\n" in buffer:
                raw = bytes(buffer.partition(b"\n")[0])
                try:
                    return _outcome_from_payload(json.loads(raw))
                except (UnicodeDecodeError, json.JSONDecodeError):
                    return None
    finally:
        selector.close()
    return None


def run_detached_operation(
    request: CodexNativeRequest,
    *,
    executable: str = sys.executable,
    process_factory: ProcessFactory = subprocess.Popen,
    timeout: float = _START_TIMEOUT_SECONDS,
) -> CodexNativeOutcome:
    """Start a child that owns app-server pipes after serve-once exits."""
    from yoke_harness.session_relay_codex_cli import _launch_environment

    command = [executable, "-m", _MODULE]
    try:
        process = process_factory(
            command,
            cwd=request.checkout,
            env=_launch_environment(request),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except OSError:
        return _initial_failure(request)
    if process.stdin is None or process.stdout is None:
        _stop(process)
        return _initial_failure(request)
    body = json.dumps(_request_payload(request), separators=(",", ":")).encode()
    if len(body) > _MAX_MESSAGE_BYTES:
        _stop(process)
        return _initial_failure(request)
    sent = False
    try:
        process.stdin.write(body + b"\n")
        process.stdin.flush()
        process.stdin.close()
        sent = True
        outcome = _read_outcome(process, timeout)
    except (OSError, subprocess.SubprocessError):
        outcome = None
    finally:
        try:
            process.stdout.close()
        except OSError:
            pass
        if process.poll() is None:
            _reap(process)
        else:
            process.wait()
    if outcome is not None:
        return outcome
    return _uncertain_failure() if sent else _initial_failure(request)


def _run_in_worker(request: CodexNativeRequest) -> CodexNativeOutcome:
    from yoke_harness.session_relay_codex_app_server import CodexAppServerTransport

    transport = CodexAppServerTransport(worker=True)
    return (
        transport.create(request)
        if request.job_kind == "launch"
        else transport.wake(request)
    )


def worker_main(*, stdin: BinaryIO | None = None, stdout: TextIO | None = None) -> int:
    source = stdin or sys.stdin.buffer
    destination = stdout or sys.stdout
    raw = source.read(_MAX_MESSAGE_BYTES + 1)
    if not raw or len(raw) > _MAX_MESSAGE_BYTES:
        return 2
    try:
        request = _request_from_payload(json.loads(raw))
        outcome = _run_in_worker(request)
    except Exception:
        outcome = CodexNativeOutcome("outcome_unknown")
    destination.write(json.dumps(_outcome_payload(outcome), separators=(",", ":")))
    destination.write("\n")
    destination.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(worker_main())


__all__ = ["run_detached_operation", "worker_main"]
