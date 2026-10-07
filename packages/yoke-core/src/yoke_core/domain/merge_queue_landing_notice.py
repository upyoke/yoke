"""Who owns a landing lane, what to tell them, and whether it arrived.

The landing observer decides what GitHub did; this decides who hears about
it. The two are separate because the answer to "who owns this lane"
outlives any one observation: a landing whose holder is gone has to reach
the project's steering seat instead. Notice acceptance and recipient delivery
stay distinct so the observer can stop resending an accepted intent while the
ordinary pending-message path owns delivery.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Callable

from yoke_contracts.session_control.models import RecipientSelector
from yoke_core.domain import db_backend
from yoke_core.domain.session_explicit_wake import mark_explicit_stopped_wake
from yoke_core.domain.session_message_service import send_message
from yoke_core.domain.session_message_store import message_details
from yoke_core.domain.session_message_types import SessionMessageError
from yoke_core.domain.work_claim_targets import scope_int_sql


#: Reached the session holding the item's work claim.
HOLDER = "holder"

#: Reached the project's steering seat because no live holder answered.
STEERING = "steering"


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


#: Live work claims joined to the sessions holding them.
_LIVE_CLAIMS = (
    " FROM work_claims wc JOIN harness_sessions hs ON hs.session_id=wc.session_id "
    "WHERE wc.released_at IS NULL AND hs.terminated_at IS NULL "
)


def resolve_lane_recipient(
    conn: Any, *, item_id: int, project_id: int, owner_session_id: str | None = None
) -> tuple[str, int, str]:
    """The session to tell, its actor, and which route found it.

    The item's own claim holder answers first, live sessions before ended
    ones. A lane nobody holds falls back to the project's steering seat,
    which is what turns an abandoned landing into staffing work instead of
    silence. ``("", 0, "")`` means nobody is addressable at all.
    An explicit execution owner replaces claim lookup, retaining the same
    steering fallback and native-resume delivery path.
    """
    marker = _p(conn)
    item_scope = scope_int_sql(conn, "wc.scope", "item_id")
    project_scope = scope_int_sql(conn, "wc.scope", "project_id")
    common = _LIVE_CLAIMS
    liveness = (
        "ORDER BY CASE WHEN hs.ended_at IS NULL THEN 0 ELSE 1 END, wc.id DESC LIMIT 1"
    )
    if owner_session_id is not None:
        # An execution can belong to a delegated session rather than the
        # claim holder. Only that owner can resume its immutable capture.
        row = conn.execute(
            "SELECT session_id, actor_id FROM harness_sessions "
            f"WHERE session_id={marker} AND terminated_at IS NULL",
            (owner_session_id,),
        ).fetchone()
    else:
        row = conn.execute(
            "SELECT wc.session_id, hs.actor_id"
            + common
            + f"AND wc.target_kind='item' AND {item_scope}={marker} "
            + liveness,
            (item_id,),
        ).fetchone()
    route = HOLDER
    if row is None:
        row = conn.execute(
            "SELECT wc.session_id, hs.actor_id"
            + common
            + f"AND wc.target_kind='steering' AND {project_scope}={marker} "
            + liveness,
            (project_id,),
        ).fetchone()
        route = STEERING
    if row is None or row[1] is None:
        return "", 0, ""
    return str(row[0]), int(row[1]), route


def addressable_items(conn: Any, *, item_ids: Any, project_id: int) -> set[int]:
    """Which items :func:`resolve_lane_recipient` would reach, in two reads.

    A live project steering seat reaches every item; otherwise only items
    with a live claim holder are addressable. Bounded by the item set, not
    one resolution per item.
    """
    ids = sorted({int(item_id) for item_id in item_ids})
    if not ids:
        return set()
    marker = _p(conn)
    live = _LIVE_CLAIMS + "AND hs.actor_id IS NOT NULL "
    project_scope = scope_int_sql(conn, "wc.scope", "project_id")
    seat = conn.execute(
        "SELECT 1"
        + live
        + f"AND wc.target_kind='steering' AND {project_scope}={marker} LIMIT 1",
        (project_id,),
    ).fetchone()
    if seat is not None:
        return set(ids)
    item_scope = scope_int_sql(conn, "wc.scope", "item_id")
    rows = conn.execute(
        f"SELECT DISTINCT {item_scope}"
        + live
        + f"AND wc.target_kind='item' AND {item_scope} IN "
        + f"({','.join([marker] * len(ids))})",
        tuple(ids),
    ).fetchall()
    return {int(row[0]) for row in rows}


def landing_message(
    public_ref: str, pr_number: str, merge_commit: str, route: str
) -> str:
    """Tell whoever owns the lane that it landed, and name what landed.

    The merge commit rides along because close-out from here is done by
    whoever reads this, and a seat picking up an abandoned lane otherwise
    has to go find the merge identity before it can say what it is closing.
    """
    landed = f"#{pr_number}"
    if merge_commit:
        landed = f"{landed}, merge commit {merge_commit[:12]}"
    if route == HOLDER:
        return (
            f"Landing complete for {public_ref} (pull request {landed}) — "
            "run close-out by re-entering the same `yoke merge item` command "
            "with its --result and --verification evidence."
        )
    return (
        f"Landing complete for {public_ref} (pull request {landed}), but its "
        "claim holder is gone. Route normal starvation/restaffing so "
        "`yoke merge item` can close the item out."
    )


def _receipt_delivered(
    conn: Any, message_id: str, session_id: str, *, reject_acknowledged: bool = False
) -> bool:
    """True when the recipient actually received the envelope, not merely queued."""
    details = message_details(conn, message_id)
    for recipient in details.get("recipients") or ():
        if str(recipient.get("session_id") or "") != session_id:
            continue
        if reject_acknowledged and (
            recipient.get("acknowledged_at") or recipient.get("state") == "acknowledged"
        ):
            raise SessionMessageError(
                "notice_already_acknowledged",
                f"notice_already_acknowledged: Notice {message_id} was already "
                "acknowledged; retain the landing "
                "marker and re-enter yoke merge item to record a fresh arming episode.",
            )
        if recipient.get("last_injected_at") or recipient.get("acknowledged_at"):
            return True
        if int(recipient.get("injection_count") or 0) > 0:
            return True
        return str(recipient.get("state") or "") in {"injected", "acknowledged"}
    return False


def notice_already_sent(conn: Any, *, idempotency_key: str) -> bool:
    """Whether this exact notice has already been accepted.

    The key names what the notice is about — for an ejection, the head and
    its arming episodes — so this answers "has the owner already been told
    about this?" without composing or sending anything. The observer needs
    it because a stop it cannot clear a marker for would otherwise be
    re-counted as newly reported on every sweep.
    """
    marker = _p(conn)
    row = conn.execute(
        f"SELECT 1 FROM session_messages WHERE idempotency_key={marker} "
        f"OR idempotency_key LIKE {marker} LIMIT 1",
        (idempotency_key, f"{idempotency_key}:armed:%"),
    ).fetchone()
    return row is not None


def push_notice(
    conn: Any,
    *,
    item_id: int,
    project_id: int,
    body_for_route: Callable[[str], str],
    idempotency_key: str,
    now: datetime,
    owner_session_id: str | None = None,
    require_new_delivery: bool = False,
) -> str:
    """Send one notice to whoever owns the lane; report what delivery did.

    ``""`` means nobody was addressable and ``"undelivered"`` means the
    envelope was accepted but has not reached the recipient yet.
    An ejection requires new delivery: an acknowledged dedupe refuses by
    name so the observer retains its landing marker. Completion notices may
    settle from their existing acknowledgement. The body is
    composed from the resolved route, because a notice to a lane whose holder
    is gone has to say something different from one the holder will read.
    """
    session_id, actor_id, route = resolve_lane_recipient(
        conn,
        item_id=item_id,
        project_id=project_id,
        owner_session_id=owner_session_id,
    )
    if not session_id:
        return ""
    created = send_message(
        conn,
        actor_id=actor_id,
        sender_session_id=None,
        selector=RecipientSelector(session_ids=[session_id]),
        body=body_for_route(route),
        idempotency_key=idempotency_key,
        idempotency_intent_only=True,
        now=now,
        commit=False,
    )
    message_id = str(created["message_id"])
    delivered = _receipt_delivered(
        conn,
        message_id,
        session_id,
        reject_acknowledged=require_new_delivery and bool(created.get("deduplicated")),
    )
    mark_explicit_stopped_wake(conn, message_id=message_id, session_id=session_id)
    if not delivered:
        return "undelivered"
    return "delivered"


__all__ = [
    "HOLDER",
    "addressable_items",
    "STEERING",
    "notice_already_sent",
    "landing_message",
    "push_notice",
    "resolve_lane_recipient",
]
