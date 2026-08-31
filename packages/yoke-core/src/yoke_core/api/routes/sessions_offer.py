"""Session offer endpoint — POST /v1/sessions/offer."""

from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi.responses import JSONResponse
from fastapi.routing import APIRouter

from yoke_core.domain import db_backend
from yoke_core.domain.sessions import (
    SessionError,
    display_claim_item_id,
    normalize_claim_item_id,
    read_chain_checkpoint,
    resolve_claimed_work_context,
    session_offer_with_ownership,
    set_session_mode,
)
from yoke_core.domain.frontier_compute import _canonical_project_label
from yoke_core.domain.scheduler import compute_schedule
from yoke_core.domain.session_project_scope import resolve_session_project_scope
from yoke_core.domain.session import (
    ClaimedWork,
    FrontierState,
    SessionOffer,
    build_drift_review_failure_action,
    should_emit_drift_review_checkpoint,
)
from yoke_core.api.routing_config import (
    PROJECT_ROUTING_CAPABILITY,
    get_max_chain_steps,
    load_process_offer_policy,
    load_project_routing_settings,
    load_routing_config,
)
from yoke_core.api.service_client_sessions_frontier import (
    build_frontier_state_from_schedule,
)
from yoke_core.api.service_client_sessions_offer_helpers import (
    build_no_work_wait_action, dump_offer_result, should_return_no_work_wait,
)
from yoke_core.api.service_client_sessions_offer_invariant import (
    HTTP_SURFACE,
    handle_charge_invariant,
)
from yoke_core.domain.session_decision_process_gate import (
    merge_skip_memory_with_policy,
    record_disabled_process_skip,
)
from yoke_core.domain.sessions_offer_envelope_merge import persist_offer_diagnostics
from yoke_core.domain.sessions_identity_read import resolve_session_identity
from yoke_core.domain.work_claim_targets import (
    from_row as target_from_row, item_id_from_row,
)
from yoke_core.api.routes.session_offer_models import SessionOfferRequest

router = APIRouter()


def _main_api():
    import yoke_core.api.main as main
    return main


