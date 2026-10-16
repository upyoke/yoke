"""Run-scoped authority for the existing client-local deploy pipeline."""

from __future__ import annotations

import json
from contextlib import nullcontext
from typing import Any, Dict, List, Optional

from yoke_core.domain.deployment_start_timing import (
    timed_call,
    timed_handler,
    timing_facts,
)
from yoke_core.domain.schema_read_scope import composition_operation
from pydantic import BaseModel

from yoke_contracts.api.function_call import FunctionCallRequest, HandlerOutcome
from yoke_core.domain.handlers.deployment_common import (
    error,
    run_id,
    update_refusal_code,
)


#: Error code an execution call carries when another session drives the run.
RUN_DRIVEN_ELSEWHERE_CODE = "run_driven_elsewhere"


class DeploymentExecutionContextRequest(BaseModel):
    pass


class DeploymentExecutionContextResponse(BaseModel):
    run: Dict[str, Any]
    members: List[Dict[str, Any]]
    stages: List[Dict[str, Any]]
    # Public references this call enrolled from the pinned candidate, so the
    # driver can print exactly what the deployment gained before it starts.
    enrolled_carried_items: List[str] = []
    # How this run's persistent QA targets can prove what they serve:
    # the project's configured served-revision path and the registered url
    # of each environment its QA stages name. Resolved here because both
    # are control-plane authority — a driver that read them from its own
    # machine would prove nothing about the environment.
    target_identity: Dict[str, Any] = {}
    candidate_containment_basis: Dict[str, Any] = {}
    start_timings: List[Dict[str, Any]] = []


class DeploymentExecutionUpdateRequest(BaseModel):
    field: str
    value: str
    candidate_containment: Optional[Dict[str, Any]] = None


class DeploymentExecutionUpdateResponse(BaseModel):
    run_id: str
    field: str
    value: str
    updated: bool
    start_timings: List[Dict[str, Any]] = []


def require_run_driver(
    request: FunctionCallRequest, resolved_run_id: str
) -> Optional[HandlerOutcome]:
    """Refuse a caller other than the run's live driver.

    A run with no live driver may be driven by any authorized session; one
    that has a live driver answers only to that driver's session, so a
    second session cannot interleave writes into a pipeline in flight. A
    driver whose heartbeat lapsed frees the run by itself: no human
    release is ever needed.
    """
    from yoke_core.domain.db_helpers import connect, utc_now, query_scalar
    from yoke_core.domain.deployment_run_driver_attachment import (
        format_refusal,
        live_attachment_for_run,
    )

    with connect() as conn:
        exists = query_scalar(
            conn,
            "SELECT 1 FROM deployment_runs WHERE id=%s",
            (resolved_run_id,),
        )
        if exists is None:
            return error("not_found", f"deployment run {resolved_run_id!r} not found")
        driver = live_attachment_for_run(
            conn, run_id_value=resolved_run_id, now=utc_now()
        )
    caller = str(request.actor.session_id or "").strip()
    if driver is not None and driver.session_id != caller:
        return error(RUN_DRIVEN_ELSEWHERE_CODE, format_refusal(resolved_run_id, driver))
    return None


def _record_bound_sources(
    conn: Any, run_id_value: str
) -> Dict[str, Any] | HandlerOutcome:
    """Pin every project's source commit before anything reads one.

    A stage that binds another project's branch substitutes the commit the
    run recorded, and delivery credits the items that commit contains, so
    the resolution happens once here rather than per stage. A branch that
    cannot be reached refuses the start by name: dispatching an unrecorded
    binding would ship a commit nothing can later account for.

    The payload travels back to the driver rather than being left for it to
    re-read, because a database that has not yet converged the column has
    nowhere to store it — and the release carrying that converge is driven
    by this very call, with a bound stage that still has to dispatch a real
    commit. The record commits on its own, so a composition refusal on the
    same connection afterwards still leaves the pinned commit in place.
    """
    from yoke_core.domain.deployment_run_bound_sources import record_bound_sources

    try:
        recorded = record_bound_sources(conn, run_id_value)
    except (LookupError, ValueError) as exc:
        conn.rollback()
        return error("bound_source_unresolved", str(exc))
    conn.commit()
    return recorded


def _record_and_compose(
    run_id_value: str, composition_result: Dict[str, Any]
) -> tuple[Dict[str, Any], tuple[bool, str]] | HandlerOutcome:
    """Pin bound sources, then validate composition on the same connection.

    One connection keeps the branch heads the record resolved inside this
    operation's read scope, so validation reuses them instead of asking the
    repository host again.
    """
    from yoke_core.domain.db_helpers import connect
    from yoke_core.domain.deployment_runs_validation import cmd_validate_composition

    with connect() as conn:
        bound_sources = timed_call(
            "context_bound_sources", _record_bound_sources, conn, run_id_value
        )
        if isinstance(bound_sources, HandlerOutcome):
            return bound_sources
        verdict = timed_call(
            "context_composition",
            cmd_validate_composition,
            run_id_value,
            composition_result=composition_result,
            connection=conn,
        )
        if verdict[0]:
            conn.commit()
        else:
            conn.rollback()
        return bound_sources, verdict


