"""Detached owner process for persistent ``codex exec`` turns."""

from __future__ import annotations

from yoke_harness.session_launch_admission import NativeCapacityRefusal

import json
import os
import subprocess
import sys
import threading
from typing import BinaryIO, Callable, Mapping, TextIO

from yoke_harness.session_relay_native_streams import BoundedStreams, STDOUT, drain
from yoke_harness.session_relay_native_diagnostics import (
    NativeDiagnosticError,
    diagnostic_reference,
    store_native_diagnostic,
)
from yoke_harness.session_relay_codex import CodexNativeOutcome, CodexNativeRequest
from yoke_harness.session_relay_codex_worker_protocol import (
    capacity_refusal_outcome,
    initial_failure,
    outcome_from_payload,
    outcome_payload,
    rehydrate_launch_attestation,
    request_from_payload,
    request_payload,
)
from yoke_harness.session_relay_detached_worker import (
    MAX_HANDOFF_BYTES,
    START_TIMEOUT_SECONDS,
    run_detached_json_worker,
)


_MODULE = "yoke_harness.session_relay_codex_cli_process"
ProcessFactory = Callable[..., subprocess.Popen[bytes]]


def _retain_and_reap(
    process: subprocess.Popen[bytes],
    streams: BoundedStreams,
    reference: str,
) -> None:
    """Own the native for the rest of its turn and keep what it said.

    This worker outlives the relay poll that started it, so it is the only
    process that can see how the native ends. Reading the streams to their end
    and writing them once, with the exit status, is what turns a codex turn
    that died into something an operator can still read.
    """

    def own() -> None:
        drain(process.stdout, streams, STDOUT)
        try:
            exit_code = process.wait()
        except (OSError, subprocess.SubprocessError):
            exit_code = None
        _retain(streams, reference, exit_code)

    threading.Thread(target=own, daemon=False, name="yoke-codex-relay-reap").start()


def _retain(
    streams: BoundedStreams,
    reference: str,
    exit_code: int | None,
) -> None:
    """Write one codex native's account, or leave the outcome unaffected."""
    stdout, stderr = streams.snapshot()
    try:
        store_native_diagnostic(
            stdout,
            stderr,
            reference=diagnostic_reference(reference),
            exit_code=exit_code,
        )
    except NativeDiagnosticError:
        return


def stop_native(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=2)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=2)


def run_detached_operation(
    request: CodexNativeRequest,
    *,
    executable: str = sys.executable,
    process_factory: ProcessFactory = subprocess.Popen,
    timeout: float = START_TIMEOUT_SECONDS,
) -> CodexNativeOutcome:
    """Start a child that retains CLI stdout after the relay returns."""
    from yoke_harness.session_relay_codex_invocation import (
        codex_launch_environment,
    )

    return run_detached_json_worker(
        module=_MODULE,
        checkout=request.checkout,
        environment=codex_launch_environment(request),
        payload=request_payload(request),
        decode=outcome_from_payload,
        initial_failure=initial_failure(request),
        uncertain_failure=CodexNativeOutcome("outcome_unknown"),
        executable=executable,
        process_factory=process_factory,
        timeout=timeout,
    )


def _run_in_worker(request: CodexNativeRequest) -> CodexNativeOutcome:
    from yoke_harness.session_relay_codex_cli import CodexCliTransport

    transport = CodexCliTransport(worker=True)
    return (
        transport.create(request)
        if request.job_kind == "launch"
        else transport.wake(request)
    )


def worker_main(
    *,
    stdin: BinaryIO | None = None,
    stdout: TextIO | None = None,
    environ: Mapping[str, str] | None = None,
) -> int:
    source = stdin or sys.stdin.buffer
    destination = stdout or sys.stdout
    raw = source.read(MAX_HANDOFF_BYTES + 1)
    if not raw or len(raw) > MAX_HANDOFF_BYTES:
        return 2
    try:
        request = request_from_payload(json.loads(raw))
        hydrated = rehydrate_launch_attestation(
            request,
            os.environ if environ is None else environ,
        )
        outcome = (
            initial_failure(request) if hydrated is None else _run_in_worker(hydrated)
        )
    except NativeCapacityRefusal as refusal:
        outcome = capacity_refusal_outcome(request, refusal)
    except Exception:
        outcome = CodexNativeOutcome("outcome_unknown")
    destination.write(json.dumps(outcome_payload(outcome), separators=(",", ":")))
    destination.write("\n")
    destination.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(worker_main())


__all__ = ["run_detached_operation", "worker_main"]