@router.post("/sessions/offer")
def api_session_offer(req: SessionOfferRequest) -> JSONResponse:
    """Accept a session offer and return a NextAction directive."""
    _main = _main_api()
    if not req.session_id:
        return _main._error_response(
            400, "MISSING_FIELD", "session_id is required.",
        )

    conn = _main.get_db_readwrite()
    try:
        _config_path = _main.get_config_path()
        max_chain_steps = get_max_chain_steps(_config_path)

        try:
            project_scope = resolve_session_project_scope(
                conn, override=req.project_scope,
            )
        except ValueError as exc:
            return _main._error_response(400, "UNKNOWN_PROJECT", str(exc))
        project_label = _canonical_project_label(conn, project_scope)

        try:
            identity = resolve_session_identity(conn, req.session_id)
        except SessionError as exc:
            return _main._error_response(400, exc.code, exc.message)

        policy_project_id: Optional[int] = identity.project_id
        if policy_project_id is None and project_scope and len(project_scope) == 1:
            policy_project_id = int(project_scope[0])

        project_routing_settings = load_project_routing_settings(
            conn, policy_project_id,
        )
        routing_config = load_routing_config(
            _config_path,
            project_settings=project_routing_settings,
        )
        process_offer_policy = load_process_offer_policy(
            _config_path,
            project_settings=project_routing_settings,
            shared_project_source=(
                f"project {policy_project_id} capability {PROJECT_ROUTING_CAPABILITY}"
                if project_routing_settings and policy_project_id is not None
                else None
            ),
        )
        # The row carries the lane registration resolved; a supplied body
        # lane is the deliberate operator override on top of it.
        resolved_lane = identity.execution_lane
        offer = SessionOffer(
            session_id=req.session_id,
            executor=identity.executor,
            provider=identity.provider,
            model=identity.model,
            requested_model=identity.requested_model,
            capabilities=identity.capabilities,
            workspace=identity.workspace,
            execution_lane=resolved_lane,
            step=req.step,
            supported_paths=[],
        )

        ownership = session_offer_with_ownership(
            conn,
            session_id=req.session_id,
            executor=identity.executor,
            provider=identity.provider,
            model=identity.model,
            requested_model=identity.requested_model,
            workspace=identity.workspace,
            execution_lane=resolved_lane,
            caller_supplied_lane=req.execution_lane,
            capabilities=identity.capabilities,
            lane_allowed_paths=routing_config.lane_allowed_paths,
            step=req.step,
            project_scope=project_scope,
            max_chain_steps=max_chain_steps, apply_workspace_home_filter=req.project_scope is None,
        )
        authoritative_lane = ownership.get("authoritative_lane") or resolved_lane
        offer = offer.model_copy(
            update={
                "supported_paths": ownership.get("supported_paths") or [],
                "execution_lane": authoritative_lane,
            }
        )
        effective_policy = merge_skip_memory_with_policy(
            process_offer_policy, ownership.get("chain_skip_memory"),
        )

        drift_dict: Optional[Dict[str, Any]] = None
        if ownership["action_hint"] == "resume":
            active_claims = []
            for c in ownership["claims"]:
                target = target_from_row(c)
                claim_ctx = resolve_claimed_work_context(conn, c)
                active_claims.append(ClaimedWork(
                    item_id=display_claim_item_id(target.item_id, conn),
                    epic_id=target.epic_id,
                    task_num=target.task_num,
                    status=claim_ctx.get("status"),
                    workflow_id=claim_ctx.get("workflow_id"),
                    workflow_version_id=claim_ctx.get("workflow_version_id"),
                    workflow_version=claim_ctx.get("workflow_version"),
                    required_path=claim_ctx.get("required_path"),
                ))
            last_step: Optional[Dict[str, Any]] = None
            checkpoint = read_chain_checkpoint(conn, req.session_id)
            if checkpoint:
                last_step = {
                    "action": checkpoint.get("action"),
                    "item_id": checkpoint.get("item_id"),
                    "task_num": checkpoint.get("task_num"),
                    "status": checkpoint.get("status"),
                    "required_path": checkpoint.get("required_path"),
                    "handler_outcome": checkpoint.get("handler_outcome"),
                    "pre_status": checkpoint.get("pre_status"),
                }
            schedule = compute_schedule(
                conn, project_scope=project_scope, session_id=req.session_id,
            )
            try:
                drift = _main.assess_post_delivery_drift(conn, project_scope)
            except RuntimeError as exc:
                result = build_drift_review_failure_action(req.session_id, str(exc))
            else:
                drift_dict = drift.to_dict() if drift else None
                frontier = _main._build_frontier_state(
                    schedule,
                    drift_review_dict=drift_dict,
                    last_completed_step=last_step,
                    conn=conn,
                )
                result = _main.decide_next_action(
                    offer,
                    frontier,
                    active_claims,
                    lane_allowed_paths=routing_config.lane_allowed_paths,
                    process_offer_policy=effective_policy,
                )
        elif should_return_no_work_wait(ownership, req.step):
            result = build_no_work_wait_action(
                session_id=req.session_id,
                ownership=ownership,
                step=req.step,
                process_offer_policy=effective_policy, actual_lane=offer.execution_lane,
            )
        elif ownership["schedule_result"] is not None:
            schedule = ownership["schedule_result"]
            try:
                drift = _main.assess_post_delivery_drift(conn, project_scope)
            except RuntimeError as exc:
                result = build_drift_review_failure_action(req.session_id, str(exc))
            else:
                drift_dict = drift.to_dict() if drift else None
                skip_ids = {
                    normalize_claim_item_id(str(e.get("item_id")))
                    for e in (ownership.get("chain_skip_memory") or [])
                    if e.get("item_id")
                }
                frontier = build_frontier_state_from_schedule(
                    schedule,
                    drift_review_dict=drift_dict,
                    skip_memory_item_ids=skip_ids or None,
                    conn=conn,
                )
                result = _main.decide_next_action(
                    offer,
                    frontier,
                    None,
                    lane_allowed_paths=routing_config.lane_allowed_paths,
                    process_offer_policy=effective_policy,
                )
        else:
            frontier = FrontierState()
            result = _main.decide_next_action(
                offer,
                frontier,
                None,
                lane_allowed_paths=routing_config.lane_allowed_paths,
                process_offer_policy=effective_policy,
            )

        _new_claim = ownership.get("new_claim")
        if _new_claim and result.action.value != "charge":
            _override_item = item_id_from_row(_new_claim)
            if _override_item:
                _release_result = _main.release_item_claim_for_execution(
                    conn,
                    req.session_id,
                    str(_override_item),
                    "offer-override",
                )
                if not _release_result.get("released"):
                    return _main._error_response(
                        500,
                        "CLAIM_RECONCILE_FAILED",
                        "Failed to release offer-time claim before non-charge action.",
                    )

        ok, err = handle_charge_invariant(
            conn,
            session_id=req.session_id,
            result=result,
            new_claim=_new_claim,
            ownership=ownership,
            surface=HTTP_SURFACE,
            project=project_label,
        )
        if not ok:
            return _main._error_response(
                500,
                "CHARGE_CLAIM_INVARIANT_FAILED",
                err or "Charge action failed claim invariant.",
            )
        set_session_mode(conn, req.session_id, result.action.value)
        record_disabled_process_skip(
            conn,
            session_id=req.session_id,
            chain_step=req.step,
            project=project_label,
            action=result,
        )
        persist_offer_diagnostics(conn, req.session_id, (result.context or {}).get("offer_diagnostics"))
        if should_emit_drift_review_checkpoint(result, drift_dict):
            # State first: advance each scoped project's checkpoint anchor,
            # then emit the matching telemetry event.
            from yoke_core.domain.strategy_checkpoints import (
                record_checkpoints,
            )
            record_checkpoints(
                conn, projects=project_scope, kind="drift_review",
            )
            conn.commit()
            _main.emit_drift_review_completed(
                session_id=req.session_id,
                project=project_label,
                project_scope=project_scope,
                classification=drift_dict["classification"],
                summary=drift_dict["summary"],
                checkpoint_start=drift_dict["checkpoint_start"],
                reviewed_through=drift_dict["reviewed_through"],
                delivered_items=drift_dict.get("delivered_items"),
            )

        _main.emit_next_action_chosen(
            session_id=req.session_id,
            action=result.action.value,
            reason=result.reason,
            correlation_id=result.correlation_id,
            project=project_label,
            chainable=result.chainable,
            step=req.step,
            supported_paths=ownership.get("supported_paths"),
            context=result.context,
        )

        _main.emit_post_decision_telemetry(
            conn,
            req.session_id,
            action=result.action.value,
            reason=result.reason,
            actual_lane=authoritative_lane,
            context=result.context,
            project=project_label,
        )

        return JSONResponse(status_code=200, content=dump_offer_result(result))
    except db_backend.operational_error_types(conn) as exc:
        if "database is locked" in str(exc).lower():
            return _main._error_response(503, "DB_BUSY", "Database is locked.")
        raise
    finally:
        conn.close()


__all__ = ["router", "SessionOfferRequest"]
