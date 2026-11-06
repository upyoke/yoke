"""Present a decision's audience; all live membership belongs to audiences."""

from __future__ import annotations

from typing import Any, Mapping

from yoke_contracts.refusal_recovery import compose_refusal
from yoke_core.domain import audiences, db_backend
from yoke_core.domain.actor_render import actor_display_labels


def _audience_id(conn: Any, request_id: int, request: Mapping | None = None) -> int:
    if request is not None:
        return int(request["audience_id"])
    p = "%s" if db_backend.connection_is_postgres(conn) else "?"
    row = conn.execute(
        f"SELECT audience_id FROM decision_requests WHERE id = {p}", (request_id,)
    ).fetchone()
    if row is None:
        raise LookupError(f"Decision request {request_id} does not exist")
    return int(row[0])


def _reason(match: Mapping) -> str:
    if match["scope_kind"] == "actor":
        return "asked of you"
    return f"{match['scope_kind']} {str(match.get('role_name') or 'member').replace('_', ' ')}"


def authority_reason(
    conn: Any,
    request_id: int,
    actor_id: int,
    *,
    request: Mapping | None = None,
    matches: list[dict] | None = None,
) -> str | None:
    if matches is None:
        matches = audiences.member_matches(
            conn, _audience_id(conn, request_id, request), actor_id
        )
    matches = [row for row in matches if row["actor_id"] == actor_id]
    return _reason(matches[0]) if matches else None


def request_deciders(
    conn: Any,
    request_id: int,
    viewer_actor_id: int | None = None,
    *,
    request: Mapping | None = None,
    matches: list[dict] | None = None,
) -> list[dict]:
    if matches is None:
        matches = audiences.member_matches(
            conn, _audience_id(conn, request_id, request)
        )
    deciders = {}
    for match in matches:
        actor_id = int(match["actor_id"])
        deciders.setdefault(
            actor_id,
            {
                "actor_id": actor_id,
                "via": "named" if match["scope_kind"] == "actor" else _reason(match),
                "is_you": actor_id == viewer_actor_id,
            },
        )
    labels = actor_display_labels(conn, deciders)
    for actor_id, decider in deciders.items():
        decider["label"] = labels[actor_id]
    return sorted(deciders.values(), key=lambda row: row["label"])


def decision_request_authority_actor_ids(conn: Any, request_id: int) -> tuple[int, ...]:
    return tuple(
        sorted(
            {
                int(row["actor_id"])
                for row in audiences.member_matches(
                    conn, _audience_id(conn, request_id)
                )
            }
        )
    )


def human_role_holders(
    conn: Any, *, scope_kind: str, scope_id: int, role_name: str
) -> tuple[int, ...]:
    return audiences.rule_actor_ids(
        conn, {"scope_kind": scope_kind, "scope_id": scope_id, "role_name": role_name}
    )


def unauthorized_resolution_message(conn: Any, request_id: int, actor_id: int) -> str:
    caller = actor_display_labels(conn, (actor_id,)).get(actor_id, "This person")
    rules = audiences.rules_for_audiences(conn, (_audience_id(conn, request_id),))
    values = next(iter(rules.values()), [])
    required = [
        "a named human" if row["scope_kind"] == "actor" else _reason(row)
        for row in values
    ]
    deciders = request_deciders(conn, request_id, actor_id)
    humans = (
        "eligible humans: " + ", ".join(row["label"] for row in deciders)
        if deciders
        else "no eligible human currently holds the required authority"
    )
    return compose_refusal(
        f"{caller} is not authorized for decision request {request_id}: required {', '.join(required)}. {humans}. Caller is {caller}.",
        recovery="Answer from an eligible human Inbox, or grant a required role to a human actor. Do not assign roles automatically",
    )


__all__ = [
    "authority_reason",
    "decision_request_authority_actor_ids",
    "human_role_holders",
    "request_deciders",
    "unauthorized_resolution_message",
]
