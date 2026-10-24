"""Tell each dependent's holder that a blocker it waited on was cancelled.

Cancelling an item removes every dependency edge that names it as the
blocker, because a cancelled item can never satisfy one. The dependent's
holder still has to hear about it: the work it waited on may be needed
under the replacement item, and only the holder can decide whether to add
that edge. The notice names the cancelled blocker, the replacement if any,
and the command to depend on it; edges are never moved automatically. It
travels the same lane routing landing notices use, so a parked holder is
woken, but only a live holder is told: a dependent nobody holds has nobody
to decide for it yet.
"""

from __future__ import annotations

from typing import Any, Optional

from yoke_contracts.timestamps import utc_now
from yoke_core.domain.merge_queue_landing_notice import (
    HOLDER,
    push_notice,
    resolve_lane_recipient,
)

#: The dependent has no live claim holder, so nobody was told.
NO_LIVE_HOLDER = "no_live_holder"

#: The session that cancelled the blocker holds the dependent itself.
CANCELLING_SESSION = "cancelling_session"


def cancelled_blocker_key(blocker_id: int, dependent_id: int) -> str:
    """One notice per dependent per cancelled blocker, however many edges."""
    return f"cancelled-blocker:{int(blocker_id)}:{int(dependent_id)}"


def cancelled_blocker_message(
    *, blocker_ref: str, dependent_ref: str, reason: str, replacement_ref: str
) -> str:
    """Name the cancelled blocker, the removed edge and the replacement."""
    lead = (
        f"{blocker_ref} was cancelled ({reason}). {dependent_ref} depended on "
        "it, so that dependency was removed."
    )
    if replacement_ref:
        return (
            f"{lead} Its replacement is {replacement_ref}. If {dependent_ref} "
            "still needs that work, run `yoke items dependency add "
            f"{dependent_ref} {replacement_ref} <source> --rationale TEXT`."
        )
    return (
        f"{lead} No replacement was named. If {dependent_ref} still needs that "
        "work, find or file the item that will do it and add a dependency on "
        "it with `yoke items dependency add`."
    )


def _notify(
    conn: Any,
    *,
    blocker_id: int,
    blocker_ref: str,
    reason: str,
    replacement_ref: str,
    dependents: list[tuple[int, str, int]],
    canceller_session_id: Optional[str],
) -> list[dict[str, str]]:
    now = utc_now()
    reports = []
    for dependent_id, dependent_ref, project_id in dependents:
        session_id, _, route = resolve_lane_recipient(
            conn, item_id=dependent_id, project_id=project_id
        )
        report = {"dependent_item": dependent_ref, "holder_session_id": ""}
        if not session_id or route != HOLDER:
            reports.append({**report, "delivery": NO_LIVE_HOLDER})
            continue
        report["holder_session_id"] = session_id
        if session_id == canceller_session_id:
            reports.append({**report, "delivery": CANCELLING_SESSION})
            continue
        body = cancelled_blocker_message(
            blocker_ref=blocker_ref,
            dependent_ref=dependent_ref,
            reason=reason,
            replacement_ref=replacement_ref,
        )
        delivery = push_notice(
            conn,
            item_id=dependent_id,
            project_id=project_id,
            body_for_route=lambda _route, body=body: body,
            idempotency_key=cancelled_blocker_key(blocker_id, dependent_id),
            now=now,
        )
        reports.append({**report, "delivery": delivery})
    return reports


def notify_after_cancel(
    conn: Any,
    *,
    blocker_id: int,
    blocker_ref: str,
    reason: str,
    replacement_ref: Optional[str],
    dependents: list[tuple[int, str, int]],
    canceller_session_id: Optional[str],
) -> tuple[list[dict[str, str]], str]:
    """Notify in its own transaction after the cancel committed.

    ``dependents`` holds ``(item_id, public_ref, project_id)``. Each report
    carries ``delivery``: :func:`push_notice`'s ``delivered`` or
    ``undelivered``, or :data:`NO_LIVE_HOLDER` / :data:`CANCELLING_SESSION`
    when no message was sent. A failure rolls back only the notices and
    returns a named advisory with its recovery; the cancel stays durable.
    """
    if not dependents:
        return [], ""
    try:
        reports = _notify(
            conn,
            blocker_id=blocker_id,
            blocker_ref=blocker_ref,
            reason=reason,
            replacement_ref=replacement_ref or "",
            dependents=dependents,
            canceller_session_id=canceller_session_id,
        )
        conn.commit()
    except Exception as exc:  # noqa: BLE001 - notices never reverse the cancel
        conn.rollback()
        refs = ", ".join(ref for _, ref, _ in dependents)
        return [], (
            f"cancelled_blocker_notice_deferred: the holders of {refs} were not "
            f"told that {blocker_ref} was cancelled ({exc}). Tell each one "
            "with `printf %s TEXT | yoke say --stdin --item PREFIX-N`, naming "
            "the replacement they may depend on."
        )
    return reports, ""


__all__ = [
    "CANCELLING_SESSION",
    "NO_LIVE_HOLDER",
    "cancelled_blocker_key",
    "cancelled_blocker_message",
    "notify_after_cancel",
]
