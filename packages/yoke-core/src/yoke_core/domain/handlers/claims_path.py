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

from typing import Any, List, Optional

from pydantic import BaseModel, Field

from yoke_core.domain import db_backend
from yoke_core.domain.path_claim_register import render_overlap_denial_for_register
from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionError,
    HandlerOutcome,
)


class RegisterRequest(BaseModel):
    item_id: Optional[int] = None
    integration_target: Optional[str] = None
    paths: List[str] = Field(default_factory=list)
    mode: str = "exclusive"
    exception_reason: Optional[str] = None
    allow_planned: bool = False
    directory_paths: Optional[List[str]] = None
    tentative_paths: Optional[List[str]] = None
    upstream_claim_id: Optional[int] = None
    actor_id: Optional[int] = None


class RegisterResponse(BaseModel):
    claim_id: int


class WidenRequest(BaseModel):
    claim_id: int
    add_target_ids: List[int] = Field(default_factory=list)
    add_paths: List[str] = Field(default_factory=list)
    reason: str = Field(..., min_length=1)
    repo_path: Optional[str] = None
    worktree_head: Optional[str] = None
    allow_planned: bool = False
    directory_paths: Optional[List[str]] = None


class WidenResponse(BaseModel):
    amendment_id: int


class ReleaseRequest(BaseModel):
    claim_id: int
    reason: str = Field(..., min_length=1)


class ReleaseResponse(BaseModel):
    claim_id: int
    state: str
    released_at: Optional[str] = None


class OverrideRequest(BaseModel):
    path_claim_id: int
    override_point: str = "creation"
    integration_target: str
    actor_id: int
    actor_reason: str = Field(..., min_length=1)
    blocking_claim_id: Optional[int] = None
    blocking_path_targets: Optional[List[int]] = None
    conflict_reason: Optional[str] = None
    item_id: Optional[int] = None
    project: Optional[str] = None


class OverrideResponse(BaseModel):
    override_event_id: Optional[str] = None


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


def _project_for_claim(conn: Any, claim_id: int) -> int:
    """Resolve the owning item's project for a claim id."""
    p = _p(conn)
    row = conn.execute(
        "SELECT items.project_id FROM path_claims "
        "JOIN items ON items.id = path_claims.item_id "
        f"WHERE path_claims.id = {p}",
        (int(claim_id),),
    ).fetchone()
    if row is None or not row[0]:
        raise ValueError(f"cannot resolve project for claim_id={claim_id}")
    return int(row[0])


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
            claim_id = register_for_item(
                conn,
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
        except (ItemNotFound, ItemHasNoProject) as exc:
            return _err("item_not_found", str(exc))
        except DefaultActorUnavailable as exc:
            return _err("actor_unavailable", str(exc))
        except PathClaimError as exc:
            message = render_overlap_denial_for_register(
                conn, exc=exc, item_id=int(body.item_id),
                integration_target=integration_target, paths=list(body.paths),
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

    from yoke_core.domain.path_claims import PathClaimError
    from yoke_core.domain.path_claims_amend import widen
    from yoke_core.domain.path_claims_resolve import (
        PathResolveError,
        resolve_or_plan_paths_to_target_ids,
        resolve_paths_to_target_ids,
    )

    with _connect_rw() as conn:
        add_ids = list(body.add_target_ids)
        if body.add_paths:
            try:
                project = _project_for_claim(conn, int(body.claim_id))
                if body.allow_planned:
                    p = _p(conn)
                    row = conn.execute(
                        f"SELECT item_id FROM path_claims WHERE id = {p}",
                        (int(body.claim_id),),
                    ).fetchone()
                    item_id_attr = (
                        int(row[0])
                        if row is not None and row[0] is not None
                        else None
                    )
                    resolved_ids = resolve_or_plan_paths_to_target_ids(
                        conn,
                        project,
                        list(body.add_paths),
                        item_id=item_id_attr,
                        claim_id=int(body.claim_id),
                        session_id=request.actor.session_id,
                        directory_paths=body.directory_paths,
                    )
                else:
                    resolved_ids = resolve_paths_to_target_ids(
                        conn, project, list(body.add_paths),
                    )
                add_ids = list(dict.fromkeys(add_ids + list(resolved_ids)))
            except PathResolveError as exc:
                return _err("path_resolve_failed", str(exc))
            except ValueError as exc:
                return _err("widen_failed", str(exc))
        try:
            amendment_id = widen(
                conn,
                claim_id=int(body.claim_id),
                add_target_ids=add_ids,
                reason=body.reason,
                repo_path=body.repo_path,
                worktree_head=body.worktree_head,
            )
        except PathClaimError as exc:
            return _err("widen_failed", f"{type(exc).__name__}: {exc}")

    return HandlerOutcome(result_payload={"amendment_id": int(amendment_id)})


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
