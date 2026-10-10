"""Reach whoever a deployment run needs, on one delivery contract.

A run-scoped stop has no single member item to address: the recipient is
the run's live driver, the session attached to it through
:mod:`yoke_core.domain.deployment_run_driver_attachment`. When no driver is
attached -- the ordinary case for a run whose driver exited at its own gate
-- the project's steering seat answers instead.

Two kinds of run-scoped wait share that recipient: a run-scoped QA stage
owed evidence (:mod:`yoke_core.domain.deployment_qa_stage_wake`) and a stage
approval whose answer is recorded and needs the runner re-entered
(:mod:`yoke_core.domain.deployment_stage_decision_effect`). A third caller
addresses a different recipient on the same send: a member whose own
item-scoped QA has been accepted
(:mod:`yoke_core.domain.deployment_qa_member_acceptance_notice`), which
reaches that item's claim holder (or the project's steering seat when
nobody holds the claim). The delivery contract is identical, so it lives
here once rather than in whichever module needed it first.

The steering fallback reuses :mod:`yoke_core.domain.steering_scope_coverage`'s
scope-aware seat rule rather than picking whichever steering claim on the
project is newest -- a project can carry more than one live steering seat at
once, each scoped to a different strategy document, and run-scoped work
carries no document of its own to disambiguate among them. Addressing the
project's plain, undocumented scope only ever matches a seat covering
unlinked work, so a project whose only live seat is narrowed to one document
correctly finds nobody rather than guessing.
"""

from __future__ import annotations

from yoke_contracts.timestamps import parse_instant, utc_now

from collections.abc import Callable
from datetime import datetime
from typing import Any, Optional

from yoke_core.domain.merge_queue_landing_notice import STEERING

#: The run's live driver answered for a run-scoped wait. Its
#: counterpart routes -- an item's claim holder, and the steering seat that
#: answers when nobody holds the role -- are named by
#: :mod:`yoke_core.domain.merge_queue_landing_notice`, whose recipient
#: primitives this mirrors, so ``STEERING`` is read from there rather than
#: restated.
DRIVER = "driver"


def resolve_run_driver_recipient(
    conn: Any, *, run_id: str, project_id: int
) -> tuple[str, int, str]:
    """The run's live driver, else the project's undocumented steering seat.

    ``("", 0, "")`` means nobody is addressable at all.
    """
    from yoke_core.domain.deployment_run_driver_attachment import (
        live_attachment_for_run,
    )
    from yoke_core.domain.steering_scope_coverage import PROJECT_KEY, covering_seat

    driver = live_attachment_for_run(conn, run_id_value=str(run_id), now=utc_now())
    if driver is not None and driver.session_id:
        actor_id = _session_actor(conn, driver.session_id)
        if actor_id is not None:
            return driver.session_id, actor_id, DRIVER
    seat = covering_seat(conn, {PROJECT_KEY: int(project_id)})
    if seat is None or seat.get("actor_id") is None:
        return "", 0, ""
    return str(seat["session_id"]), int(seat["actor_id"]), STEERING


def _session_actor(conn: Any, session_id: str) -> Optional[int]:
    from yoke_core.domain import db_backend

    marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
    row = conn.execute(
        f"SELECT actor_id FROM harness_sessions WHERE session_id={marker}",
        (session_id,),
    ).fetchone()
    if row is None:
        return None
    value = row["actor_id"] if hasattr(row, "keys") else row[0]
    return int(value) if value is not None else None


def _receipt_delivered(conn: Any, message_id: str, session_id: str) -> bool:
    """True when the recipient actually received the envelope, not merely queued."""
    from yoke_core.domain.session_message_store import message_details

    details = message_details(conn, message_id)
    for recipient in details.get("recipients") or ():
        if str(recipient.get("session_id") or "") != session_id:
            continue
        if recipient.get("last_injected_at") or recipient.get("acknowledged_at"):
            return True
        if int(recipient.get("injection_count") or 0) > 0:
            return True
        return str(recipient.get("state") or "") in {"injected", "acknowledged"}
    return False


def _deliver(
    conn: Any,
    *,
    session_id: str,
    actor_id: int,
    body: str,
    idempotency_key: str,
    now: datetime,
) -> str:
    """Queue one envelope and say whether it reached ``session_id``."""
    from yoke_contracts.session_control.models import RecipientSelector
    from yoke_core.domain.session_explicit_wake import mark_explicit_stopped_wake
    from yoke_core.domain.session_message_service import send_message

    created = send_message(
        conn,
        actor_id=actor_id,
        sender_session_id=None,
        selector=RecipientSelector(session_ids=[session_id]),
        body=body,
        idempotency_key=idempotency_key,
        idempotency_intent_only=True,
        now=now,
        commit=False,
    )
    message_id = str(created["message_id"])
    mark_explicit_stopped_wake(conn, message_id=message_id, session_id=session_id)
    return (
        "delivered"
        if _receipt_delivered(conn, message_id, session_id)
        else "undelivered"
    )


def push_run_scoped_notice(
    conn: Any,
    *,
    run_id: str,
    project_id: int,
    body_for_route: Callable[[str], str],
    idempotency_key: str,
    now: Optional[datetime] = None,
) -> str:
    """Reach whoever is driving *run_id*, and say whether it landed.

    The run-scoped counterpart to
    :func:`merge_queue_landing_notice.push_notice`, with the same return
    contract: ``""`` nobody addressable, ``"undelivered"`` queued but not
    yet reached, ``"delivered"`` reached the recipient. ``body_for_route``
    is passed the route that found the recipient so the body can name who
    it reached.
    """
    now = parse_instant(utc_now() if now is None else now)
    session_id, actor_id, route = resolve_run_driver_recipient(
        conn, run_id=run_id, project_id=project_id
    )
    if not session_id:
        return ""
    return _deliver(
        conn,
        session_id=session_id,
        actor_id=actor_id,
        body=body_for_route(route),
        idempotency_key=idempotency_key,
        now=now,
    )


def push_member_notice(
    conn: Any,
    *,
    item_id: int,
    project_id: int,
    body_for_route: Callable[[str], str],
    idempotency_key: str,
    now: Optional[datetime] = None,
) -> str:
    """Reach the item's claim holder (or steering), on this same send.

    The member-recipient counterpart to :func:`push_run_scoped_notice`.
    Recipient resolution is
    :func:`merge_queue_landing_notice.resolve_lane_recipient` -- the
    release-wait owner's claim holder, else the project's steering seat --
    so a parked owner and an abandoned lane are the same two answers every
    other per-item wake already uses. The envelope still goes through this
    module's delivery contract rather than a second wake path.
    """
    now = parse_instant(utc_now() if now is None else now)
    from yoke_core.domain.merge_queue_landing_notice import resolve_lane_recipient

    session_id, actor_id, route = resolve_lane_recipient(
        conn, item_id=item_id, project_id=project_id
    )
    if not session_id:
        return ""
    return _deliver(
        conn,
        session_id=session_id,
        actor_id=actor_id,
        body=body_for_route(route),
        idempotency_key=idempotency_key,
        now=now,
    )


__all__ = [
    "DRIVER",
    "push_member_notice",
    "push_run_scoped_notice",
    "resolve_run_driver_recipient",
]
