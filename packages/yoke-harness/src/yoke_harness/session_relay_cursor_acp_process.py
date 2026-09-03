"""Detached owner process for relay-controlled Cursor ACP turns."""

from __future__ import annotations

import base64
import binascii
from dataclasses import replace
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import BinaryIO, Callable, Mapping, TextIO

from yoke_harness.session_launch_handoff import LAUNCH_CONTEXT_ENV
from yoke_harness.session_relay_cursor import (
    CursorCreateRequest,
    CursorNativeResult,
    CursorWakeRequest,
)
from yoke_harness.session_relay_detached_worker import (
    MAX_HANDOFF_BYTES,
    START_TIMEOUT_SECONDS,
    run_detached_json_worker,
)


_MODULE = "yoke_harness.session_relay_cursor_acp_process"
Request = CursorCreateRequest | CursorWakeRequest
ProcessFactory = Callable[..., subprocess.Popen[bytes]]


def _request_payload(request: Request) -> dict[str, object]:
    if isinstance(request, CursorCreateRequest):
        return {
            "kind": "launch",
            "checkout": str(request.checkout),
            "launch_id": request.launch_id,
            "surface_version": request.surface_version,
            "native_instruction": request.native_instruction,
            "requested_model": request.requested_model,
        }
    return {
        "kind": "wake",
        "checkout": str(request.checkout),
        "target_session_id": request.target_session_id,
        "surface_version": request.surface_version,
        "target_liveness": request.target_liveness,
        "wake_mode": request.wake_mode,
        "native_instruction": request.native_instruction,
        "requested_model": request.requested_model,
    }


def _request_from_payload(payload: object) -> Request:
    if not isinstance(payload, dict):
        raise ValueError("worker request must be an object")
    common = {
        "checkout": Path(str(payload.get("checkout") or "")),
        "surface_version": str(payload.get("surface_version") or ""),
        "native_instruction": str(payload.get("native_instruction") or ""),
    }
    if payload.get("kind") == "launch":
        return CursorCreateRequest(
            **common,
            launch_id=str(payload.get("launch_id") or ""),
            launch_attestation="",
            requested_model=(
                str(payload["requested_model"])
                if payload.get("requested_model")
                else None
            ),
        )
    if payload.get("kind") == "wake":
        return CursorWakeRequest(
            **common,
            target_session_id=str(payload.get("target_session_id") or ""),
            target_liveness=(
                str(payload["target_liveness"])
                if payload.get("target_liveness")
                else None
            ),
            wake_mode=str(payload.get("wake_mode") or ""),
            requested_model=(
                str(payload["requested_model"])
                if payload.get("requested_model")
                else None
            ),
        )
    raise ValueError("worker request kind is invalid")


def _rehydrate(request: Request, environ: Mapping[str, str]) -> Request | None:
    if not isinstance(request, CursorCreateRequest):
        return request
    try:
        context = json.loads(environ.get(LAUNCH_CONTEXT_ENV, ""))
    except (TypeError, ValueError):
        return None
    if not isinstance(context, dict) or context.get("launch_id") != request.launch_id:
        return None
    attestation = context.get("attestation")
    if not isinstance(attestation, str) or not attestation.strip():
        return None
    return replace(request, launch_attestation=attestation.strip())


def _outcome_payload(outcome: CursorNativeResult) -> dict[str, object]:
    payload: dict[str, object] = {
        "result_code": outcome.result_code,
        "native_session_id": outcome.native_session_id,
        "exit_code": outcome.exit_code,
        "duration_ms": outcome.duration_ms,
    }
    if outcome.identity_output_snippet:
        payload["identity_output_snippet"] = outcome.identity_output_snippet
    if outcome.identity_parse_expectation:
        payload["identity_parse_expectation"] = outcome.identity_parse_expectation
    if outcome.conversation_store:
        payload["conversation_store"] = outcome.conversation_store
    if outcome.native_stderr:
        # The worker owns the pipe; the parent owns the retention. Base64
        # because this hand-off is JSON and the native writes arbitrary bytes.
        payload["native_stderr_b64"] = base64.b64encode(outcome.native_stderr).decode(
            "ascii"
        )
    return payload


def _outcome_from_payload(payload: object) -> CursorNativeResult | None:
    if not isinstance(payload, dict) or not isinstance(payload.get("result_code"), str):
        return None
    native = payload.get("native_session_id")
    exit_code = payload.get("exit_code")
    duration_ms = payload.get("duration_ms")
    snippet = payload.get("identity_output_snippet")
    expectation = payload.get("identity_parse_expectation")
    store = payload.get("conversation_store")
    encoded = payload.get("native_stderr_b64")
    try:
        stderr = base64.b64decode(encoded, validate=True) if encoded else b""
    except (TypeError, ValueError, binascii.Error):
        stderr = b""
    return CursorNativeResult(
        str(payload["result_code"]),
        str(native) if isinstance(native, str) and native else None,
        int(exit_code) if isinstance(exit_code, int) else None,
        int(duration_ms) if isinstance(duration_ms, int) else None,
        identity_output_snippet=snippet if isinstance(snippet, str) else None,
        identity_parse_expectation=(
            expectation if isinstance(expectation, str) else None
        ),
        conversation_store=store if isinstance(store, str) else None,
        native_stderr=stderr,
    )


def _initial_failure(request: Request) -> CursorNativeResult:
    return CursorNativeResult(
        "not_created" if isinstance(request, CursorCreateRequest) else "not_found"
    )


def run_detached_operation(
    request: Request,
    *,
    executable: str = sys.executable,
    process_factory: ProcessFactory = subprocess.Popen,
    timeout: float = START_TIMEOUT_SECONDS,
) -> CursorNativeResult:
    from yoke_harness.session_relay_cursor_acp_requests import acp_environment

    return run_detached_json_worker(
        module=_MODULE,
        checkout=request.checkout,
        environment=acp_environment(request),
        payload=_request_payload(request),
        decode=_outcome_from_payload,
        initial_failure=_initial_failure(request),
        uncertain_failure=CursorNativeResult("outcome_unknown"),
        executable=executable,
        process_factory=process_factory,
        timeout=timeout,
    )


def _run_in_worker(request: Request) -> CursorNativeResult:
    from yoke_harness.session_relay_cursor_acp import CursorAcpTransport

    transport = CursorAcpTransport(worker=True)
    return (
        transport.new_session(request)
        if isinstance(request, CursorCreateRequest)
        else transport.prompt_session(request)
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
        request = _request_from_payload(json.loads(raw))
        hydrated = _rehydrate(request, os.environ if environ is None else environ)
        outcome = (
            _initial_failure(request) if hydrated is None else _run_in_worker(hydrated)
        )
    except Exception:
        outcome = CursorNativeResult("outcome_unknown")
    destination.write(json.dumps(_outcome_payload(outcome), separators=(",", ":")))
    destination.write("\n")
    destination.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(worker_main())


__all__ = ["run_detached_operation", "worker_main"]
