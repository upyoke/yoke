"""Internal server-side writes for merge and done-transition bookkeeping.

Two done-transition control-plane writes used to open a local ``connect()``
inside the engine, which fails over an https control plane (no local
Postgres):

* the collapsed local done finalization — resolve ``deployed_to``, update
  ``items.deployed_to`` when a target env is known, and upsert the item's
  ``release_entries`` row, all inside ONE transaction, and
* the pre-flight ``items.merged_at`` population.

These handlers relay both writes server-side (dispatched in-process
against a local Postgres connection, or over https server-side) while the
engine keeps every git and filesystem operation local. Each handler is a
thin wrapper over the UNCHANGED engine/domain write: the finalize handler
runs the exact
:func:`yoke_core.engines.done_transition_finalize._resolve_deployed_to`
resolution, the same conditional ``deployed_to`` update, and the unchanged
:func:`~yoke_core.engines.done_transition_finalize._insert_release_note`
release-note upsert on a SINGLE connection with the same explicit commit,
so the whole finalization stays ATOMIC in one relay. The engine keeps its
operator narratives; these handlers return only the raw write result.

These are ``adapter_status='internal'`` (merge finalize glue, never an agent
CLI surface) and ``ambient_session_required=False``: the done transition
runs in a merge subprocess that may resolve no ambient harness session, so
these session-optional writes match the read siblings' no-session posture.
They are claim-free because the merge writes they replace were claim-free
(a raw control-plane connection, no claim check) — the item claim /
QA-gate ceremony is enforced upstream by the done-transition status flip,
not by these finalize writes.
"""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field, ValidationError

from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionError,
    HandlerOutcome,
)


class FinalizeLocalSideEffectsRequest(BaseModel):
    release_category: str = Field(..., min_length=1)
    env_name: str = ""
    title: str = ""
    item_project: str = ""


class FinalizeLocalSideEffectsResponse(BaseModel):
    deployed_to: str
    release_note: bool


class PopulateMergedAtRequest(BaseModel):
    merged_at: str = Field(..., min_length=1)


class PopulateMergedAtResponse(BaseModel):
    item_id: int
    merged_at: str


class MarkLandingPendingRequest(BaseModel):
    pr_number: str = Field(..., min_length=1)
    enqueued_at: str = Field(..., min_length=1)


class MarkLandingPendingResponse(BaseModel):
    item_id: int
    pr_number: str
    enqueued_at: str
    landed_at: str = ""
    notified_at: str = ""


class ClearLandingPendingRequest(BaseModel):
    pass


class ClearLandingPendingResponse(BaseModel):
    item_id: int
    cleared: bool


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


def handle_finalize_local_side_effects(
    request: FunctionCallRequest,
) -> HandlerOutcome:
    """Run the collapsed local done finalization inside ONE transaction.

    Wraps the unchanged single-connection sequence the engine ran inline:
    :func:`yoke_core.engines.done_transition_finalize._resolve_deployed_to`,
    the conditional ``items.deployed_to`` update, and
    :func:`~yoke_core.engines.done_transition_finalize._insert_release_note`,
    then the explicit commit. Keeping all three on one connection with one
    commit preserves the finalize atomicity — the caller relays this once
    rather than splitting deployed_to and release-note into separate writes.
    Any DB-level failure surfaces as a structured error so the engine can
    degrade exactly as its inline ``except`` clauses did (the item still
    reaches done; finalization is advisory).
    """
    item_id = _require_item_id(request)
    if item_id is None:
        return _err(
            "target_invalid",
            "finalize_local_side_effects requires target.item_id",
        )
    try:
        body = FinalizeLocalSideEffectsRequest.model_validate(request.payload)
    except ValidationError as exc:
        return _err("payload_invalid", f"finalize payload invalid: {exc}")

    from yoke_core.engines.done_transition_finalize import (
        _insert_release_note,
        _resolve_deployed_to,
    )

    try:
        with _connect_rw() as conn:
            deployed_to = _resolve_deployed_to(conn, item_id, body.env_name)
            if deployed_to:
                p = _placeholder(conn)
                conn.execute(
                    f"UPDATE items SET deployed_to = {p} WHERE id = {p}",
                    (deployed_to, item_id),
                )
            release_note = _insert_release_note(
                conn,
                item_id,
                body.release_category,
                body.title,
                body.item_project,
            )
            conn.commit()
    except Exception as exc:  # noqa: BLE001 - engine degrades on any failure
        return _err("finalize_local_side_effects_failed", str(exc))

    return HandlerOutcome(
        result_payload={
            "deployed_to": deployed_to or "",
            "release_note": bool(release_note),
        },
        primary_success=True,
    )


