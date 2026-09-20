"""Reach whoever a deployment run needs, on one delivery contract.

A run-scoped stop has no single member item to address: the recipient is
the project's deploy-lock driver, the same "one driver per project" concept
:mod:`yoke_core.domain.deploy_lock` already serializes run creation and
execution against. When no session holds that lock -- the ordinary case for
a run whose driver exited at its own gate and released it -- the project's
steering seat answers instead.

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

from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any, Optional

from yoke_core.domain.merge_queue_landing_notice import STEERING

#: The project's deploy-lock holder answered for a run-scoped wait. Its
#: counterpart routes -- an item's claim holder, and the steering seat that
#: answers when nobody holds the role -- are named by
#: :mod:`yoke_core.domain.merge_queue_landing_notice`, whose recipient
#: primitives this mirrors, so ``STEERING`` is read from there rather than
#: restated.
DRIVER = "driver"


def resolve_run_driver_recipient(
    conn: Any, *, project_id: int
) -> tuple[str, int, str]:
    """The project's live deploy-lock holder, else its undocumented steering seat.

    ``("", 0, "")`` means nobody is addressable at all.
    """
    from yoke_core.domain.coordination_claims import active_claim
    from yoke_core.domain.project_identity import resolve_project
    from yoke_core.domain.steering_scope_coverage import PROJECT_KEY, covering_seat
    from yoke_core.domain.work_claim_targets import make_deploy_serialization_target

    identity = resolve_project(conn, project_id, required=False)
    if identity is not None:
        claim = active_claim(
            conn, make_deploy_serialization_target(identity.id, identity.slug)
        )
        if claim is not None and claim.actor_id is not None:
            return claim.session_id, int(claim.actor_id), DRIVER
    seat = covering_seat(conn, {PROJECT_KEY: int(project_id)})
    if seat is None or seat.get("actor_id") is None:
        return "", 0, ""
    return str(seat["session_id"]), int(seat["actor_id"]), STEERING


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
    project_id: int,
    body_for_route: Callable[[str], str],
    idempotency_key: str,
    now: Optional[datetime] = None,
) -> str:
    """Reach whoever is driving a project's release, and say whether it landed.

    The run-scoped counterpart to
    :func:`merge_queue_landing_notice.push_notice`, with the same return
    contract: ``""`` nobody addressable, ``"undelivered"`` queued but not
    yet reached, ``"delivered"`` reached the recipient. ``body_for_route``
    is passed the route that found the recipient so the body can name who
    it reached.
    """
    session_id, actor_id, route = resolve_run_driver_recipient(
        conn, project_id=project_id
    )
    if not session_id:
        return ""
    return _deliver(
        conn,
        session_id=session_id,
        actor_id=actor_id,
        body=body_for_route(route),
        idempotency_key=idempotency_key,
        now=now or datetime.now(timezone.utc),
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
        now=now or datetime.now(timezone.utc),
    )


__all__ = [
    "DRIVER",
    "push_member_notice",
    "push_run_scoped_notice",
    "resolve_run_driver_recipient",
]
