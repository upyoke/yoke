"""Internal server-side deployment reads for the done-transition engine.

The done-transition deployment guards and the final done-preconditions
bundle read the control plane (``deployment_flows``, ``deployment_runs`` /
``deployment_run_items``, ``deployment_run_qa``, plus the item scalar and
``shepherd_verdicts`` reads inside the preconditions bundle) by opening a
local ``connect()``, which fails over an https control plane. These
handlers relay those reads server-side while the engine keeps every guard
verdict and operator narrative client-side.

Each handler is a thin wrapper over the unchanged query the engine ran
inline (or, for the preconditions bundle, over the unchanged
:func:`yoke_core.engines.done_transition_preconditions.evaluate_done_preconditions`
connection-based core). They are ``adapter_status='internal'`` (engine
glue, never an agent CLI surface), so they carry no CLI adapter row.
"""

from __future__ import annotations

from typing import Any, List, Optional

from pydantic import BaseModel, Field

from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionError,
    HandlerOutcome,
)


class RegisteredFlowIdsRequest(BaseModel):
    pass


class RegisteredFlowIdsResponse(BaseModel):
    flow_ids: List[str] = Field(default_factory=list)


class LatestDeploymentRunRequest(BaseModel):
    pass


class LatestDeploymentRunResponse(BaseModel):
    run_id: str
    status: str


class RunStageRequest(BaseModel):
    run_id: str = Field(..., min_length=1)


class RunStageResponse(BaseModel):
    current_stage: str


class RunBlockingQaRequest(BaseModel):
    run_id: str = Field(..., min_length=1)


class RunBlockingQaResponse(BaseModel):
    blocking: List[str] = Field(default_factory=list)


class DonePreconditionsRequest(BaseModel):
    deploy_flow: str = ""
    require_plan_verdict: bool = False


class DonePreconditionsResponse(BaseModel):
    allowed: bool
    reason: Optional[str] = None


def _err(code: str, message: str) -> HandlerOutcome:
    return HandlerOutcome(
        primary_success=False,
        error=FunctionError(code=code, message=message),
    )


def _connect_rw() -> Any:
    from yoke_core.domain import db_helpers

    return db_helpers.connect()


def _placeholder(conn: Any) -> str:
    from yoke_core.domain import db_backend

    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _require_item_id(request: FunctionCallRequest) -> Optional[int]:
    if request.target.item_id is None:
        return None
    return int(request.target.item_id)


def handle_registered_flow_ids(request: FunctionCallRequest) -> HandlerOutcome:
    """Return every registered ``deployment_flows.id`` (sorted).

    Wraps :func:`yoke_core.domain.deployment_flow_validator.list_registered_flow_ids`
    unchanged; the engine owns the "not a registered flow" narrative and the
    registered-alternatives suffix.
    """
    from yoke_core.domain.deployment_flow_validator import (
        list_registered_flow_ids,
    )

    try:
        with _connect_rw() as conn:
            flow_ids = list_registered_flow_ids(conn)
    except Exception as exc:  # noqa: BLE001 - surfaced so the guard aborts
        return _err("registered_flow_ids_failed", str(exc))

    return HandlerOutcome(
        result_payload={"flow_ids": list(flow_ids)},
        primary_success=True,
    )


def handle_latest_deployment_run(request: FunctionCallRequest) -> HandlerOutcome:
    """Return the item's latest deployment run id + status (empty when none).

    Runs the engine's exact ``deployment_runs`` JOIN ``deployment_run_items``
    ordered by ``created_at DESC LIMIT 1`` read. Serves both the
    ``_check_deployment_evidence`` (succeeded?) and ``_get_latest_run_status``
    ((status, id)) engine helpers from one read; both derive their verdict
    client-side.
    """
    item_id = _require_item_id(request)
    if item_id is None:
        return _err("target_invalid", "latest_deployment_run requires target.item_id")

    try:
        with _connect_rw() as conn:
            marker = _placeholder(conn)
            row = conn.execute(
                "SELECT dr.id, dr.status FROM deployment_runs dr "
                "JOIN deployment_run_items dri ON dr.id = dri.run_id "
                f"WHERE dri.item_id = {marker} "
                "ORDER BY dr.created_at DESC LIMIT 1",
                (item_id,),
            ).fetchone()
    except Exception as exc:  # noqa: BLE001 - surfaced so the guard aborts
        return _err("latest_deployment_run_failed", str(exc))

    if not row:
        return HandlerOutcome(
            result_payload={"run_id": "", "status": ""},
            primary_success=True,
        )
    run_id = row["id"] if hasattr(row, "keys") else row[0]
    status = row["status"] if hasattr(row, "keys") else row[1]
    return HandlerOutcome(
        result_payload={"run_id": str(run_id or ""), "status": str(status or "")},
        primary_success=True,
    )


