"""Registered control-plane operations used by the local deploy driver."""

from __future__ import annotations

import os
import sys
from typing import Any, Dict, List, Optional

from yoke_contracts.api.function_call import TargetRef
from yoke_core.api.service_client_structured_api_adapter import call_dispatcher
from yoke_core.domain.control_plane_function_degradation import REGISTRY_SKEW_CODES
from yoke_core.domain.deployment_run_driver_attachment import (
    ATTACH_FUNCTION_ID,
    RELEASE_FUNCTION_ID,
)
from yoke_core.domain.session_liveness_pump import (
    HEARTBEAT_INTERVAL_SECONDS,
    SessionLivenessPump,
)


class DeploymentControlPlaneError(RuntimeError):
    """A required serving control-plane operation was refused."""


def _call(function_id: str, run_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    response = call_dispatcher(
        function_id=function_id,
        target=TargetRef(kind="workflow_run", workflow_run_id=run_id),
        payload=payload,
    )
    if not response.success:
        message = response.error.message if response.error else "request failed"
        raise DeploymentControlPlaneError(f"{function_id} failed: {message}")
    return dict(response.result or {})


def execution_context(run_id: str) -> Dict[str, Any]:
    """Return the locked run, member, and immutable stage projection."""
    return _call("deployment_runs.execution.context", run_id, {})


def run_pin(run_id: str) -> Dict[str, str]:
    """Return the run's project and pin without composing membership.

    Self-deploy driver freeze needs the lineage and project to take a
    worktree. Asking :func:`execution_context` for those two fields also
    enrolls every delivery-ready item and derives carried work, which is
    minutes of git before the child exists. The pin itself is already on
    the run row.
    """
    result = _call("deployment_runs.get", run_id, {})
    run = result.get("run") or {}
    if not isinstance(run, dict):
        run = {}
    return {
        "project": str(run.get("project") or ""),
        "release_lineage": str(run.get("release_lineage") or ""),
    }


def update_run_field(run_id: str, field: str, value: str) -> None:
    """Write one execution-owned run field through serving authority."""
    result = _call(
        "deployment_runs.execution.update",
        run_id,
        {"field": field, "value": value},
    )
    if not result.get("updated"):
        raise DeploymentControlPlaneError(
            f"deployment_runs.execution.update did not verify {field}={value}"
        )


def seed_qa(run_id: str) -> int:
    """Idempotently seed the run's flow-derived QA checks."""
    return int(
        _call("deployment_runs.execution.qa_seed", run_id, {}).get("seeded") or 0
    )


def record_qa_stage(
    run_id: str,
    stage: str,
    verdict: str,
    *,
    raw_result: str = "{}",
    duration_ms: Optional[str] = None,
    workflow_run: Optional[str] = None,
) -> Optional[str]:
    """Record one stage verdict on the run's serving control plane."""
    payload: Dict[str, Any] = {
        "stage": stage,
        "verdict": verdict,
        "raw_result": raw_result,
    }
    if duration_ms is not None:
        payload["duration_ms"] = duration_ms
    if workflow_run is not None:
        payload["workflow_run"] = workflow_run
    result = _call("deployment_runs.execution.qa_record", run_id, payload)
    value = result.get("qa_run_id")
    return str(value) if value is not None else None


def record_qa_pass(run_id: str, stage: str, qa_result: str) -> None:
    """Record a passing stage verdict; warn rather than crash a done stage."""
    try:
        record_qa_stage(run_id, stage, "pass", raw_result=qa_result)
    except DeploymentControlPlaneError as exc:
        print(
            f"  Warning: could not record QA verdict for stage '{stage}': {exc}",
            file=sys.stderr,
        )


def unresolved_qa(run_id: str) -> List[str]:
    """Return every blocking QA obligation that still prevents completion."""
    values = _call("deployment_runs.execution.qa_pending", run_id, {}).get("unresolved")
    return [str(value) for value in values] if isinstance(values, list) else []


def ephemeral_qa_ready(run_id: str) -> bool:
    """Return whether every run member already has passing browser QA."""
    return bool(
        _call("deployment_runs.execution.ephemeral_qa_ready", run_id, {}).get("ready")
    )


def allocate_stage_receipt(
    run_id: str,
    *,
    stage_name: str,
    correlation_id: str,
    target_kind: str,
    executor: str,
) -> Dict[str, Any]:
    """Allocate a durable per-stage receipt attempt before executor dispatch."""
    return _call(
        "deployment_runs.execution.stage_receipt_allocate",
        run_id,
        {
            "stage_name": stage_name,
            "correlation_id": correlation_id,
            "target_kind": target_kind,
            "executor": executor,
        },
    )


def complete_stage_receipt(
    run_id: str,
    *,
    receipt_id: int,
    correlation_id: str,
    status: str,
    target_name: Optional[str] = None,
    observed_url: Optional[str] = None,
    observed_release_lineage: Optional[str] = None,
    observed_artifact_identity: Optional[str] = None,
    executor_receipt: Optional[str] = None,
    failure_reason: Optional[str] = None,
) -> Dict[str, Any]:
    """Settle one allocated attempt with observed evidence or a failure reason."""
    payload: Dict[str, Any] = {
        "receipt_id": receipt_id,
        "correlation_id": correlation_id,
        "status": status,
    }
    for key, value in (
        ("target_name", target_name),
        ("observed_url", observed_url),
        ("observed_release_lineage", observed_release_lineage),
        ("observed_artifact_identity", observed_artifact_identity),
        ("executor_receipt", executor_receipt),
        ("failure_reason", failure_reason),
    ):
        if value is not None:
            payload[key] = value
    return _call("deployment_runs.execution.stage_receipt_complete", run_id, payload)


def latest_stage_receipt(run_id: str, *, stage_name: str) -> Optional[Dict[str, Any]]:
    """Return the newest receipt attempt for a stage, or ``None`` if absent."""
    result = _call(
        "deployment_runs.execution.stage_receipt_latest",
        run_id,
        {"stage_name": stage_name},
    )
    receipt = result.get("receipt")
    return dict(receipt) if isinstance(receipt, dict) else None


def project_field(project: str, field: str) -> str:
    """Read one project field through the selected transport."""
    response = call_dispatcher(
        function_id="projects.get",
        target=TargetRef(kind="global"),
        payload={"project": project, "field": field},
    )
    if not response.success:
        message = response.error.message if response.error else "request failed"
        raise DeploymentControlPlaneError(f"projects.get failed: {message}")
    value = (response.result or {}).get("value")
    return "" if value is None else str(value)


def attach_driver(
    run_id: str, *, phase: str, progress_capture: str = ""
) -> Dict[str, Any]:
    """Record this process as the run's driver, or refuse a live other one.

    A registry-skew answer means this client is ahead of the plane; the
    caller proceeds without recording, matching an unconverged column.
    """
    response = call_dispatcher(
        function_id=ATTACH_FUNCTION_ID,
        target=TargetRef(kind="workflow_run", workflow_run_id=run_id),
        payload={
            "phase": phase,
            "pid": os.getpid(),
            "progress_capture": progress_capture,
        },
    )
    if response.success:
        return dict(response.result or {})
    code = response.error.code if response.error else ""
    if code in REGISTRY_SKEW_CODES:
        return {}
    message = response.error.message if response.error else "request failed"
    raise DeploymentControlPlaneError(f"{ATTACH_FUNCTION_ID} failed: {message}")


def release_driver(run_id: str) -> None:
    """Drop this process's driver attachment; a miss is not a pipeline failure."""
    try:
        _call(RELEASE_FUNCTION_ID, run_id, {"pid": os.getpid()})
    except DeploymentControlPlaneError as exc:
        print(f"warning: could not release deploy driver: {exc}", file=sys.stderr)


class DriverLivenessPump(SessionLivenessPump):
    """Refresh the run's driver attachment for as long as this process is."""

    def __init__(
        self,
        run_id: str,
        *,
        phase: str,
        progress_capture: str = "",
        interval_seconds: float = HEARTBEAT_INTERVAL_SECONDS,
    ) -> None:
        super().__init__(interval_seconds=interval_seconds)
        self._run_id = run_id
        self._phase = phase
        self._progress_capture = progress_capture

    def tick(self) -> bool:
        now = self._clock()
        due = now - self._last_refresh >= self._interval
        refreshed = super().tick()
        if due:
            try:
                attach_driver(
                    self._run_id,
                    phase=self._phase,
                    progress_capture=self._progress_capture,
                )
            except DeploymentControlPlaneError:
                pass
        return refreshed


__all__ = [
    "DeploymentControlPlaneError",
    "DriverLivenessPump",
    "allocate_stage_receipt",
    "attach_driver",
    "complete_stage_receipt",
    "execution_context",
    "ephemeral_qa_ready",
    "latest_stage_receipt",
    "project_field",
    "record_qa_stage",
    "release_driver",
    "run_pin",
    "seed_qa",
    "unresolved_qa",
    "update_run_field",
]
