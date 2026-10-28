"""Resume the owner of a scoped capture for independent QA review.

A finished walk wakes its owner through the item-QA route. A walk stopped by
an abort or error keeps a pending bundle for its completed captures; that
review wakes the capture session while it is live, and otherwise the member
the execution answers for, so the review never sits unowned. A plan group
answers no member: its review reaches the run's driver, else the session
that started the run, else steering.
"""

from __future__ import annotations

import shlex
from yoke_contracts.timestamps import utc_now
from typing import Any, Mapping

from yoke_core.domain.merge_queue_landing_notice import HOLDER, push_notice
from yoke_core.domain.project_identity import render_item_ref
from yoke_core.domain.qa_plan_execution_store import marker
from yoke_core.domain.qa_plan_settled_review import (
    REVIEW_WAKE_PREFIX,
    execution_has_persisted_verdict_batch,
)


def _group_execution(execution: Mapping[str, Any]) -> bool:
    """Whether this execution walks an item-qa plan group (memberless rows)."""
    from yoke_core.domain.deployment_qa_plan_groups import group_marker

    return not execution.get("deployment_member_item_id") and (
        group_marker(execution.get("execution_target")) is not None
    )


def _notify_group_review(
    conn: Any, execution: Mapping[str, Any], body_for_route, idempotency_key: str
) -> str:
    """A plan group answers no member: its review reaches the run's recipient."""
    from yoke_core.domain.deployment_run_driver_notice import push_run_scoped_notice

    run_id = str(execution["deployment_run_id"])
    row = conn.execute(
        f"SELECT project_id FROM deployment_runs WHERE id={marker(conn)}", (run_id,)
    ).fetchone()
    if row is None:
        return ""
    return push_run_scoped_notice(
        conn,
        run_id=run_id,
        project_id=int(row[0]),
        body_for_route=body_for_route,
        idempotency_key=idempotency_key,
        now=utc_now(),
    )


def notify_scoped_agent_review(conn: Any, execution: Mapping[str, Any]) -> str:
    """Use the item-QA wake route, with a distinct notice for this execution.

    The earlier stage wait may already be delivered. Its key cannot also
    identify the later review continuation, which is new work for the owner.
    """
    run_id = execution.get("deployment_run_id")
    stage = execution.get("deployment_stage")
    if not run_id or not stage:
        return ""
    if _group_execution(execution):
        return _notify_finished_group(conn, execution)
    member_id = execution.get("deployment_member_item_id")
    if not member_id:
        return ""
    p = marker(conn)
    row = conn.execute(
        "SELECT i.project_id, p.slug FROM items i "
        f"JOIN projects p ON p.id=i.project_id WHERE i.id={p}",
        (int(member_id),),
    ).fetchone()
    if row is None:
        return ""
    item_ref = render_item_ref(conn, int(member_id))
    command = shlex.join(
        [
            "yoke",
            "watch",
            "qa-plan",
            "--",
            "--item",
            item_ref,
            "--project",
            str(row[1]),
            "--resume-execution-id",
            str(execution["id"]),
        ]
    )
    execution_id = str(execution["id"])
    if execution_has_persisted_verdict_batch(conn, execution_id):
        return ""
    owner = str(execution.get("session_id") or "")

    def body_for_route(route: str) -> str:
        recovery = (
            f"Owning session {owner}: re-enter `{command}` now. The command "
            "reprints the pending bundle without recapturing; dispatch its "
            "typed reviewer contract and submit the complete verdict batch."
            if route == HOLDER
            else f"Owning session {owner or 'unrecorded'} is gone. Route normal "
            "idle/gone-holder starvation and restaffing for this member; the "
            f"scoped re-entry command is `{command}`."
        )
        return (
            f"Scoped QA capture for {item_ref} on deployment run {run_id}, "
            f"stage {stage!r}, execution {execution_id} reached "
            f"{execution['state']}. Follow the returned walk/review contract; no QA "
            f"verdict exists yet. {recovery}"
        )

    return push_notice(
        conn,
        item_id=int(member_id),
        project_id=int(row[0]),
        owner_session_id=owner,
        body_for_route=body_for_route,
        idempotency_key=f"{REVIEW_WAKE_PREFIX}{execution_id}",
        now=utc_now(),
    )


def _notify_finished_group(conn: Any, execution: Mapping[str, Any]) -> str:
    execution_id = str(execution["id"])
    if execution_has_persisted_verdict_batch(conn, execution_id):
        return ""
    command = shlex.join(
        ["yoke", "watch", "qa-plan", "--", "--resume-execution-id", execution_id]
    )
    owner = str(execution.get("session_id") or "unrecorded")
    body = (
        f"Scoped QA capture for the plan group on deployment run "
        f"{execution['deployment_run_id']}, stage {execution['deployment_stage']!r}, "
        f"execution {execution_id} reached {execution['state']}. No QA verdict "
        f"exists yet. Capture session {owner} (or whoever this reaches when it is "
        f"gone): re-enter `{command}`, which reprints the pending bundle without "
        "recapturing; dispatch its typed reviewer contract and submit the "
        "complete verdict batch."
    )
    return _notify_group_review(
        conn, execution, lambda _route: body, f"{REVIEW_WAKE_PREFIX}{execution_id}"
    )