def handle_run_stage(request: FunctionCallRequest) -> HandlerOutcome:
    """Return a deployment run's ``current_stage`` (empty when null/missing).

    The engine treats a ``-failed`` suffix as a contradictory succeeded/failed
    state; the suffix check + narrative stay engine-owned.
    """
    try:
        body = RunStageRequest.model_validate(request.payload)
    except Exception as exc:  # noqa: BLE001 - surface a structured payload error
        return _err("payload_invalid", f"run_stage payload invalid: {exc}")

    try:
        with _connect_rw() as conn:
            marker = _placeholder(conn)
            row = conn.execute(
                "SELECT COALESCE(current_stage, '') FROM deployment_runs "
                f"WHERE id = {marker}",
                (body.run_id,),
            ).fetchone()
    except Exception as exc:  # noqa: BLE001 - surfaced so the guard aborts
        return _err("run_stage_failed", str(exc))

    current_stage = "" if row is None else str(row[0] or "")
    return HandlerOutcome(
        result_payload={"current_stage": current_stage},
        primary_success=True,
    )


def handle_run_blocking_qa(request: FunctionCallRequest) -> HandlerOutcome:
    """Return a run's unsatisfied blocking QA descriptions.

    Runs the engine's exact ``deployment_run_qa`` read (blocking, not passed,
    not waived) and returns each ``check_name (status)`` string; the engine
    prints them and blocks when the list is non-empty.
    """
    try:
        body = RunBlockingQaRequest.model_validate(request.payload)
    except Exception as exc:  # noqa: BLE001 - surface a structured payload error
        return _err("payload_invalid", f"run_blocking_qa payload invalid: {exc}")

    try:
        with _connect_rw() as conn:
            marker = _placeholder(conn)
            rows = conn.execute(
                "SELECT check_name || ' (' || status || ')' "
                "FROM deployment_run_qa "
                f"WHERE run_id = {marker} AND blocking = 1 "
                "AND status <> 'passed' AND status <> 'waived'",
                (body.run_id,),
            ).fetchall()
    except Exception as exc:  # noqa: BLE001 - surfaced so the guard aborts
        return _err("run_blocking_qa_failed", str(exc))

    return HandlerOutcome(
        result_payload={"blocking": [str(r[0]) for r in rows]},
        primary_success=True,
    )


def handle_done_preconditions(request: FunctionCallRequest) -> HandlerOutcome:
    """Evaluate the four done-preconditions and return ``(allowed, reason)``.

    Wraps the unchanged connection-based
    :func:`yoke_core.engines.done_transition_preconditions.evaluate_done_preconditions`
    bundle (registered-flow, deployed_to, deploy_stage, latest-run-not-failed,
    and the planning verdict checks). The exact rejection-reason strings are
    preserved; the guard banner stays engine-owned.
    """
    item_id = _require_item_id(request)
    if item_id is None:
        return _err("target_invalid", "done_preconditions requires target.item_id")
    try:
        body = DonePreconditionsRequest.model_validate(request.payload or {})
    except Exception as exc:  # noqa: BLE001 - surface a structured payload error
        return _err("payload_invalid", f"done_preconditions payload invalid: {exc}")

    from yoke_core.engines.done_transition_preconditions import (
        evaluate_done_preconditions,
    )

    try:
        with _connect_rw() as conn:
            allowed, reason = evaluate_done_preconditions(
                conn, item_id, body.deploy_flow, body.require_plan_verdict
            )
    except Exception as exc:  # noqa: BLE001 - surfaced so the guard aborts
        return _err("done_preconditions_failed", str(exc))

    return HandlerOutcome(
        result_payload={"allowed": bool(allowed), "reason": reason},
        primary_success=True,
    )


__all__ = [
    "DonePreconditionsRequest",
    "DonePreconditionsResponse",
    "LatestDeploymentRunRequest",
    "LatestDeploymentRunResponse",
    "RegisteredFlowIdsRequest",
    "RegisteredFlowIdsResponse",
    "RunBlockingQaRequest",
    "RunBlockingQaResponse",
    "RunStageRequest",
    "RunStageResponse",
    "handle_done_preconditions",
    "handle_latest_deployment_run",
    "handle_registered_flow_ids",
    "handle_run_blocking_qa",
    "handle_run_stage",
]
