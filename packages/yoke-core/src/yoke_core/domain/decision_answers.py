"""The answers people have given a decision request.

Reading answers is separate from judging them: :mod:`approval_decisions`
asks whether a policy is satisfied, while this module only says who
answered what and when. Every reader here is set-shaped underneath,
because the surfaces that ask — an Inbox page, a gate list — ask for
several requests at once and ask for each of them more than once.
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping, Optional

from yoke_core.domain import db_backend


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _decision_payload(row: Any) -> dict[str, Any]:
    return {
        "id": int(row[1]),
        "actor_id": int(row[2]),
        "action": str(row[3]),
        "note": row[4],
        "decided_at": str(row[5]),
        # Which surface answered. Empty for a decision recorded before
        # the session was stored, and for one taken with no session.
        "decided_session_id": str(row[6] or ""),
    }


def decisions_for_requests(
    conn: Any,
    request_ids: Iterable[int],
) -> dict[int, list[dict[str, Any]]]:
    """Answers for a set of requests, keyed by request, in one statement.

    A page showing several gates asks this for every one of them, and each
    gate's own composition asks it more than once, so the set form is what
    keeps an Inbox read sized by its gates rather than by how many times
    each is consulted. A request with no answers yet is absent.
    """
    ids = tuple(dict.fromkeys(int(value) for value in request_ids))
    if not ids:
        return {}
    p = _p(conn)
    rows = conn.execute(
        "SELECT request_id, id, actor_id, action, note, decided_at, "
        "decided_session_id FROM decision_request_decisions "
        f"WHERE request_id IN ({', '.join(p for _ in ids)}) "
        "ORDER BY request_id, decided_at, id",
        ids,
    ).fetchall()
    grouped: dict[int, list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(int(row[0]), []).append(_decision_payload(row))
    return grouped


def list_decisions(conn: Any, request_id: int) -> list[dict[str, Any]]:
    """Return one request's answers in the order they were given.

    The one-element case of :func:`decisions_for_requests`.
    """
    return decisions_for_requests(conn, (int(request_id),)).get(int(request_id), [])


def decision_by_actor(
    decisions: Iterable[Mapping[str, Any]],
    actor_id: int,
) -> Optional[dict[str, Any]]:
    """This actor's own answer among answers already read, if they gave one."""
    for decision in decisions:
        if int(decision["actor_id"]) == int(actor_id):
            return dict(decision)
    return None


def actor_decision(
    conn: Any,
    request_id: int,
    actor_id: int,
) -> Optional[dict[str, Any]]:
    """Return this actor's own answer, when they have already given one.

    A caller that already holds the request's answers uses
    :func:`decision_by_actor` instead of reading them again.
    """
    return decision_by_actor(list_decisions(conn, request_id), actor_id)


__all__ = [
    "actor_decision",
    "decision_by_actor",
    "decisions_for_requests",
    "list_decisions",
]
