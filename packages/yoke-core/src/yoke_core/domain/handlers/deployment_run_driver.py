"""Attach, release, and look up the process driving a deployment run."""

from typing import Any, Optional

from pydantic import BaseModel

from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionError,
    HandlerOutcome,
)
from yoke_core.domain.deployment_run_driver_attachment import (
    ATTACH_FUNCTION_ID,
    DRIVER_ALREADY_ATTACHED_CODE,
    FOR_CAPTURE_FUNCTION_ID,
    RELEASE_FUNCTION_ID,
    ROW_LOCK_BUSY_CODE,
    DriverAlreadyAttached,
    VALID_PHASES,
    attach_driver,
    live_attachment_for_capture,
    release_driver,
)
from yoke_core.domain.deployment_runs_lock import DeploymentRunRowLockBusy
from yoke_core.domain.handlers import deployment_run_execution as execution
from yoke_core.domain.handlers.deployment_common import error, require_global, run_id


class AttachDriverRequest(BaseModel):
    phase: str
    pid: int
    progress_capture: str = ""
    machine_id: str = ""
    exited_driver_pid: int = 0


class AttachDriverResponse(BaseModel):
    run_id: str
    recorded: bool
    driver: dict[str, Any] = {}


class ReleaseDriverRequest(BaseModel):
    pid: int


class ReleaseDriverResponse(BaseModel):
    run_id: str
    released: bool


class DriverForCaptureRequest(BaseModel):
    progress_capture: str


class DriverForCaptureResponse(BaseModel):
    driver: Optional[dict[str, Any]] = None


def _int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _already_attached(exc: DriverAlreadyAttached) -> HandlerOutcome:
    return HandlerOutcome(
        primary_success=False,
        result_payload={"run_id": exc.run_id, "driver": exc.current.as_dict()},
        error=FunctionError(code=DRIVER_ALREADY_ATTACHED_CODE, message=str(exc)),
    )


def handle_attach_driver(request: FunctionCallRequest) -> HandlerOutcome:
    resolved = run_id(request, ATTACH_FUNCTION_ID)
    if isinstance(resolved, HandlerOutcome):
        return resolved
    payload = request.payload or {}
    phase = str(payload.get("phase") or "").strip()
    pid = _int(payload.get("pid"))
    if phase not in VALID_PHASES or pid <= 0:
        return error("payload_invalid", "phase and pid are required")
    session_id = str(request.actor.session_id or "").strip()
    if not session_id:
        return error("unauthenticated", "a session is required to attach a driver")
    if refusal := execution._require_execution_lock(request, resolved):
        return refusal
    from yoke_core.domain.db_helpers import connect

    with connect() as conn:
        try:
            recorded = attach_driver(
                conn,
                resolved,
                session_id=session_id,
                pid=pid,
                phase=phase,
                progress_capture=str(payload.get("progress_capture") or ""),
                machine_id=str(payload.get("machine_id") or ""),
                exited_driver_pid=_int(payload.get("exited_driver_pid")),
            )
        except LookupError as exc:
            conn.rollback()
            return error("not_found", str(exc))
        except DriverAlreadyAttached as exc:
            conn.rollback()
            return _already_attached(exc)
        except DeploymentRunRowLockBusy as exc:
            conn.rollback()
            return error(ROW_LOCK_BUSY_CODE, str(exc))
        except ValueError as exc:
            conn.rollback()
            return error("payload_invalid", str(exc))
        conn.commit()
    return HandlerOutcome(
        result_payload={
            "run_id": resolved,
            "recorded": recorded is not None,
            "driver": recorded.as_dict() if recorded is not None else {},
        },
        primary_success=True,
    )


def handle_release_driver(request: FunctionCallRequest) -> HandlerOutcome:
    resolved = run_id(request, RELEASE_FUNCTION_ID)
    if isinstance(resolved, HandlerOutcome):
        return resolved
    pid = _int((request.payload or {}).get("pid"))
    session_id = str(request.actor.session_id or "").strip()
    if not session_id:
        return error("unauthenticated", "a session is required to release a driver")
    if pid <= 0:
        return error("payload_invalid", "pid is required")
    if refusal := execution._require_execution_lock(request, resolved):
        return refusal
    from yoke_core.domain.db_helpers import connect

    with connect() as conn:
        try:
            released = release_driver(conn, resolved, session_id=session_id, pid=pid)
        except DeploymentRunRowLockBusy as exc:
            conn.rollback()
            return error(ROW_LOCK_BUSY_CODE, str(exc))
        conn.commit()
    return HandlerOutcome(
        result_payload={"run_id": resolved, "released": released},
        primary_success=True,
    )


def handle_driver_for_capture(request: FunctionCallRequest) -> HandlerOutcome:
    if invalid := require_global(request, FOR_CAPTURE_FUNCTION_ID):
        return invalid
    capture = str((request.payload or {}).get("progress_capture") or "").strip()
    if not capture:
        return error("payload_invalid", "progress_capture is required")
    from yoke_core.domain.db_helpers import connect, iso8601_now

    with connect() as conn:
        found = live_attachment_for_capture(
            conn, progress_capture=capture, now=iso8601_now()
        )
    return HandlerOutcome(
        result_payload={"driver": None if found is None else found.as_dict()},
        primary_success=True,
    )


def register(registry) -> None:
    for function_id, handler, request_model, response_model in (
        (
            ATTACH_FUNCTION_ID,
            handle_attach_driver,
            AttachDriverRequest,
            AttachDriverResponse,
        ),
        (
            RELEASE_FUNCTION_ID,
            handle_release_driver,
            ReleaseDriverRequest,
            ReleaseDriverResponse,
        ),
    ):
        registry.register(
            function_id,
            handler,
            request_model,
            response_model,
            stability="stable",
            owner_module=__name__,
            target_kinds=["workflow_run"],
            side_effects=["deployment_runs_update"],
            emitted_event_names=["YokeFunctionCalled"],
            guardrails=["deploy_lock_required"],
            adapter_status="internal",
            claim_required_kind=None,
            minimum_serving_version="next-release",
        )
    registry.register(
        FOR_CAPTURE_FUNCTION_ID,
        handle_driver_for_capture,
        DriverForCaptureRequest,
        DriverForCaptureResponse,
        stability="stable",
        owner_module=__name__,
        target_kinds=["global"],
        side_effects=[],
        emitted_event_names=["YokeFunctionCalled"],
        guardrails=[],
        adapter_status="internal",
        claim_required_kind=None,
        minimum_serving_version="next-release",
    )


__all__ = [
    "handle_attach_driver",
    "handle_driver_for_capture",
    "handle_release_driver",
    "register",
]
