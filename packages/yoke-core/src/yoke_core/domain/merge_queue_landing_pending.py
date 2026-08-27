"""Durable merge-queue handoff and the control-plane landing observer."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Callable, Iterable

from yoke_contracts.api.function_call import TargetRef
from yoke_contracts.item_ref import format_item_ref
from yoke_contracts.session_control.models import RecipientSelector
from yoke_core.api.service_client_structured_api_adapter import call_dispatcher
from yoke_core.domain import db_backend
from yoke_core.domain.schema_common import _column_exists
from yoke_core.domain.session_message_service import send_message
from yoke_core.domain.session_message_types import row_dict, timestamp, utc_now
from yoke_core.domain.work_claim_targets import scope_int_sql
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
        "p.public_item_prefix FROM items i JOIN projects p ON p.id=i.project_id "
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
        "WHERE wc.released_at IS NULL AND hs.ended_at IS NULL "
        "AND hs.terminated_at IS NULL "
    )
    row = conn.execute(
        "SELECT wc.session_id, hs.actor_id"
        + common
        + f"AND wc.target_kind='item' AND {item_scope}={marker} "
        "ORDER BY wc.id DESC LIMIT 1",
        (item_id,),
    ).fetchone()
    route = "holder"
    if row is None:
        row = conn.execute(
            "SELECT wc.session_id, hs.actor_id"
            + common
            + f"AND wc.target_kind='steering' AND {project_scope}={marker} "
            "ORDER BY wc.id DESC LIMIT 1",
            (project_id,),
        ).fetchone()
        route = "steering"
    if row is None or row[1] is None:
        return "", 0, ""
    return str(row[0]), int(row[1]), route


def _message_body(item_ref: str, pr_number: str, route: str) -> str:
    if route == "holder":
        return (
            f"Landing complete for {item_ref} (pull request #{pr_number}) — "
            "run close-out by re-entering the same `yoke merge item` command "
            "with its --result and --verification evidence."
        )
    return (
        f"Landing complete for {item_ref} (pull request #{pr_number}), but its "
        "claim holder is gone. Route normal starvation/restaffing so "
        "`yoke merge item` can close the item out."
    )


def observe_pending_landings(
    conn: Any,
    project_ids: Iterable[int],
    *,
    now: datetime | None = None,
    read_state: Callable[..., Any] = read_pr_landing_state,
) -> dict[str, int]:
    """Notify one live owner exactly once after each pending PR lands."""
    current = now or utc_now()
    current_text = timestamp(current)
    rows = _pending_rows(conn, project_ids)
    conn.commit()
    result = {"checked": len(rows), "landed": 0, "notified": 0, "unrouted": 0}
    marker = _p(conn)
    for row in rows:
        pr_number = str(row["merge_queue_pr_number"])
        state, error = read_state(
            MergeContext(
                args=MergeArgs(branch="", target="main"),
                repo_root="",
                project=str(row["slug"]),
            ),
            pr_number,
        )
        if error or state is None or not bool(state.merged):
            continue
        cursor = conn.execute(
            "UPDATE items SET merge_queue_landed_at=COALESCE("
            f"merge_queue_landed_at, {marker}) WHERE id={marker} "
            f"AND merge_queue_pr_number={marker} "
            "AND merge_queue_notified_at IS NULL AND merged_at IS NULL",
            (current_text, int(row["id"]), pr_number),
        )
        if not cursor.rowcount:
            conn.rollback()
            continue
        result["landed"] += 1
        session_id, actor_id, route = _recipient(
            conn,
            item_id=int(row["id"]),
            project_id=int(row["project_id"]),
        )
        if not session_id:
            conn.commit()
            result["unrouted"] += 1
            continue
        item_ref = format_item_ref(
            row["slug"],
            row["public_item_prefix"],
            row["project_sequence"],
            item_id=int(row["id"]),
        )
        try:
            send_message(
                conn,
                actor_id=actor_id,
                sender_session_id=None,
                selector=RecipientSelector(session_ids=[session_id]),
                body=_message_body(item_ref, pr_number, route),
                idempotency_key=f"merge-queue-landed:{row['id']}:{pr_number}",
                now=current,
                commit=False,
            )
            conn.execute(
                f"UPDATE items SET merge_queue_notified_at={marker} "
                f"WHERE id={marker} AND merge_queue_pr_number={marker} "
                "AND merge_queue_notified_at IS NULL",
                (current_text, int(row["id"]), pr_number),
            )
            conn.commit()
            result["notified"] += 1
        except Exception:
            conn.rollback()
    return result


__all__ = [
    "clear_landing_pending",
    "mark_landing_pending",
    "observe_pending_landings",
]
