"""Function handlers for project onboarding checklist runs."""

from __future__ import annotations

from typing import Any, Dict, Optional

from pydantic import BaseModel

from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionError,
    HandlerOutcome,
)
from yoke_contracts.onboard_checklist import BRANCH_LOCAL_CHECKOUT, OPERATION_INIT
from yoke_core.domain import project_onboarding_runs


class OnboardChecklistInitRequest(BaseModel):
    run_id: Optional[str] = None
    project_id: Optional[int] = None
    project: Optional[str] = None
    branch: str = BRANCH_LOCAL_CHECKOUT
    checkout_path: Optional[str] = None
    machine_config_path: Optional[str] = None
    github_repo: Optional[str] = None
    row_status: Optional[Dict[str, str]] = None
    evidence: Optional[Dict[str, Any]] = None
    blocker: Optional[Dict[str, Optional[str]]] = None
    note: Optional[Dict[str, Optional[str]]] = None
    metadata: Optional[Dict[str, Any]] = None


class OnboardChecklistInitResponse(BaseModel):
    schema_version: int
    operation: str
    run_id: str
    resumed: bool
    status: str
    rows: list
    summary: dict
    run: dict


class OnboardChecklistRunRequest(BaseModel):
    run_id: Optional[str] = None
    project_id: Optional[int] = None
    project: Optional[str] = None
    branch: Optional[str] = None
    checkout_path: Optional[str] = None
    machine_config_path: Optional[str] = None
    github_repo: Optional[str] = None
    row_status: Optional[Dict[str, str]] = None
    evidence: Optional[Dict[str, Any]] = None
    blocker: Optional[Dict[str, Optional[str]]] = None
    note: Optional[Dict[str, Optional[str]]] = None
    metadata: Optional[Dict[str, Any]] = None


class OnboardChecklistRunResponse(OnboardChecklistInitResponse):
    pass


def handle_onboard_checklist_init(request: FunctionCallRequest) -> HandlerOutcome:
    payload = request.payload or {}
    return _handle(payload, operation=OPERATION_INIT)


def handle_onboard_checklist_run(request: FunctionCallRequest) -> HandlerOutcome:
    payload = request.payload or {}
    return _handle(payload, operation=project_onboarding_runs.OPERATION_RUN)


def _handle(payload: dict[str, Any], *, operation: str) -> HandlerOutcome:
    branch = payload.get("branch")
    if branch is None and operation == OPERATION_INIT:
        branch = BRANCH_LOCAL_CHECKOUT
    project_id, project_error = _resolve_project_ref(payload)
    if project_error is not None:
        return project_error
    try:
        result = project_onboarding_runs.update_run(
            run_id=payload.get("run_id"),
            project_id=project_id,
            branch=branch,
            checkout_path=payload.get("checkout_path"),
            machine_config_path=payload.get("machine_config_path"),
            github_repo=payload.get("github_repo"),
            row_status=payload.get("row_status") or {},
            evidence=payload.get("evidence") or {},
            blocker=payload.get("blocker") or {},
            note=payload.get("note") or {},
            metadata=payload.get("metadata") or {},
            operation=operation,
        )
    except project_onboarding_runs.ProjectOnboardingRunError as exc:
        return HandlerOutcome(
            primary_success=False,
            error=FunctionError(
                code="onboard_checklist_failed",
                message=str(exc),
            ),
        )
    return HandlerOutcome(result_payload=result, primary_success=True)


def _resolve_project_ref(
    payload: dict[str, Any],
) -> tuple[Optional[int], Optional[HandlerOutcome]]:
    """Resolve the run's numeric project id from the payload.

    A numeric ``project_id`` wins; otherwise a ``project`` slug-or-id ref
    (the standalone init shape) resolves through the project registry so
    the run row stays project-attributed. No ref at all stays ``None`` —
    machine-only runs carry no project.
    """
    project_id = payload.get("project_id")
    ref = payload.get("project")
    if project_id is not None or not ref:
        return project_id, None
    from yoke_core.domain.db_helpers import connect
    from yoke_core.domain.project_identity import resolve_project_id

    conn = connect()
    try:
        return resolve_project_id(conn, str(ref)), None
    except LookupError as exc:
        return None, HandlerOutcome(
            primary_success=False,
            error=FunctionError(
                code="project_not_found",
                message=str(exc),
                jsonpath="$.payload.project",
            ),
        )
    finally:
        conn.close()


__all__ = [
    "OnboardChecklistInitRequest",
    "OnboardChecklistInitResponse",
    "OnboardChecklistRunRequest",
    "OnboardChecklistRunResponse",
    "handle_onboard_checklist_init",
    "handle_onboard_checklist_run",
]
