"""Yoke function handlers for the ``claims.work.*`` family.

Operations:

- ``claims.work.acquire`` — acquire a typed work claim. ``claim_required_kind=None``
  (chicken-and-egg). The handler asserts no active claim on the target.
- ``claims.work.release`` — release a held claim by id. Dispatcher enforces
  ``self_only`` (caller must be the holder).
- ``claims.work.holder.get`` — single-target claim-holder lookup.
- ``claims.work.holder.list`` — claim-holder list (item or session scope).

Reuse: routes through :mod:`yoke_core.domain.sessions_lifecycle_claim`
(`claim_work`, `release_claim`) and
:mod:`yoke_core.domain.sessions_queries_lookup` (`get_claim_for_work_unit`).
No claim mutation logic is re-implemented; handlers only translate the
function-call envelope into the existing domain calls and back.
"""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field

from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionError,
    HandlerOutcome,
)


# ---------------------------------------------------------------------------
# Request / response models — JSON-schema boundary contracts
# ---------------------------------------------------------------------------


class _WorkTargetSpec(BaseModel):
    """Discriminated work-claim target body. ``kind`` selects which keys apply."""

    kind: Literal["item", "epic_task", "process"]
    item_id: Optional[int] = None
    epic_id: Optional[int] = None
    task_num: Optional[int] = None
    process_key: Optional[str] = None
    project: Optional[str] = None


class AcquireRequest(BaseModel):
    target: _WorkTargetSpec
    reason: Optional[str] = None


class AcquireResponse(BaseModel):
    claim_id: int
    session_id: str
    target_kind: str
    item_id: Optional[int] = None
    epic_id: Optional[int] = None
    task_num: Optional[int] = None
    process_key: Optional[str] = None
    conflict_group: Optional[str] = None
    linked_path_claim_ids: List[int] = Field(default_factory=list)


class ReleaseRequest(BaseModel):
    claim_id: Optional[int] = Field(
        default=None,
        description=(
            "work_claims.id to release; omitted when the envelope target "
            "carries the claim (dispatcher-resolved item/epic_task shape)."
        ),
    )
    reason: str = Field(..., min_length=1)


class ReleaseResponse(BaseModel):
    claim_id: int
    released_at: Optional[str] = None
    release_reason: Optional[str] = None
    linked_path_claim_ids: Optional[List[int]] = None


# ---------------------------------------------------------------------------
# Handler implementations
# ---------------------------------------------------------------------------


def _err(code: str, message: str, *, jsonpath: Optional[str] = None) -> HandlerOutcome:
    return HandlerOutcome(
        primary_success=False,
        error=FunctionError(code=code, message=message, jsonpath=jsonpath),
    )


def _connect_rw() -> Any:
    from yoke_core.domain import db_helpers
    return db_helpers.connect()


def handle_acquire(request: FunctionCallRequest) -> HandlerOutcome:
    """Acquire a typed work claim for ``request.actor.session_id``.

    Asserts no active claim on the target before dispatching to
    :func:`yoke_core.domain.sessions_lifecycle_claim.claim_work`. The
    dispatcher cannot enforce this because ``claim_required_kind=None``
    here — acquisition IS the act of establishing a claim.
    """
    try:
        body = AcquireRequest.model_validate(request.payload)
    except Exception as exc:  # pydantic ValidationError, etc.
        return _err("payload_invalid", f"acquire payload invalid: {exc}")

    target_spec = body.target
    if (
        target_spec.kind == "item"
        and target_spec.item_id is None
        and request.target.item_id is not None
    ):
        # Dispatcher-resolved envelope target carries the id when the
        # client shipped a raw item_ref (relay contract).
        target_spec.item_id = int(request.target.item_id)
    try:
        target = _spec_to_target(target_spec)
    except _TargetSpecError as exc:
        return _err("payload_invalid", str(exc), jsonpath="$.target")

    from yoke_core.domain.sessions_lifecycle_claim import (
        SessionError,
        claim_work,
    )

    session_id = request.actor.session_id
    with _connect_rw() as conn:
        try:
            row = claim_work(
                conn, session_id=session_id, target=target,
                reason=body.reason,
            )
        except SessionError as exc:
            code = (
                "already_claimed"
                if exc.code == "ALREADY_CLAIMED"
                else "claim_failed"
            )
            return _err(code, f"{exc.code}: {exc}")

    return HandlerOutcome(
        result_payload={
            "claim_id": int(row["id"]),
            "session_id": str(row["session_id"]),
            "target_kind": str(row["target_kind"]),
            "item_id": row["item_id"],
            "epic_id": row["epic_id"],
            "task_num": row["task_num"],
            "process_key": row["process_key"],
            "conflict_group": row["conflict_group"],
            "linked_path_claim_ids": list(row.get("linked_path_claim_ids") or []),
        },
    )


def handle_release(request: FunctionCallRequest) -> HandlerOutcome:
    """Release a held claim by id (dispatcher enforces self-only)."""
    try:
        body = ReleaseRequest.model_validate(request.payload)
    except Exception as exc:
        return _err("payload_invalid", f"release payload invalid: {exc}")

    claim_id = body.claim_id
    if claim_id is None and request.target.claim_id is not None:
        # self_only verification resolved the session's own claim onto
        # the target for item/epic_task-shaped release envelopes.
        claim_id = int(request.target.claim_id)
    if claim_id is None:
        return _err(
            "payload_invalid",
            "release requires claim_id (payload or resolved target)",
        )

    from yoke_core.domain.sessions_lifecycle_claim import (
        SessionError,
        release_claim,
    )

    with _connect_rw() as conn:
        try:
            row = release_claim(conn, int(claim_id), reason=body.reason)
        except SessionError as exc:
            return _err("release_failed", f"{exc.code}: {exc}")

    payload_out: Dict[str, Any] = {
        "claim_id": int(row["id"]),
        "released_at": row["released_at"],
        "release_reason": row["release_reason"],
    }
    if "linked_path_claim_ids" in row:
        payload_out["linked_path_claim_ids"] = list(
            row["linked_path_claim_ids"] or []
        )
    return HandlerOutcome(result_payload=payload_out)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _TargetSpecError(ValueError):
    pass


def _spec_to_target(spec: _WorkTargetSpec):
    """Translate the request body's target spec into a WorkClaimTarget."""
    from yoke_core.domain.work_claim_targets import (
        make_epic_task_target,
        make_item_target,
        make_process_target,
    )

    if spec.kind == "item":
        if spec.item_id is None:
            raise _TargetSpecError("target.kind='item' requires item_id")
        return make_item_target(int(spec.item_id))
    if spec.kind == "epic_task":
        if spec.epic_id is None or spec.task_num is None:
            raise _TargetSpecError(
                "target.kind='epic_task' requires epic_id and task_num"
            )
        return make_epic_task_target(int(spec.epic_id), int(spec.task_num))
    if spec.kind == "process":
        if not spec.process_key or not spec.project:
            raise _TargetSpecError(
                "target.kind='process' requires process_key and project"
            )
        return make_process_target(spec.process_key, spec.project)
    raise _TargetSpecError(f"unknown target.kind {spec.kind!r}")


__all__ = [
    "AcquireRequest",
    "AcquireResponse",
    "ReleaseRequest",
    "ReleaseResponse",
    "handle_acquire",
    "handle_release",
]
