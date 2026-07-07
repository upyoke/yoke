"""Claim verification helpers for the function-call dispatcher.

Extracted from :mod:`yoke_function_dispatch` to keep the dispatcher's
main routing flow within the file-line budget. Each ``claim_required_kind``
maps to one verification predicate:

- ``"item"`` / ``"epic"`` — consult the canonical session-claim lookup
  for the target item / epic id; require the actor's ``session_id`` to
  match the active claim row.
- ``"self_only"`` — read ``work_claims`` by id; require the actor to own
  the claim row.
- ``"operator_override"`` — require the actor's session row to carry the
  operator mode marker.

Tests monkeypatch :func:`who_claims_for_item` and :func:`is_operator_session`
to inject synthetic rows without touching the live DB.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionCallResponse,
    FunctionError,
)
from yoke_core.domain.yoke_function_registry import RegistryEntry


def _placeholder(conn: Any) -> str:
    from yoke_core.domain import db_backend

    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def who_claims_for_item(item_id: int) -> Optional[Dict[str, Any]]:
    """Return the active item-target work_claims row for ``item_id``.

    Thin adapter over the canonical lookup
    ``yoke_core.domain.sessions_queries_lookup.get_claim_for_work_unit``.
    Returns ``None`` when no live claim exists or the lookup fails.
    """
    try:
        from yoke_core.domain import db_helpers
        from yoke_core.domain.sessions_queries_lookup import (
            get_claim_for_work_unit,
        )
    except Exception:
        return None
    try:
        with db_helpers.connect() as conn:
            return get_claim_for_work_unit(conn, item_id=str(item_id))
    except Exception:
        return None


def is_operator_session(actor_session_id: str) -> bool:
    """Return True when the session row's mode marks it as operator.

    Inspects ``harness_sessions.mode``; ``"operator"`` is the canonical
    bypass marker. Returns False on any error or absence.
    """
    if not actor_session_id:
        return False
    try:
        from yoke_core.domain import db_backend, db_helpers
    except Exception:
        return False
    conn = None
    try:
        with db_helpers.connect() as conn:
            p = _placeholder(conn)
            row = conn.execute(
                f"SELECT mode FROM harness_sessions WHERE session_id = {p}",
                (actor_session_id,),
            ).fetchone()
    except db_backend.database_error_types(conn):
        return False
    if row is None:
        return False
    mode = row[0]
    return str(mode or "") == "operator"


def _claim_error(
    request: FunctionCallRequest,
    function_id: str,
    version: str,
    code: str,
    message: str,
) -> FunctionCallResponse:
    return FunctionCallResponse(
        success=False,
        function=function_id,
        version=version,
        request_id=request.request_id,
        result={},
        warnings=[],
        error=FunctionError(code=code, message=message),
        event_ids=[],
    )


def _resolve_qa_requirement_item_id(
    qa_requirement_id: int,
) -> tuple[Optional[int], Optional[str], Optional[str]]:
    """Resolve ``item_id`` from a ``qa_requirements`` row.

    Returns a ``(item_id, error_code, error_message)`` triple:

    - ``(int, None, None)`` on success.
    - ``(None, "not_found", msg)`` when the row is absent.
    - ``(None, "claim_required", msg)`` when ``item_id`` is NULL on the
      row (global qa requirements have no item to claim against) or the
      lookup fails outright.
    """
    try:
        from yoke_core.domain import db_helpers
        with db_helpers.connect() as conn:
            p = _placeholder(conn)
            row = conn.execute(
                f"SELECT item_id FROM qa_requirements WHERE id = {p}",
                (int(qa_requirement_id),),
            ).fetchone()
    except Exception as exc:
        return None, "claim_required", (
            f"failed to resolve qa_requirement_id={qa_requirement_id} "
            f"to item_id: {exc}"
        )
    if row is None:
        return None, "not_found", (
            f"qa_requirement_id={qa_requirement_id} not found"
        )
    item_id = row[0]
    if item_id is None:
        return None, "claim_required", (
            f"qa_requirement_id={qa_requirement_id} has no item_id; "
            "global qa requirements cannot be claim-verified against an item"
        )
    return int(item_id), None, None


def _claim_row_for_id(claim_id: int) -> Optional[Dict[str, Any]]:
    try:
        from yoke_core.domain import db_helpers
        with db_helpers.connect() as conn:
            p = _placeholder(conn)
            row = conn.execute(
                "SELECT id, session_id FROM work_claims "
                f"WHERE id = {p} AND released_at IS NULL",
                (int(claim_id),),
            ).fetchone()
    except Exception:
        return None
    if row is None:
        return None
    return {
        "id": row[0],
        "session_id": row[1],
    }


def _session_claim_id_for_target(
    target: Any, actor_session: str
) -> Optional[int]:
    """Resolve the calling session's active claim id for an item or
    epic_task shaped ``self_only`` target.

    Server-side replacement for the retired client-side claim-id lookup:
    ``yoke claims work release --item / --epic-id+--task-num`` now ship
    the typed target and the dispatcher finds the session's own claim.
    Filtering on ``session_id = actor_session`` makes the lookup itself
    the self-ownership proof.
    """
    if not actor_session:
        return None
    try:
        from yoke_core.domain import db_helpers
        with db_helpers.connect() as conn:
            p = _placeholder(conn)
            if target.kind == "item" and target.item_id is not None:
                row = conn.execute(
                    "SELECT id FROM work_claims "
                    f"WHERE session_id = {p} AND target_kind = 'item' "
                    f"AND item_id = {p} AND released_at IS NULL "
                    "ORDER BY id DESC LIMIT 1",
                    (actor_session, int(target.item_id)),
                ).fetchone()
            elif (
                target.kind == "epic_task"
                and target.epic_id is not None
                and target.task_num is not None
            ):
                row = conn.execute(
                    "SELECT id FROM work_claims "
                    f"WHERE session_id = {p} AND target_kind = 'epic_task' "
                    f"AND epic_id = {p} AND task_num = {p} "
                    "AND released_at IS NULL "
                    "ORDER BY id DESC LIMIT 1",
                    (actor_session, int(target.epic_id), int(target.task_num)),
                ).fetchone()
            else:
                return None
    except Exception:
        return None
    if row is None:
        return None
    return int(row[0] if not hasattr(row, "keys") else row["id"])


def verify_claim(
    entry: RegistryEntry, request: FunctionCallRequest
) -> Optional[FunctionCallResponse]:
    """Run the registry entry's ``claim_required_kind`` check.

    Returns ``None`` when verification passes (or no claim is required).
    Returns a populated :class:`FunctionCallResponse` carrying
    ``error.code="claim_required"`` or ``error.code=
    "operator_override_required"`` otherwise.
    """
    kind = entry.claim_required_kind
    if kind is None:
        return None
    actor_session = request.actor.session_id
    target = request.target
    fid = entry.function_id
    ver = entry.version

    if kind in ("item", "epic"):
        target_id = target.item_id if kind == "item" else target.epic_id
        if (
            target_id is None
            and kind == "item"
            and target.kind == "qa_requirement"
            and target.qa_requirement_id is not None
        ):
            resolved, err_code, err_msg = _resolve_qa_requirement_item_id(
                target.qa_requirement_id
            )
            if err_code is not None:
                return _claim_error(request, fid, ver, err_code, err_msg or "")
            target_id = resolved
        if target_id is None:
            return _claim_error(
                request, fid, ver, "claim_required",
                f"claim_required_kind={kind!r} but target id is missing",
            )
        row = who_claims_for_item(int(target_id))
        claim_session = str((row or {}).get("session_id") or "")
        if not row or claim_session != actor_session:
            return _claim_error(
                request, fid, ver, "claim_required",
                f"no active claim by session {actor_session!r} on "
                f"{kind} {target_id}; acquire one first: "
                f"python3 -m yoke_core.api.service_client claim-work "
                f"--item YOK-{target_id} --reason <intent>",
            )
        return None

    if kind == "self_only":
        claim_id = target.claim_id
        if claim_id is None and target.kind in ("item", "epic_task"):
            resolved = _session_claim_id_for_target(target, actor_session)
            if resolved is None:
                shape = (
                    f"item {target.item_id}"
                    if target.kind == "item"
                    else f"epic_task ({target.epic_id}, {target.task_num})"
                )
                return _claim_error(
                    request, fid, ver, "claim_required",
                    f"no active claim by session {actor_session!r} on "
                    f"{shape}; pass --claim-id explicitly or acquire one "
                    "first: yoke claims work acquire",
                )
            # The lookup filters on the actor's session, so resolution
            # itself is the self-ownership proof — no re-check needed.
            target.claim_id = resolved
            return None
        if claim_id is None:
            return _claim_error(
                request, fid, ver, "claim_required",
                "claim_required_kind='self_only' but target.claim_id is missing",
            )
        row = _claim_row_for_id(int(claim_id))
        owner = str((row or {}).get("session_id") or "")
        if owner != actor_session:
            return _claim_error(
                request, fid, ver, "claim_required",
                f"claim {claim_id} not held by session {actor_session!r}; "
                f"acquire your own claim with: "
                f"python3 -m yoke_core.api.service_client claim-work "
                f"--item YOK-<id> --reason <intent>",
            )
        return None

    if kind == "operator_override":
        if not is_operator_session(actor_session):
            return _claim_error(
                request, fid, ver, "operator_override_required",
                f"session {actor_session!r} lacks operator-override authority",
            )
        return None

    # Defensive — registry validation makes this unreachable.
    return _claim_error(
        request, fid, ver, "claim_required",
        f"unknown claim_required_kind {kind!r}",
    )


__all__ = [
    "who_claims_for_item",
    "is_operator_session",
    "verify_claim",
    "_resolve_qa_requirement_item_id",
]
