"""Durable, body-free delivery for relay launch reports."""

from __future__ import annotations

from dataclasses import replace
from hashlib import sha256
import json
from pathlib import Path
from typing import Any, Callable, Mapping

from yoke_contracts.api.function_call import TargetRef
from yoke_contracts.session_control.capabilities import native_create_timeout_seconds
from yoke_contracts.session_control.evidence import redacted_evidence_document
from yoke_contracts.session_control.launch_registration import (
    IDENTITY_REGISTRATION_WAIT_CODE,
    NATIVE_LAUNCH_WORKSPACE_FIELD,
)
from yoke_harness.session_relay_schedule import relay_state_dir
from yoke_harness.session_relay_runtime import RelayAdapterResult


PENDING_REPORT_DIR_NAME = "pending-reports"
REPORT_RETRY_SECONDS = 1

# How long one report dispatch may take. Every relay report is a small
# control-plane write, so the same bound covers them all.
RELAY_REPORT_TIMEOUT_SECONDS = 10


Dispatcher = Callable[..., Any]


def _directory(state_dir: Path | None) -> Path:
    directory = (state_dir or relay_state_dir()) / PENDING_REPORT_DIR_NAME
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    directory.chmod(0o700)
    return directory


def _report_path(payload: Mapping[str, object], state_dir: Path | None) -> Path:
    identity = "\0".join(
        str(payload.get(name) or "")
        for name in ("relay_id", "job_kind", "job_id", "lease_id")
    )
    return _directory(state_dir) / f"{sha256(identity.encode()).hexdigest()}.json"


def _safe_payload(value: object) -> dict[str, object] | None:
    if not isinstance(value, Mapping):
        return None
    required = ("relay_id", "job_kind", "job_id", "lease_id", "result")
    if any(
        not isinstance(value.get(name), str) or not value.get(name) for name in required
    ):
        return None
    if value["job_kind"] not in {"launch", "wake", "terminate"}:
        return None
    payload: dict[str, object] = {name: value[name] for name in required}
    for name in ("native_id", "adapter_revision"):
        item = value.get(name)
        payload[name] = str(item)[:128] if isinstance(item, str) and item else None
    evidence = value.get("evidence")
    payload["evidence"] = redacted_evidence_document(
        evidence if isinstance(evidence, Mapping) else None
    )
    return payload


