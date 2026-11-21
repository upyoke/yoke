"""Claim-conflict, machine-health, and project-capability read handlers."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel

from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionError,
    HandlerOutcome,
)


# ---------------------------------------------------------------------------
# path_claims.conflicts.list.run
# ---------------------------------------------------------------------------


class PathClaimsConflictsRequest(BaseModel):
    integration_target: Optional[str] = None


class PathClaimsConflictsResponse(BaseModel):
    conflicts: List[Dict[str, Any]]


def handle_path_claims_conflicts(request: FunctionCallRequest) -> HandlerOutcome:
    from yoke_core.domain.db_helpers import connect
    from yoke_core.domain.path_claims_read import cross_claim_conflicts

    integration_target = (request.payload or {}).get("integration_target")
    conn = connect()
    try:
        conflicts = cross_claim_conflicts(
            conn,
            integration_target=(
                str(integration_target) if integration_target else None
            ),
        )
    finally:
        conn.close()
    item_id = request.target.item_id
    if item_id is not None:
        filtered = []
        for c in conflicts:
            try:
                self_item = c.get("self", {}).get("item_id")
                other_item = c.get("other", {}).get("item_id")
                if (self_item is not None and int(self_item) == int(item_id)) or (
                    other_item is not None and int(other_item) == int(item_id)
                ):
                    filtered.append(c)
            except (TypeError, ValueError):
                continue
        conflicts = filtered
    return HandlerOutcome(
        result_payload={"conflicts": conflicts},
        primary_success=True,
    )


# ---------------------------------------------------------------------------
# doctor.run.run — exactly one of quick / full / only, unless payload.receipt.


class DoctorRunRequest(BaseModel):
    only: Optional[str] = None
    quick: bool = False
    full: bool = False
    fix: bool = False
    project: Optional[str] = None
    db_path: Optional[str] = None
    runtime: Optional[str] = None
    receipt: Optional[Dict[str, Any]] = None


class DoctorRunResponse(BaseModel):
    results: List[Dict[str, Any]]
    scope: str
    project: str
    runtime: str
    fail_count: int
    warn_count: int
    pass_count: int
    na_count: int


def handle_doctor_run(request: FunctionCallRequest) -> HandlerOutcome:
    payload = request.payload or {}
    if "receipt" in payload:
        from yoke_core.domain.last_doctor_run_read import record_receipt_from_payload

        return record_receipt_from_payload(payload.get("receipt"))
    from yoke_core.domain.service_runtime_ports import get_doctor_run

    return get_doctor_run().run(request)


# ---------------------------------------------------------------------------
# projects.capability.has.run
# ---------------------------------------------------------------------------


class ProjectsCapabilityHasRequest(BaseModel):
    project: str
    cap_type: str


class ProjectsCapabilityHasResponse(BaseModel):
    project: str
    cap_type: str
    has: bool


def handle_projects_capability_has(request: FunctionCallRequest) -> HandlerOutcome:
    payload = request.payload or {}
    project = payload.get("project")
    cap_type = payload.get("cap_type")
    if not project or not isinstance(project, str):
        return HandlerOutcome(
            primary_success=False,
            error=FunctionError(
                code="payload_invalid",
                message="project is required",
                jsonpath="$.payload.project",
            ),
        )
    if not cap_type or not isinstance(cap_type, str):
        return HandlerOutcome(
            primary_success=False,
            error=FunctionError(
                code="payload_invalid",
                message="cap_type is required",
                jsonpath="$.payload.cap_type",
            ),
        )
    from yoke_core.domain.projects_crud import cmd_has_capability

    has = bool(cmd_has_capability(project, cap_type))
    return HandlerOutcome(
        result_payload={
            "project": project,
            "cap_type": cap_type,
            "has": has,
        },
        primary_success=True,
    )


__all__ = [
    "PathClaimsConflictsRequest",
    "PathClaimsConflictsResponse",
    "handle_path_claims_conflicts",
    "DoctorRunRequest",
    "DoctorRunResponse",
    "handle_doctor_run",
    "ProjectsCapabilityHasRequest",
    "ProjectsCapabilityHasResponse",
    "handle_projects_capability_has",
]
