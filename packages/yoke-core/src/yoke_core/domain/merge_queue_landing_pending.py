"""Durable merge-queue handoff and the control-plane landing observer."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Callable, Iterable

from yoke_contracts.api.function_call import TargetRef
from yoke_contracts.public_ref import format_item_ref
from yoke_contracts.session_control.models import RecipientSelector
from yoke_core.api.service_client_structured_api_adapter import call_dispatcher
from yoke_core.domain import db_backend
from yoke_core.domain.schema_common import _column_exists
from yoke_core.domain.merge_queue_enqueue_verification import read_landing
from yoke_core.domain.merge_queue_landing_observation import (
    EJECTED,
    LANDED,
    classify_pending_landing,
    ejection_message,
)
from yoke_core.domain.session_explicit_wake import mark_explicit_stopped_wake
from yoke_core.domain.session_message_service import send_message
from yoke_core.domain.session_message_store import message_details
from yoke_core.domain.session_message_types import row_dict, timestamp, utc_now
from yoke_core.domain.work_claim_targets import scope_int_sql
from yoke_core.engines.merge_worktree_pr_check_runs import (
    read_required_checks,
)
from yoke_core.engines.merge_worktree_pr_membership import (
    read_pr_queue_membership,
)
from yoke_core.engines.merge_worktree_pr_queue import read_pr_landing_state
from yoke_core.engines.merge_worktree_prepare import MergeArgs, MergeContext


def _response_error(response: Any, fallback: str) -> str:
    error = getattr(response, "error", None)
    return str(getattr(error, "message", None) or fallback)


def mark_landing_pending(
    item_id: int,
    pr_number: str,
    *,
    dispatch: Callable[..., Any] = call_dispatcher,
    now: datetime | None = None,
) -> tuple[str, str]:
    """Persist queue admission, returning ``(enqueued_at, error)``."""
    enqueued_at = timestamp(now or utc_now())
    response = dispatch(
        function_id="merge_queue.landing_pending.mark",
        target=TargetRef(kind="item", item_id=int(item_id)),
        payload={"pr_number": str(pr_number), "enqueued_at": enqueued_at},
    )
    if not getattr(response, "success", False):
        return "", _response_error(response, "landing marker write failed")
    result = getattr(response, "result", None) or {}
    return str(result.get("enqueued_at") or enqueued_at), ""


def clear_landing_pending(
    item_id: int,
    *,
    dispatch: Callable[..., Any] = call_dispatcher,
) -> str:
    """Clear a marker after close-out; return a warning on failure."""
    response = dispatch(
        function_id="merge_queue.landing_pending.clear",
        target=TargetRef(kind="item", item_id=int(item_id)),
        payload={},
    )
    if getattr(response, "success", False):
        return ""
    return _response_error(response, "landing marker clear failed")


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _pending_rows(conn: Any, project_ids: Iterable[int]) -> list[dict[str, Any]]:
    projects = tuple(sorted({int(value) for value in project_ids}))
    if not projects or not _column_exists(conn, "items", "merge_queue_enqueued_at"):
        return []
    marker = _p(conn)
    slots = ",".join(marker for _ in projects)
    rows = conn.execute(
        "SELECT i.id, i.project_id, i.project_sequence, i.merge_queue_pr_number, "
        "i.merge_queue_enqueued_at, i.merge_queue_landed_at, p.slug, "
        "p.public_item_prefix, p.default_branch "
        "FROM items i JOIN projects p ON p.id=i.project_id "
        f"WHERE i.project_id IN ({slots}) AND i.merge_queue_enqueued_at IS NOT NULL "
        "AND i.merge_queue_pr_number IS NOT NULL "
        "AND i.merge_queue_notified_at IS NULL AND i.merged_at IS NULL "
        "AND i.status NOT IN ('done','cancelled') ORDER BY i.id",
        projects,
    ).fetchall()
    return [row_dict(row) for row in rows]


def _recipient(conn: Any, *, item_id: int, project_id: int) -> tuple[str, int, str]:
    marker = _p(conn)
    item_scope = scope_int_sql(conn, "wc.scope", "item_id")
    project_scope = scope_int_sql(conn, "wc.scope", "project_id")
    common = (
        " FROM work_claims wc JOIN harness_sessions hs ON hs.session_id=wc.session_id "
        "WHERE wc.released_at IS NULL AND hs.terminated_at IS NULL "
    )
    row = conn.execute(
        "SELECT wc.session_id, hs.actor_id"
        + common
        +         f"AND wc.target_kind='item' AND {item_scope}={marker} "
        "ORDER BY CASE WHEN hs.ended_at IS NULL THEN 0 ELSE 1 END, wc.id DESC "
        "LIMIT 1",
        (item_id,),
    ).fetchone()
    route = "holder"
    if row is None:
        row = conn.execute(
            "SELECT wc.session_id, hs.actor_id"
            + common
            +         f"AND wc.target_kind='steering' AND {project_scope}={marker} "
        "ORDER BY CASE WHEN hs.ended_at IS NULL THEN 0 ELSE 1 END, wc.id DESC "
        "LIMIT 1",
            (project_id,),
        ).fetchone()
        route = "steering"
    if row is None or row[1] is None:
        return "", 0, ""
    return str(row[0]), int(row[1]), route


def _message_body(public_ref: str, pr_number: str, route: str) -> str:
    if route == "holder":
        return (
            f"Landing complete for {public_ref} (pull request #{pr_number}) — "
            "run close-out by re-entering the same `yoke merge item` command "
            "with its --result and --verification evidence."
        )
    return (
        f"Landing complete for {public_ref} (pull request #{pr_number}), but its "
        "claim holder is gone. Route normal starvation/restaffing so "
        "`yoke merge item` can close the item out."
    )


def _landing_receipt_delivered(conn: Any, message_id: str, session_id: str) -> bool:
    """True when the recipient actually received the envelope, not merely queued."""
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


def _push_notice(
    conn: Any,
    row: dict[str, Any],
    *,
    body_for_route: Callable[[str], str],
    idempotency_key: str,
    now: datetime,
) -> str:
    """Send one notice to whoever owns the lane; report what delivery did.

    ``""`` means nobody was addressable and ``"undelivered"`` means the
    envelope exists but has not reached the recipient yet — both leave the
    marker alone so the next poll tries again. The body is composed from
    the resolved route, because a notice to a lane whose holder is gone
    has to say something different from one the holder will read.
    """
    session_id, actor_id, route = _recipient(
        conn,
        item_id=int(row["id"]),
        project_id=int(row["project_id"]),
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
        now=now,
        commit=False,
    )
    message_id = str(created["message_id"])
    mark_explicit_stopped_wake(conn, message_id=message_id, session_id=session_id)
    if not _landing_receipt_delivered(conn, message_id, session_id):
        return "undelivered"
    return "delivered"


def observe_pending_landings(
    conn: Any,
    project_ids: Iterable[int],
    *,
    now: datetime | None = None,
    read_state: Callable[..., Any] = read_pr_landing_state,
    read_membership: Callable[..., Any] = read_pr_queue_membership,
    read_checks: Callable[..., Any] = read_required_checks,
) -> dict[str, int]:
    """Report every pending landing that resolved, and how it resolved.

    A landing that merged notifies its holder to close out. A pull request
    GitHub has dropped notifies the holder to rebase and re-gate, and its
    handoff marker is cleared, because there is no queued landing left to
    wait for. Only a pull request the queue still holds stays silent.
    """
    current = now or utc_now()
    current_text = timestamp(current)
    rows = _pending_rows(conn, project_ids)
    conn.commit()
    result = {
        "checked": len(rows),
        "landed": 0,
        "notified": 0,
        "ejected": 0,
        "unrouted": 0,
    }
    marker = _p(conn)
    for row in rows:
        pr_number = str(row["merge_queue_pr_number"])
        target = str(row.get("default_branch") or "main")
        ctx = MergeContext(
            args=MergeArgs(branch="", target=target),
            repo_root="",
            project=str(row["slug"]),
        )
        readback = read_landing(
            ctx,
            pr_number,
            read_state=read_state,
            read_membership=read_membership,
            read_checks=read_checks,
        )
        if readback.state_error:
            continue
        observation = classify_pending_landing(readback, target=target)
        if observation.kind not in (LANDED, EJECTED):
            continue
        public_ref = format_item_ref(
            row["slug"],
            row["public_item_prefix"],
            row["project_sequence"],
            item_id=int(row["id"]),
        )
        try:
            if observation.kind == EJECTED:
                delivery = _push_notice(
                    conn,
                    row,
                    body_for_route=lambda route: ejection_message(
                        public_ref, pr_number, observation, route
                    ),
                    idempotency_key=f"merge-queue-ejected:{row['id']}:{pr_number}",
                    now=current,
                )
                if not delivery:
                    conn.commit()
                    result["unrouted"] += 1
                    continue
                if delivery == "delivered":
                    # The queue admission is what ended, so that is what is
                    # cleared: the item stops being reported as a pending
                    # landing and a fresh `yoke merge item` re-arms it. The
                    # pull request number stays, because one observation
                    # cannot separate an ejection from the seconds in which
                    # a successful train has cleared the slot and the merge
                    # has not surfaced — and a re-entry that turns out to
                    # be converging on a merge still needs that number to
                    # find the merge-group run its evidence is built on.
                    conn.execute(
                        f"UPDATE items SET merge_queue_enqueued_at=NULL "
                        f"WHERE id={marker} AND merge_queue_pr_number={marker}",
                        (int(row["id"]), pr_number),
                    )
                    result["ejected"] += 1
                conn.commit()
                continue
            if not str(row.get("merge_queue_landed_at") or ""):
                cursor = conn.execute(
                    f"UPDATE items SET merge_queue_landed_at={marker} "
                    f"WHERE id={marker} AND merge_queue_pr_number={marker} "
                    "AND merge_queue_landed_at IS NULL AND merged_at IS NULL",
                    (current_text, int(row["id"]), pr_number),
                )
                if not cursor.rowcount:
                    conn.rollback()
                    continue
                result["landed"] += 1
            delivery = _push_notice(
                conn,
                row,
                body_for_route=lambda route: _message_body(
                    public_ref, pr_number, route
                ),
                idempotency_key=f"merge-queue-landed:{row['id']}:{pr_number}",
                now=current,
            )
            if not delivery:
                conn.commit()
                result["unrouted"] += 1
                continue
            if delivery == "delivered":
                conn.execute(
                    f"UPDATE items SET merge_queue_notified_at={marker} "
                    f"WHERE id={marker} AND merge_queue_pr_number={marker} "
                    "AND merge_queue_notified_at IS NULL",
                    (current_text, int(row["id"]), pr_number),
                )
                result["notified"] += 1
            conn.commit()
        except Exception:
            conn.rollback()
    return result


__all__ = [
    "clear_landing_pending",
    "mark_landing_pending",
    "observe_pending_landings",
]
