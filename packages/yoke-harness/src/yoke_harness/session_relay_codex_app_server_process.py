"""Detached owner process for Codex app-server turns."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from typing import BinaryIO, Callable, Mapping, TextIO

from yoke_harness.session_relay_codex import CodexNativeOutcome, CodexNativeRequest
from yoke_harness.session_relay_detached_worker import (
    MAX_HANDOFF_BYTES,
    START_TIMEOUT_SECONDS,
    run_detached_json_worker,
)
from yoke_harness.session_relay_codex_worker_protocol import (
    initial_failure as _initial_failure,
    outcome_from_payload as _outcome_from_payload,
    outcome_payload as _outcome_payload,
    rehydrate_launch_attestation as _rehydrate_launch_attestation,
    request_from_payload as _request_from_payload,
    request_payload as _request_payload,
)


_MODULE = "yoke_harness.session_relay_codex_app_server_process"
_MAX_MESSAGE_BYTES = MAX_HANDOFF_BYTES
_START_TIMEOUT_SECONDS = START_TIMEOUT_SECONDS

ProcessFactory = Callable[..., subprocess.Popen[bytes]]


def _uncertain_failure() -> CodexNativeOutcome:
    return CodexNativeOutcome("outcome_unknown")


def run_detached_operation(
    request: CodexNativeRequest,
    *,
    executable: str = sys.executable,
    process_factory: ProcessFactory = subprocess.Popen,
    timeout: float = _START_TIMEOUT_SECONDS,
) -> CodexNativeOutcome:
    """Start a child that owns app-server pipes after serve-once exits."""
    from yoke_harness.session_relay_codex_cli import _launch_environment

    return run_detached_json_worker(
        module=_MODULE,
        checkout=request.checkout,
        environment=_launch_environment(request),
        payload=_request_payload(request),
        decode=_outcome_from_payload,
        initial_failure=_initial_failure(request),
        uncertain_failure=_uncertain_failure(),
        executable=executable,
        process_factory=process_factory,
        timeout=timeout,
    )


def _run_in_worker(request: CodexNativeRequest) -> CodexNativeOutcome:
    from yoke_harness.session_relay_codex_app_server import CodexAppServerTransport

    transport = CodexAppServerTransport(worker=True)
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
    raw = source.read(_MAX_MESSAGE_BYTES + 1)
    if not raw or len(raw) > _MAX_MESSAGE_BYTES:
        return 2
    try:
        request = _request_from_payload(json.loads(raw))
        hydrated = _rehydrate_launch_attestation(
            request,
            os.environ if environ is None else environ,
        )
        outcome = (
            _initial_failure(request) if hydrated is None else _run_in_worker(hydrated)
        )
    except Exception:
        outcome = CodexNativeOutcome("outcome_unknown")
    destination.write(json.dumps(_outcome_payload(outcome), separators=(",", ":")))
    destination.write("\n")
    destination.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(worker_main())


__all__ = ["run_detached_operation", "worker_main"]