def handle_populate_merged_at(request: FunctionCallRequest) -> HandlerOutcome:
    """Set ``items.merged_at`` to the caller-resolved timestamp.

    Wraps the unchanged single-statement update the engine ran inline. The
    timestamp is resolved client-side (the engine's ``now``) and passed in
    the payload so the value is identical across transports. The engine
    already skipped the update when ``merged_at`` was set (a relayed read),
    so this handler always writes.
    """
    item_id = _require_item_id(request)
    if item_id is None:
        return _err("target_invalid", "populate_merged_at requires target.item_id")
    try:
        body = PopulateMergedAtRequest.model_validate(request.payload)
    except ValidationError as exc:
        return _err("payload_invalid", f"populate_merged_at payload invalid: {exc}")

    try:
        with _connect_rw() as conn:
            p = _placeholder(conn)
            conn.execute(
                f"UPDATE items SET merged_at = {p} WHERE id = {p}",
                (body.merged_at, item_id),
            )
            conn.commit()
    except Exception as exc:  # noqa: BLE001 - surfaced so the caller aborts
        return _err("populate_merged_at_failed", str(exc))

    return HandlerOutcome(
        result_payload={"item_id": item_id, "merged_at": body.merged_at},
        primary_success=True,
    )


def handle_mark_landing_pending(request: FunctionCallRequest) -> HandlerOutcome:
    """Persist one idempotent merge-queue handoff marker."""
    item_id = _require_item_id(request)
    if item_id is None:
        return _err("target_invalid", "landing_pending.mark requires target.item_id")
    try:
        body = MarkLandingPendingRequest.model_validate(request.payload)
    except ValidationError as exc:
        return _err("payload_invalid", f"landing marker payload invalid: {exc}")

    try:
        with _connect_rw() as conn:
            p = _placeholder(conn)
            row = conn.execute(
                "SELECT merge_queue_pr_number, merge_queue_enqueued_at, "
                "merge_queue_landed_at, merge_queue_notified_at FROM items "
                f"WHERE id = {p}",
                (item_id,),
            ).fetchone()
            if row is None:
                return _err("target_not_found", f"item {item_id} not found")
            same_pr = str(row[0] or "") == body.pr_number
            enqueued_at = str(row[1]) if same_pr and row[1] else body.enqueued_at
            landed_at = str(row[2] or "") if same_pr else ""
            notified_at = str(row[3] or "") if same_pr else ""
            conn.execute(
                "UPDATE items SET merge_queue_pr_number = {0}, "
                "merge_queue_enqueued_at = {0}, merge_queue_landed_at = {0}, "
                "merge_queue_notified_at = {0} WHERE id = {0}".format(p),
                (
                    body.pr_number,
                    enqueued_at,
                    landed_at or None,
                    notified_at or None,
                    item_id,
                ),
            )
            conn.commit()
    except Exception as exc:  # noqa: BLE001 - surfaced to the merge boundary
        return _err("landing_pending_mark_failed", str(exc))

    return HandlerOutcome(
        result_payload={
            "item_id": item_id,
            "pr_number": body.pr_number,
            "enqueued_at": enqueued_at,
            "landed_at": landed_at,
            "notified_at": notified_at,
        },
        primary_success=True,
    )


def handle_clear_landing_pending(request: FunctionCallRequest) -> HandlerOutcome:
    """Clear the queue handoff only after item close-out succeeds."""
    item_id = _require_item_id(request)
    if item_id is None:
        return _err("target_invalid", "landing_pending.clear requires target.item_id")
    try:
        ClearLandingPendingRequest.model_validate(request.payload)
        with _connect_rw() as conn:
            p = _placeholder(conn)
            cursor = conn.execute(
                "UPDATE items SET merge_queue_pr_number = NULL, "
                "merge_queue_enqueued_at = NULL, merge_queue_landed_at = NULL, "
                f"merge_queue_notified_at = NULL WHERE id = {p}",
                (item_id,),
            )
            conn.commit()
            cleared = bool(cursor.rowcount)
    except ValidationError as exc:
        return _err("payload_invalid", f"landing marker payload invalid: {exc}")
    except Exception as exc:  # noqa: BLE001 - advisory close-out warning
        return _err("landing_pending_clear_failed", str(exc))
    return HandlerOutcome(
        result_payload={"item_id": item_id, "cleared": cleared},
        primary_success=True,
    )


__all__ = [
    "FinalizeLocalSideEffectsRequest",
    "FinalizeLocalSideEffectsResponse",
    "ClearLandingPendingRequest",
    "ClearLandingPendingResponse",
    "MarkLandingPendingRequest",
    "MarkLandingPendingResponse",
    "PopulateMergedAtRequest",
    "PopulateMergedAtResponse",
    "handle_clear_landing_pending",
    "handle_finalize_local_side_effects",
    "handle_mark_landing_pending",
    "handle_populate_merged_at",
]
