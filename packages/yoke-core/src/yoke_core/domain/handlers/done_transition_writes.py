"""Internal server-side writes for done-transition bookkeeping.

The merge-queue landing marker on the same items lives in
:mod:`yoke_core.domain.handlers.merge_queue_marker_writes`.

Two done-transition control-plane writes used to open a local ``connect()``
inside the engine, which fails over an https control plane (no local
Postgres):

* the collapsed local done finalization — resolve ``deployed_to``, update
  ``items.deployed_to`` when a target env is known, and upsert the item's
  ``release_entries`` row, all inside ONE transaction, and
* the pre-flight ``items.merged_at`` population.

These handlers run both writes over a control-plane connection, whether
called in-process or over HTTPS. The engine keeps Git, filesystem operations
and operator output local. The finalize handler owns destination resolution,
the conditional item update and the release note upsert in one transaction.

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

from yoke_contracts.timestamps import format_instant, parse_instant
from yoke_core.domain.db_helpers import instant_parameter

from typing import Any, Optional

from pydantic import BaseModel, Field, ValidationError

from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionError,
    HandlerOutcome,
)
from yoke_contracts.public_ref import ITEM_NOT_FOUND
from yoke_core.domain import db_backend


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
    supersedes_prior_landing: bool = False


class PopulateMergedAtResponse(BaseModel):
    item_id: int
    merged_at: str


def _err(code: str, message: str) -> HandlerOutcome:
    return HandlerOutcome(
        primary_success=False,
        error=FunctionError(code=code, message=message),
    )


def _connect_rw() -> Any:
    from yoke_core.domain import db_helpers

    return db_helpers.connect()


def _placeholder(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _require_item_id(request: FunctionCallRequest) -> Optional[int]:
    if request.target.item_id is None:
        return None
    return int(request.target.item_id)


def _resolve_deployed_to(conn, item_id: int, env_name: str) -> str:
    if env_name:
        return env_name
    try:
        p = _placeholder(conn)
        row = conn.execute(
            "SELECT COALESCE(i.deployment_flow, ''), "
            "COALESCE(e.name, f.target_tier, '') "
            "FROM items i "
            "LEFT JOIN deployment_flows f ON f.id = i.deployment_flow "
            "LEFT JOIN environments e ON e.id = f.target_environment_id "
            f"WHERE i.id = {p}",
            (item_id,),
        ).fetchone()
    except db_backend.operational_error_types(conn):
        return ""
    if not row:
        return ""
    deploy_flow, environment = str(row[0] or ""), str(row[1] or "")
    if deploy_flow and deploy_flow != "null" and environment and environment != "null":
        return environment
    return ""


def _insert_release_note(
    conn,
    item_id: int,
    category: str,
    title: str,
    item_project: str,
) -> bool:
    from yoke_core.domain import release_notes as _release_notes

    try:
        _release_notes.cmd_insert(
            conn,
            int(item_id),
            category,
            title,
            project=item_project or None,
        )
    except db_backend.operational_error_types(conn):
        return False
    return True


def handle_finalize_local_side_effects(
    request: FunctionCallRequest,
) -> HandlerOutcome:
    """Run the collapsed local done finalization inside ONE transaction.

    Resolves the destination, conditionally updates ``items.deployed_to``,
    upserts the release note and commits once. The caller relays the sequence
    as one operation so the destination and release note are written atomically.
    Any DB-level failure surfaces as a structured error so the engine can
    degrade exactly as its inline ``except`` clauses did (the item still
    reaches done; finalization is advisory).
    """
    item_id = _require_item_id(request)
    if item_id is None:
        return _err(
            "target_invalid",
            "finalize_local_side_effects requires target.public_ref",
        )
    try:
        body = FinalizeLocalSideEffectsRequest.model_validate(request.payload)
    except ValidationError as exc:
        return _err("payload_invalid", f"finalize payload invalid: {exc}")

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
    """Record when the branch landed, keeping the first answer recorded.

    Wraps the single-statement update the engine ran inline. The timestamp
    is resolved client-side (the engine's ``now``) and passed in the payload
    so the value is identical across transports.

    A caller reaching here after the landing observer has already recorded
    the moment GitHub reported the merge is stamping the moment close-out
    got around to it, which is later and less true. So the write keeps the
    landing time already on the item: close-out can run minutes or hours
    after the merge, and the report that names a landing nobody closed out
    measures its age from this column.

    ``supersedes_prior_landing`` is how the merge boundary says it is not
    guessing: it read the landing merge commit's own time, which answers for
    a specific landing rather than for whenever this ran. Keeping the earlier
    value would then be wrong rather than kind: an item that lands a second
    time would go on reporting the first landing's date forever, and its
    close-out would report a merge identity the item record never took.

    A landing this control plane observed for itself still outranks that,
    which is why the supersede writes ``merge_queue_landed_at`` when one is
    recorded. A queue merge commit is created when the queue forms its group
    and merged minutes later, so its committer time is genuinely earlier than
    the landing, while the observer holds GitHub's own merge moment. The
    column is safe to prefer because it always belongs to the item's current
    landing pull request: a re-land opens a separate attempt record and
    leaves the columns alone, and the observer moves the columns onto that
    pull request with an empty landing stamp only once it merges, then
    stamps the new merge moment. While an attempt is still open the column
    holds the previous landing, so a close-out that reaches here before the
    observer promotes the attempt takes the resolved commit time instead.
    An item with no queue landing
    -- every standalone merge -- has nothing there and takes the resolved
    commit time, which for that boundary IS the landing time.
    """
    item_id = _require_item_id(request)
    if item_id is None:
        return _err("target_invalid", "populate_merged_at requires target.public_ref")
    try:
        body = PopulateMergedAtRequest.model_validate(request.payload)
    except ValidationError as exc:
        return _err("payload_invalid", f"populate_merged_at payload invalid: {exc}")

    try:
        with _connect_rw() as conn:
            p = _placeholder(conn)
            clock = instant_parameter(conn, parse_instant(body.merged_at))
            if body.supersedes_prior_landing:
                assignment = (
                    f"CASE WHEN EXISTS (SELECT 1 FROM merge_queue_landing_attempts "
                    f"WHERE item_id = {p} AND closed_at IS NULL) THEN {p} "
                    f"ELSE COALESCE(merge_queue_landed_at, {p}) END"
                )
                params: tuple = (item_id, clock, clock, item_id)
            else:
                assignment = f"COALESCE(merged_at, {p})"
                params = (clock, item_id)
            conn.execute(
                f"UPDATE items SET merged_at = {assignment} WHERE id = {p}",
                params,
            )
            row = conn.execute(
                f"SELECT merged_at FROM items WHERE id = {p}",
                (item_id,),
            ).fetchone()
            conn.commit()
    except Exception as exc:  # noqa: BLE001 - surfaced so the caller aborts
        return _err("populate_merged_at_failed", str(exc))
    if row is None:
        return _err("target_not_found", ITEM_NOT_FOUND)

    return HandlerOutcome(
        result_payload={
            "item_id": item_id,
            "merged_at": format_instant(row[0]) if row[0] is not None else None,
        },
        primary_success=True,
    )


__all__ = [
    "FinalizeLocalSideEffectsRequest",
    "FinalizeLocalSideEffectsResponse",
    "PopulateMergedAtRequest",
    "PopulateMergedAtResponse",
    "handle_finalize_local_side_effects",
    "handle_populate_merged_at",
]