def _project_id(conn: Any, item_id: int) -> int | None:
    row = conn.execute(
        f"SELECT project_id FROM items WHERE id={marker(conn)}", (int(item_id),)
    ).fetchone()
    return int(row[0]) if row is not None else None


def _session_live(conn: Any, session_id: str) -> bool:
    if not session_id:
        return False
    row = conn.execute(
        "SELECT 1 FROM harness_sessions WHERE session_id="
        f"{marker(conn)} AND ended_at IS NULL AND terminated_at IS NULL",
        (session_id,),
    ).fetchone()
    return row is not None


def notify_stopped_capture_review(
    conn: Any, execution: Mapping[str, Any], *, bundle_id: str
) -> list[str]:
    """Hand a stopped walk's pending review to its owner, else its waiters.

    Writes without committing, inside the caller's settlement transaction.
    Returns one delivery result per notice (``""`` = nobody addressable). A
    refused send never blocks the stop: it prints a named line, and the stage
    keeps naming the review in its own blocker.
    """
    from yoke_core.domain.db_savepoint import savepoint
    from yoke_core.domain.session_message_types import SessionMessageError

    try:
        with savepoint(conn, "_yoke_stopped_review_notice", owns=False):
            return _notify_stopped(conn, execution, bundle_id=bundle_id)
    except SessionMessageError as exc:
        print(
            f"stopped_review_unaddressed: execution {execution['id']} stopped "
            f"as {execution['state']} with review bundle {bundle_id} pending; "
            f"its notice was refused ({exc}). Run the stage's named "
            "review-begin command, or staff a member who can."
        )
        return []


def _notify_stopped(
    conn: Any, execution: Mapping[str, Any], *, bundle_id: str
) -> list[str]:
    from yoke_core.domain.qa_pending_agent_review import PendingAgentReview
    from yoke_core.domain.qa_pending_agent_review import review_scope_flag

    execution_id = str(execution["id"])
    if execution_has_persisted_verdict_batch(conn, execution_id):
        return []
    run_id = execution.get("deployment_run_id")
    group = bool(run_id) and _group_execution(execution)
    member = (
        execution.get("deployment_member_item_id") if run_id else execution.get("item_id")
    )
    members = [int(member)] if member else []
    if not members and not group:
        return []
    owner = str(execution.get("session_id") or "")
    pending = PendingAgentReview(
        execution_id=execution_id,
        bundle_id=bundle_id,
        session_id=owner,
        state=str(execution["state"]),
        scope_flag=review_scope_flag(conn, execution),
    )
    where = (
        f"deployment run {run_id}, stage {execution.get('deployment_stage')!r}"
        if run_id
        else "its item transition"
    )
    stopped = (
        f"QA plan execution {execution_id} ({where}) stopped as "
        f"{execution['state']} with completed captures awaiting independent "
        f"review in bundle {bundle_id}. No QA verdict exists for them yet, and "
        "re-running `yoke qa plan run` cannot supply one."
    )
    now = utc_now()
    owner_live = _session_live(conn, owner)
    if group:
        body = (
            f"{stopped} Owning session {owner}: {pending.next_action()}."
            if owner_live
            else f"{stopped} Its capture session {owner or 'unrecorded'} has "
            f"ended, so this reaches the run's recipient: {pending.next_action()}."
        )
        return [
            _notify_group_review(
                conn,
                execution,
                lambda _route: body,
                f"{REVIEW_WAKE_PREFIX}{execution_id}:group",
            )
        ]
    deliveries = []
    for member in members[:1] if owner_live else members:
        project_id = _project_id(conn, member)
        if project_id is None:
            continue
        item_ref = render_item_ref(conn, member)

        def body_for_route(route: str, item_ref: str = item_ref) -> str:
            if owner_live:
                return f"{stopped} Owning session {owner}: {pending.next_action()}."
            reached = (
                f"{item_ref}'s claim holder"
                if route == HOLDER
                else f"{item_ref}'s project steering seat (no live claim holder)"
            )
            return (
                f"{stopped} Its capture session {owner or 'unrecorded'} has "
                f"ended, so this reaches {reached}: {pending.next_action()}."
            )

        deliveries.append(
            push_notice(
                conn,
                item_id=member,
                project_id=project_id,
                owner_session_id=owner if owner_live else None,
                body_for_route=body_for_route,
                # Distinct from the finished-walk notice: a walk that reached
                # awaiting review and then stopped owes new instructions.
                idempotency_key=(
                    f"{REVIEW_WAKE_PREFIX}{execution_id}:"
                    f"{'owner' if owner_live else member}"
                ),
                now=now,
            )
        )
    return deliveries
