"""Detached owner process for persistent ``codex exec`` turns."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from typing import BinaryIO, Callable, Mapping, TextIO

from yoke_harness.session_relay_codex import CodexNativeOutcome, CodexNativeRequest
from yoke_harness.session_relay_codex_worker_protocol import (
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


def run_detached_operation(
    request: CodexNativeRequest,
    *,
    executable: str = sys.executable,
    process_factory: ProcessFactory = subprocess.Popen,
    timeout: float = START_TIMEOUT_SECONDS,
) -> CodexNativeOutcome:
    """Start a child that retains CLI stdout after the relay returns."""
    from yoke_harness.session_relay_codex_cli import _launch_environment

    return run_detached_json_worker(
        module=_MODULE,
        checkout=request.checkout,
        environment=_launch_environment(request),
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
    except Exception:
        outcome = CodexNativeOutcome("outcome_unknown")
    destination.write(json.dumps(outcome_payload(outcome), separators=(",", ":")))
    destination.write("\n")
    destination.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(worker_main())


__all__ = ["run_detached_operation", "worker_main"]
