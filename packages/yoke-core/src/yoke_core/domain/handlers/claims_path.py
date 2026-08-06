"""Yoke function handlers for ``claims.path.*`` register/widen/release/override.

Activation + coordination_decision handlers live in
:mod:`claims_path_activation` (sibling module) to keep both files under
the 350-line budget.

Reuse: routes through :mod:`yoke_core.domain.path_claims`,
:mod:`yoke_core.domain.path_claims_register`,
:mod:`yoke_core.domain.path_claims_amend`,
:mod:`yoke_core.domain.path_claims_override`. No path-claim mutation
logic is re-implemented here.
"""

from __future__ import annotations

from typing import Any, Optional

from yoke_core.domain import db_backend
from yoke_core.domain.handlers.claims_path_models import (
    OverrideRequest,
    OverrideResponse,
    RegisterRequest,
    RegisterResponse,
    ReleaseRequest,
    ReleaseResponse,
    WidenRequest,
    WidenResponse,
)
from yoke_core.domain.path_claim_register import render_overlap_denial_for_register
from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionError,
    HandlerOutcome,
)


def _err(code: str, message: str, *, jsonpath: Optional[str] = None) -> HandlerOutcome:
    return HandlerOutcome(
        primary_success=False,
        error=FunctionError(code=code, message=message, jsonpath=jsonpath),
    )


def _connect_rw() -> Any:
    from yoke_core.domain import db_helpers

    return db_helpers.connect()


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _validate(model_cls, payload: Any, label: str):
    try:
        return model_cls.model_validate(payload), None
    except Exception as exc:
        return None, _err("payload_invalid", f"{label} payload invalid: {exc}")


def handle_register(request: FunctionCallRequest) -> HandlerOutcome:
    body, err = _validate(RegisterRequest, request.payload, "register")
    if err is not None:
        return err
    if body.item_id is None and request.target.item_id is not None:
        body.item_id = int(request.target.item_id)
    if body.item_id is None:
        return _err(
            "payload_invalid",
            "register requires an item id (payload or resolved target)",
            jsonpath="$.payload.item_id",
        )

    from yoke_core.domain.path_claims import PathClaimError
    from yoke_core.domain.path_claim_task_bindings import (
        PathClaimTaskBindingError,
    )
    from yoke_core.domain.path_claim_task_registration import register_for_task
    from yoke_core.domain.path_claims_register import (
        DefaultActorUnavailable,
        ItemHasNoProject,
        ItemNotFound,
        PathClaimRegistrationError,
        register_for_item,
    )
    from yoke_core.domain.path_claims_register_validate_integration_target import (
        resolve_and_validate_integration_target,
    )

    with _connect_rw() as conn:
        try:
            integration_target = resolve_and_validate_integration_target(
                conn,
                item_id=int(body.item_id),
                supplied_target=body.integration_target,
            )
        except PathClaimRegistrationError as exc:
            return _err("integration_target_invalid", str(exc))
        try:
            registrar = (
                register_for_task if body.task_num is not None else register_for_item
            )
            kwargs = dict(
                conn=conn,
                item_id=int(body.item_id),
                integration_target=integration_target,
                paths=list(body.paths),
                upstream_claim_id=body.upstream_claim_id,
                actor_id=body.actor_id,
                session_id=request.actor.session_id,
                mode=body.mode,
                exception_reason=body.exception_reason,
                allow_planned=body.allow_planned,
                directory_paths=body.directory_paths,
                tentative_paths=body.tentative_paths,
            )
            if body.task_num is not None:
                kwargs["task_num"] = int(body.task_num)
            claim_id = registrar(**kwargs)
        except (ItemNotFound, ItemHasNoProject) as exc:
            return _err("item_not_found", str(exc))
        except DefaultActorUnavailable as exc:
            return _err("actor_unavailable", str(exc))
        except PathClaimTaskBindingError as exc:
            return _err("task_binding_invalid", str(exc))
        except PathClaimError as exc:
            message = render_overlap_denial_for_register(
                conn,
                exc=exc,
                item_id=int(body.item_id),
                integration_target=integration_target,
                paths=list(body.paths),
                allow_planned=body.allow_planned,
                session_id=request.actor.session_id,
            )
            fallback = f"{type(exc).__name__}: {exc}"
            return _err("register_failed", message if message is not None else fallback)

    return HandlerOutcome(result_payload={"claim_id": int(claim_id)})


