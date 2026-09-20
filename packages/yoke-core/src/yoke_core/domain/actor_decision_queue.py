"""The gates one actor still owes an answer, and the ones they just gave.

Both lists are a page: the candidate gates are selected first, composed
for the set in one pass, and only then asked the per-reader questions —
whether this actor may answer, what they already answered, and who else
can. Composing one gate at a time re-read the same four tables for every
gate the page showed.
"""

from __future__ import annotations

from typing import Any, Iterable, Optional

from yoke_core.domain import db_backend
from yoke_core.domain.decision_answers import decision_by_actor
from yoke_core.domain.decision_request_authority import (
    authority_reason,
    request_deciders,
)
from yoke_core.domain.decision_request_rows import request_rows


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


# How many of an actor's own settled requests the Inbox keeps beside what
# still waits on them. The answers themselves are permanent rows in
# ``decision_request_decisions``; this bounds only how far back one reader
# sees their own recent history.
RECENTLY_DECIDED_SHOWN = 10


def pending_requests_for_actor(
    conn: Any,
    actor_id: int,
    *,
    project_ids: Optional[Iterable[int]] = None,
) -> list[dict[str, Any]]:
    """List what still waits on this actor, and what they have already answered.

    A request the actor already decided stays in their list rather than
    vanishing: under ``all`` it is still open, still theirs to watch, and the
    honest thing to show them is that their own part is done and who the gate
    is now waiting on.
    """
    allowed_projects = (
        {int(value) for value in project_ids} if project_ids is not None else None
    )
    rows = conn.execute(
        "SELECT id FROM decision_requests WHERE status = 'pending' "
        "ORDER BY created_at DESC, id DESC"
    ).fetchall()
    composed = request_rows(conn, (int(row[0]) for row in rows))
    result = []
    for row in rows:
        request = composed.get(int(row[0]))
        if request is None:
            continue
        if (
            allowed_projects is not None
            and request["project_id"] is not None
            and int(request["project_id"]) not in allowed_projects
        ):
            continue
        reason = authority_reason(conn, request["id"], actor_id, request=request)
        if reason is None:
            continue
        decision = decision_by_actor(request["decisions"], actor_id)
        request["asked_of_you"] = reason == "asked of you"
        request["authority_reason"] = reason
        request["your_decision"] = decision
        request["decided_by_you"] = decision is not None
        request["deciders"] = request_deciders(
            conn, request["id"], actor_id, request=request,
        )
        result.append(request)
    result.sort(key=lambda value: (value["decided_by_you"], not value["asked_of_you"]))
    return result


def recently_decided_requests_for_actor(
    conn: Any,
    actor_id: int,
    *,
    project_ids: Optional[Iterable[int]] = None,
    limit: int = RECENTLY_DECIDED_SHOWN,
) -> list[dict[str, Any]]:
    """List the settled requests this actor answered, most recent answer first.

    A request the actor answered stays in ``pending_requests_for_actor`` only
    while the gate itself is still pending. The moment the gate settles the
    request leaves that list, so a reader who had just answered four of them
    reloaded onto an empty history and lost the way back to what they decided.
    Their answers are durable rows, so the settled request is read back through
    the actor's own decision rather than remembered by the page that drew it.

    A settled request offers no actions and cannot be answered again, so it
    carries none: what it still carries is its subject, its evidence, and the
    answer this actor gave it.
    """
    p = _p(conn)
    allowed_projects = (
        {int(value) for value in project_ids} if project_ids is not None else None
    )
    rows = conn.execute(
        "SELECT d.request_id FROM decision_request_decisions d "
        "JOIN decision_requests r ON r.id = d.request_id "
        f"WHERE d.actor_id = {p} AND r.status <> 'pending' "
        "ORDER BY d.decided_at DESC, d.request_id DESC",
        (int(actor_id),),
    ).fetchall()
    # Only the first ``limit`` survivors are shown, but which rows survive is
    # a per-row question, so the window is taken first and composed once.
    composed = request_rows(conn, (int(row[0]) for row in rows[: int(limit)]))
    result: list[dict[str, Any]] = []
    for row in rows:
        if len(result) >= int(limit):
            break
        request = composed.get(int(row[0]))
        if request is None:
            request = request_rows(conn, (int(row[0]),)).get(int(row[0]))
        if request is None:
            continue
        if (
            allowed_projects is not None
            and request["project_id"] is not None
            and int(request["project_id"]) not in allowed_projects
        ):
            continue
        reason = authority_reason(conn, request["id"], actor_id, request=request)
        request["asked_of_you"] = reason == "asked of you"
        request["authority_reason"] = reason
        request["your_decision"] = decision_by_actor(request["decisions"], actor_id)
        request["decided_by_you"] = True
        request["deciders"] = request_deciders(
            conn, request["id"], actor_id, request=request,
        )
        request["actions"] = []
        request["can_act"] = False
        result.append(request)
    return result


__all__ = [
    "RECENTLY_DECIDED_SHOWN",
    "pending_requests_for_actor",
    "recently_decided_requests_for_actor",
]
