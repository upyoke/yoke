"""Registered add-or-remove amendment handler for path claims."""

from __future__ import annotations

from yoke_contracts.api.function_call import FunctionCallRequest, HandlerOutcome
from yoke_core.domain.handlers.claims_path import (
    _connect_rw,
    _err,
    _validate,
    handle_widen,
)
from yoke_core.domain.handlers.claims_path_models import (
    AmendRequest,
    AmendResponse,
)


def _widen(request: FunctionCallRequest) -> HandlerOutcome:
    outcome = handle_widen(request)
    if outcome.primary_success:
        outcome.result_payload["amendment_kind"] = "widen"
    return outcome


def _narrow(
    request: FunctionCallRequest,
    body: AmendRequest,
) -> HandlerOutcome:
    from yoke_core.domain.migration_path_claim_widen import lock_claim_for_widen
    from yoke_core.domain.path_claims import PathClaimError
    from yoke_core.domain.path_claims_amend import narrow
    from yoke_core.domain.path_claims_events import emit_amended
    from yoke_core.domain.path_claims_read import claim_projection
    from yoke_core.domain.path_claims_resolve import (
        PathResolveError,
        resolve_paths_to_target_ids,
    )

    with _connect_rw() as conn:
        try:
            context = lock_claim_for_widen(
                conn,
                claim_id=int(body.claim_id),
                expected_item_id=request.target.item_id,
            )
            remove_ids = list(body.remove_target_ids)
            if body.remove_paths:
                resolved_ids = resolve_paths_to_target_ids(
                    conn,
                    context.project_id,
                    list(body.remove_paths),
                )
                remove_ids.extend(resolved_ids)
            remove_ids = list(dict.fromkeys(remove_ids))
            amendment_id = narrow(
                conn,
                claim_id=int(body.claim_id),
                drop_target_ids=remove_ids,
                reason=body.reason,
                repo_path=body.repo_path,
                worktree_head=body.worktree_head,
                boundary_evidence=(
                    body.boundary_evidence.model_dump()
                    if body.boundary_evidence is not None
                    else None
                ),
            )
            projection = claim_projection(conn, int(body.claim_id))
            emit_amended(
                conn=conn,
                claim=projection,
                amendment_id=amendment_id,
                amendment_kind="narrow",
                payload={"removed": remove_ids},
                reason=body.reason,
                project=context.project,
            )
        except PathResolveError as exc:
            conn.rollback()
            return _err("path_resolve_failed", str(exc))
        except (PathClaimError, ValueError) as exc:
            conn.rollback()
            return _err("amend_failed", f"{type(exc).__name__}: {exc}")
    return HandlerOutcome(
        result_payload={
            "amendment_id": int(amendment_id),
            "amendment_kind": "narrow",
            "migration_model": None,
            "migration_lease_id": None,
            "db_claim_event_id": None,
        }
    )


def handle_amend(request: FunctionCallRequest) -> HandlerOutcome:
    body, err = _validate(AmendRequest, request.payload, "amend")
    if err is not None:
        return err
    if body.add_target_ids or body.add_paths:
        return _widen(request)
    return _narrow(request, body)


__all__ = ["AmendRequest", "AmendResponse", "handle_amend"]