def handle_widen(request: FunctionCallRequest) -> HandlerOutcome:
    body, err = _validate(WidenRequest, request.payload, "widen")
    if err is not None:
        return err

    from yoke_core.domain.coordination_leases import LeaseError
    from yoke_core.domain.db_claim import DbClaimAmendmentError
    from yoke_core.domain.migration_path_claim_widen import (
        lock_claim_for_widen,
        widen_locked_claim,
    )
    from yoke_core.domain.path_claims import PathClaimError
    from yoke_core.domain.path_claims_resolve import (
        PathResolveError,
        resolve_or_plan_paths_to_target_ids,
        resolve_paths_to_target_ids,
    )

    with _connect_rw() as conn:
        try:
            context = lock_claim_for_widen(
                conn,
                claim_id=int(body.claim_id),
                expected_item_id=request.target.item_id,
            )
            add_ids = list(body.add_target_ids)
            if body.add_paths:
                if body.allow_planned:
                    resolved_ids = resolve_or_plan_paths_to_target_ids(
                        conn,
                        context.project_id,
                        list(body.add_paths),
                        item_id=context.item_id,
                        claim_id=int(body.claim_id),
                        session_id=request.actor.session_id,
                        directory_paths=body.directory_paths,
                    )
                else:
                    resolved_ids = resolve_paths_to_target_ids(
                        conn,
                        context.project_id,
                        list(body.add_paths),
                    )
                add_ids = list(dict.fromkeys(add_ids + list(resolved_ids)))
            result = widen_locked_claim(
                conn,
                claim_id=int(body.claim_id),
                context=context,
                add_target_ids=add_ids,
                reason=body.reason,
                session_id=request.actor.session_id,
                db_claim_payload=body.db_claim,
                repo_path=body.repo_path,
                worktree_head=body.worktree_head,
            )
        except PathResolveError as exc:
            conn.rollback()
            return _err("path_resolve_failed", str(exc))
        except (DbClaimAmendmentError, LeaseError, PathClaimError, ValueError) as exc:
            conn.rollback()
            return _err("widen_failed", f"{type(exc).__name__}: {exc}")

    return HandlerOutcome(
        result_payload={
            "amendment_id": int(result.amendment_id),
            "migration_model": result.migration_model,
            "migration_lease_id": result.migration_lease_id,
            "db_claim_event_id": result.db_claim_event_id,
        }
    )


# ``claims.path.amend`` is an alias on widen — the external "amend" verb
# consumers reach for. Narrow has a distinct boundary-check code path;
# surfacing it as ``claims.path.narrow`` is out of scope for this task.
handle_amend = handle_widen


def handle_release(request: FunctionCallRequest) -> HandlerOutcome:
    body, err = _validate(ReleaseRequest, request.payload, "release")
    if err is not None:
        return err

    from yoke_core.domain.path_claims import (
        ClaimNotFound,
        PathClaimError,
        release,
    )

    with _connect_rw() as conn:
        try:
            release(conn, claim_id=int(body.claim_id), reason=body.reason)
        except ClaimNotFound as exc:
            return _err("claim_not_found", str(exc))
        except PathClaimError as exc:
            return _err("release_failed", f"{type(exc).__name__}: {exc}")
        p = _p(conn)
        row = conn.execute(
            f"SELECT state, released_at FROM path_claims WHERE id = {p}",
            (int(body.claim_id),),
        ).fetchone()

    return HandlerOutcome(
        result_payload={
            "claim_id": int(body.claim_id),
            "state": str(row["state"]) if row else "released",
            "released_at": row["released_at"] if row else None,
        },
    )


def handle_override(request: FunctionCallRequest) -> HandlerOutcome:
    body, err = _validate(OverrideRequest, request.payload, "override")
    if err is not None:
        return err

    from yoke_core.domain.path_claims_override import (
        ClaimNotFound,
        EmptyActorReason,
        HookContextRejection,
        PathClaimOverrideError,
        invoke_override,
    )

    with _connect_rw() as conn:
        try:
            event_id = invoke_override(
                conn,
                path_claim_id=int(body.path_claim_id),
                override_point=body.override_point,
                integration_target=body.integration_target,
                actor_id=int(body.actor_id),
                actor_reason=body.actor_reason,
                blocking_claim_id=body.blocking_claim_id,
                blocking_path_targets=body.blocking_path_targets,
                conflict_reason=body.conflict_reason,
                item_id=body.item_id,
                project=body.project,
                session_id=request.actor.session_id,
            )
        except HookContextRejection as exc:
            return _err("hook_context_rejected", str(exc))
        except EmptyActorReason as exc:
            return _err("actor_reason_required", str(exc))
        except ClaimNotFound as exc:
            return _err("claim_not_found", str(exc))
        except PathClaimOverrideError as exc:
            return _err("override_failed", f"{type(exc).__name__}: {exc}")

    return HandlerOutcome(result_payload={"override_event_id": event_id})


__all__ = [
    "RegisterRequest",
    "RegisterResponse",
    "WidenRequest",
    "WidenResponse",
    "ReleaseRequest",
    "ReleaseResponse",
    "OverrideRequest",
    "OverrideResponse",
    "handle_register",
    "handle_widen",
    "handle_amend",
    "handle_release",
    "handle_override",
]