def _member_rows(run_id_value: str, *, connection: Any = None) -> List[Dict[str, Any]]:
    from yoke_core.domain.db_helpers import connect, query_rows
    from yoke_core.domain.item_worktrees import primary_item_worktree
    from yoke_core.domain.project_identity import render_item_ref

    with connect() if connection is None else nullcontext(connection) as conn:
        rows = query_rows(
            conn,
            "SELECT dri.item_id,dri.delivery_intent,dri.requirement_snapshot,"
            "i.status,i.deployed_to FROM deployment_run_items dri "
            "JOIN items i ON i.id=dri.item_id WHERE dri.run_id=%s "
            "ORDER BY dri.item_id",
            (run_id_value,),
        )
        members = []
        for row in rows:
            item_id = int(row["item_id"])
            lane = primary_item_worktree(conn, item_id) or {}
            members.append(
                {
                    "item_id": item_id,
                    "public_ref": render_item_ref(conn, item_id),
                    "status": str(row["status"]),
                    "deployed_to": str(row.get("deployed_to") or ""),
                    "branch": str(lane.get("branch") or ""),
                    "delivery_intent": row["delivery_intent"],
                    "requirement_snapshot": row["requirement_snapshot"],
                }
            )
        return members


@timed_handler
@composition_operation
def handle_deployment_execution_context(
    request: FunctionCallRequest,
) -> HandlerOutcome:
    resolved_run_id = run_id(request, "deployment_runs.execution.context")
    if isinstance(resolved_run_id, HandlerOutcome):
        return resolved_run_id
    if refusal := require_run_driver(request, resolved_run_id):
        return refusal
    composition_result: Dict[str, Any] = {}
    composed = _record_and_compose(resolved_run_id, composition_result)
    if isinstance(composed, HandlerOutcome):
        return composed
    bound_sources, (valid, composition_message) = composed
    if not valid:
        return error("composition_invalid", composition_message)
    from yoke_core.domain.deployment_run_carried_work import parse_carried_work
    from yoke_core.domain.deployment_run_contained_items import (
        CandidateContainmentRefusal,
        candidate_containment_basis,
    )
    from yoke_core.domain.deployment_runs_crud_query import get_run
    from yoke_core.domain.db_helpers import connect
    from yoke_core.domain.deployment_target_identity_config import run_target_identity
    from yoke_core.domain.flow import cmd_stages
    from yoke_core.domain.project_identity import resolve_project_id

    run = timed_call("context_run_read", get_run, resolved_run_id)
    if run is None:
        return error("not_found", f"deployment run {resolved_run_id!r} not found")
    run["carried_work"] = parse_carried_work(run.get("carried_work"))
    timing_facts(source_sha=str(run.get("release_lineage") or ""))
    # The resolution above is authoritative for this execution, converged
    # column or not; the row read would project an empty string before it.
    run["bound_sources"] = bound_sources
    try:
        with connect() as conn:
            stages = json.loads(
                timed_call("context_stages", cmd_stages, conn, str(run["flow"]))
            )
            containment_basis = timed_call(
                "context_containment_basis",
                candidate_containment_basis,
                conn,
                resolved_run_id,
            )
            target_identity = timed_call(
                "context_target_identity",
                run_target_identity,
                conn,
                project_id=resolve_project_id(conn, str(run["project"])),
                stages=stages,
                target_environment=str(run.get("target_environment") or ""),
            )
    except (
        CandidateContainmentRefusal,
        LookupError,
        ValueError,
        json.JSONDecodeError,
    ) as exc:
        return error("execution_context_invalid", str(exc))
    members = timed_call("context_members", _member_rows, resolved_run_id)
    timing_facts(member_count=len(members))
    return HandlerOutcome(
        result_payload={
            "run": run,
            "members": members,
            "stages": stages,
            "target_identity": target_identity,
            "candidate_containment_basis": containment_basis,
            "enrolled_carried_items": list(composition_result.get("enrolled", ())),
        },
        primary_success=True,
    )


@timed_handler
@composition_operation
def handle_deployment_execution_update(
    request: FunctionCallRequest,
) -> HandlerOutcome:
    resolved_run_id = run_id(request, "deployment_runs.execution.update")
    if isinstance(resolved_run_id, HandlerOutcome):
        return resolved_run_id
    payload = request.payload or {}
    field = str(payload.get("field") or "").strip()
    value = payload.get("value")
    if field not in {"status", "current_stage"}:
        return error(
            "invalid_field",
            "execution updates are limited to status and current_stage",
            jsonpath="$.payload.field",
        )
    if value is None:
        return error("payload_invalid", "value is required", jsonpath="$.payload.value")
    if refusal := require_run_driver(request, resolved_run_id):
        return refusal
    from yoke_core.domain.deployment_runs_crud_mutate import cmd_update

    attestation = payload.get("candidate_containment")
    if update_error := cmd_update(
        resolved_run_id,
        field,
        str(value),
        candidate_containment=(
            dict(attestation) if isinstance(attestation, dict) else None
        ),
    ):
        return error(update_refusal_code(update_error), update_error)
    return HandlerOutcome(
        result_payload={
            "run_id": resolved_run_id,
            "field": field,
            "value": str(value),
            "updated": True,
        },
        primary_success=True,
    )


__all__ = [
    "DeploymentExecutionContextRequest",
    "DeploymentExecutionContextResponse",
    "DeploymentExecutionUpdateRequest",
    "DeploymentExecutionUpdateResponse",
    "_record_bound_sources",
    "RUN_DRIVEN_ELSEWHERE_CODE",
    "require_run_driver",
    "handle_deployment_execution_context",
    "handle_deployment_execution_update",
]