def _write_pending(payload: Mapping[str, object], state_dir: Path | None) -> Path:
    path = _report_path(payload, state_dir)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(payload, separators=(",", ":"), sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.chmod(0o600)
    temporary.replace(path)
    return path


def _dispatch(
    dispatcher: Dispatcher,
    function_id: str,
    payload: Mapping[str, object],
    *,
    timeout_s: int,
) -> Any:
    return dispatcher(
        function_id=function_id,
        target=TargetRef(kind="global"),
        payload=dict(payload),
        timeout_s=timeout_s,
    )


def deliver_terminal_report(
    dispatcher: Dispatcher,
    function_id: str,
    payload: Mapping[str, object],
    *,
    state_dir: Path | None,
    timeout_s: int,
) -> Any:
    """Persist a sanitized report before its first delivery attempt."""
    safe = _safe_payload(payload)
    if safe is None:
        raise ValueError("relay report payload is invalid")
    if safe["job_kind"] == "wake":
        return _dispatch(dispatcher, function_id, safe, timeout_s=timeout_s)
    pending = _write_pending(safe, state_dir)
    try:
        response = _dispatch(dispatcher, function_id, safe, timeout_s=timeout_s)
    except Exception as exc:
        return exc
    if getattr(response, "success", False):
        pending.unlink(missing_ok=True)
    return response


def report_launch_progress(
    dispatcher: Dispatcher,
    function_id: str,
    payload: Mapping[str, object],
    *,
    timeout_s: int,
) -> bool:
    """Best-effort one-way evidence update; it never completes the attempt."""
    safe = _safe_payload({**payload, "result": "progress"})
    if safe is None:
        return False
    try:
        response = _dispatch(dispatcher, function_id, safe, timeout_s=timeout_s)
    except Exception:
        return False
    return bool(getattr(response, "success", False))


def _launch_registration(
    dispatcher: Dispatcher,
    function_id: str,
    payload: Mapping[str, object],
    *,
    timeout_s: int,
) -> dict[str, object] | None:
    safe = _safe_payload({**payload, "result": "progress"})
    if safe is None:
        return None
    try:
        response = _dispatch(dispatcher, function_id, safe, timeout_s=timeout_s)
    except Exception:
        return None
    if not getattr(response, "success", False):
        return None
    envelope = getattr(response, "result", None)
    if not isinstance(envelope, Mapping):
        return None
    result = envelope.get("result", envelope)
    if not isinstance(result, Mapping):
        return None
    registration = result.get("registration")
    return dict(registration) if isinstance(registration, Mapping) else None


def attach_launch_progress_reporter(
    dispatcher: Dispatcher,
    function_id: str,
    relay_id: str,
    job: Mapping[str, object],
    *,
    timeout_s: int,
) -> Mapping[str, object]:
    """Give a local launch adapter a body-free progress callback."""
    if job.get("job_kind") != "launch":
        return job
    runnable = dict(job)

    def report(evidence: Mapping[str, object]) -> bool:
        progress = RelayAdapterResult("progress", evidence=dict(evidence))
        return report_launch_progress(
            dispatcher,
            function_id,
            _launch_payload(relay_id, job, progress),
            timeout_s=timeout_s,
        )

    runnable["_launch_progress_reporter"] = report

    def resolve_registration(workspace: str) -> dict[str, object] | None:
        bound = native_create_timeout_seconds(str(job.get("surface") or ""))
        progress = RelayAdapterResult(
            "progress",
            evidence={
                "result_code": IDENTITY_REGISTRATION_WAIT_CODE,
                NATIVE_LAUNCH_WORKSPACE_FIELD: workspace,
                "native_launch_bound_seconds": int(bound or 0),
                "surface": str(job.get("surface") or ""),
            },
        )
        return _launch_registration(
            dispatcher,
            function_id,
            _launch_payload(relay_id, job, progress),
            timeout_s=timeout_s,
        )

    runnable["_launch_registration_resolver"] = resolve_registration
    return runnable


def _launch_payload(
    relay_id: str,
    job: Mapping[str, object],
    result: RelayAdapterResult,
) -> dict[str, object]:
    return {
        "relay_id": relay_id,
        "job_kind": "launch",
        "job_id": str(job.get("job_id") or ""),
        "lease_id": str(job.get("lease_id") or ""),
        "result": result.result_code,
        "native_id": result.native_session_id,
        "adapter_revision": result.adapter_revision,
        "evidence": result.evidence,
    }


def checkpoint_launch_start(
    dispatcher: Dispatcher,
    function_id: str,
    relay_id: str,
    job: Mapping[str, object],
    *,
    timeout_s: int,
) -> Mapping[str, object]:
    if job.get("job_kind") != "launch":
        return job
    started = RelayAdapterResult(
        "progress",
        evidence={
            "surface": str(job.get("surface") or ""),
            "result_code": "adapter_started",
            "native_launch_phase": "adapter_start",
        },
    )
    report_launch_progress(
        dispatcher,
        function_id,
        _launch_payload(relay_id, job, started),
        timeout_s=timeout_s,
    )
    return attach_launch_progress_reporter(
        dispatcher, function_id, relay_id, job, timeout_s=timeout_s
    )


def checkpoint_launch_result(
    dispatcher: Dispatcher,
    function_id: str,
    relay_id: str,
    job: Mapping[str, object],
    result: RelayAdapterResult,
    *,
    timeout_s: int,
) -> RelayAdapterResult:
    if job.get("job_kind") != "launch":
        return result
    evidence = dict(result.evidence)
    evidence.setdefault(
        "native_launch_phase",
        "native_running"
        if result.result_code == "native_created"
        else "adapter_complete",
    )
    prepared = replace(result, evidence=evidence)
    report_launch_progress(
        dispatcher,
        function_id,
        _launch_payload(relay_id, job, prepared),
        timeout_s=timeout_s,
    )
    return prepared


def diagnostic_outcome_fields(
    relay_id: str,
    machine_id: str,
    result: RelayAdapterResult,
) -> dict[str, object]:
    evidence = redacted_evidence_document(result.evidence)
    reference = evidence.get("native_diagnostic_ref")
    failure_class = evidence.get("native_error_class")
    availability = evidence.get("diagnostic_availability")
    if not any((reference, failure_class, availability)):
        return {}
    return {
        "relay_id": relay_id,
        "machine_id": machine_id,
        "native_diagnostic_ref": reference if isinstance(reference, str) else None,
        "native_diagnostic_command": evidence.get("native_diagnostic_command"),
        "diagnostic_expires_at": evidence.get("diagnostic_expires_at"),
        "diagnostic_availability": availability,
        "native_error_class": failure_class,
        "native_error_step": evidence.get("native_error_step"),
    }


def retry_pending_reports(
    dispatcher: Dispatcher,
    function_id: str,
    *,
    state_dir: Path | None,
    timeout_s: int,
) -> bool:
    """Drain reports left by a prior transport failure or process exit."""
    directory = _directory(state_dir)
    all_delivered = True
    for path in sorted(directory.glob("*.json")):
        try:
            safe = _safe_payload(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            safe = None
        if safe is None:
            path.unlink(missing_ok=True)
            continue
        try:
            response = _dispatch(dispatcher, function_id, safe, timeout_s=timeout_s)
        except Exception:
            all_delivered = False
            continue
        if getattr(response, "success", False):
            path.unlink(missing_ok=True)
        else:
            all_delivered = False
    return all_delivered


__all__ = [
    "RELAY_REPORT_TIMEOUT_SECONDS",
    "PENDING_REPORT_DIR_NAME",
    "REPORT_RETRY_SECONDS",
    "attach_launch_progress_reporter",
    "checkpoint_launch_result",
    "checkpoint_launch_start",
    "deliver_terminal_report",
    "diagnostic_outcome_fields",
    "report_launch_progress",
    "retry_pending_reports",
]
