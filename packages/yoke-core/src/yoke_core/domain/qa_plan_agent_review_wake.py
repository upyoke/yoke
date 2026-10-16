"""Resume the owner of an item-scoped capture for independent QA review."""

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


def notify_scoped_agent_review(conn: Any, execution: Mapping[str, Any]) -> str:
    """Use the item-QA wake route, with a distinct notice for this execution.

    The earlier stage wait may already be delivered. Its key cannot also
    identify the later review continuation, which is new work for the owner.
    """
    member_id = execution.get("deployment_member_item_id")
    run_id = execution.get("deployment_run_id")
    stage = execution.get("deployment_stage")
    if (
        not member_id
        and run_id
        and stage
        and ((execution.get("execution_target") or {}).get("deployment") or {}).get(
            "shared_plan"
        )
    ):
        from yoke_core.domain.deployment_qa_shared_plans import (
            execution_subject,
            group_members,
        )

        group = execution_subject(conn, execution)
        members = group_members(conn, group, execution["execution_target"])
        member_id = members[0] if members else None
    if not member_id or not run_id or not stage:
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
            "--deployment-run-id",
            str(run_id),
            "--stage",
            str(stage),
            "--member",
            item_ref,
            "--project",
            str(row[1]),
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
            "awaiting_agent_review. Independent review is pending; no QA "
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
