"""Tell each moved member owner that item QA now waits on the successor.

Skipped: plan-only members, members mid-walk, and manual-only members whose
claim holder already holds a future scheduled recheck.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from yoke_core.domain.db_savepoint import SavepointLostError, savepoint
from yoke_core.domain.deployment_run_driver_notice import push_member_notice
from yoke_core.domain.session_message_types import SessionMessageError

_SEND_SAVEPOINT = "_yoke_moved_member_qa_notice"


def item_qa_stage_name(stages: Sequence[Mapping[str, Any]]) -> str:
    """The flow's item-scoped QA stage, or ``item-qa`` when it has not named one."""
    for stage in stages:
        if stage.get("step_runner") == "qa" and stage.get("scope") == "item":
            name = str(stage.get("name") or "").strip()
            if name:
                return name
    return "item-qa"


def moved_member_body(
    *, item_ref: str, old_id: str, new_id: str, stage_name: str
) -> str:
    """One notice: QA moved, and the predecessor wake is no longer the command."""
    return (
        f"{item_ref}'s QA moved from run {old_id} to run {new_id}. "
        f"It opens when {new_id} reaches item QA stage {stage_name!r}. "
        "The successor's QA dispatch will wake you; do not act on the "
        "predecessor's wake."
    )


def _member_rows(conn: Any, item_ids: Sequence[int]) -> list[dict[str, Any]]:
    """One read for every moved member. The lock window stays the same at any size."""
    ids = sorted({int(item_id) for item_id in item_ids})
    if not ids:
        return []
    rows = conn.execute(
        "SELECT i.id, i.project_id, i.project_sequence, p.slug, p.public_item_prefix "
        "FROM items i JOIN projects p ON p.id=i.project_id "
        "WHERE i.id=ANY(%s) ORDER BY i.id",
        (ids,),
    ).fetchall()
    if len(rows) != len(ids):
        raise ValueError(
            "moved_member_qa_notice_failed: a moved member disappeared "
            "during takeover; retry the creation"
        )
    return [
        {
            "id": row["id"],
            "project_id": row["project_id"],
            "project_sequence": row["project_sequence"],
            "slug": row["slug"],
            "public_item_prefix": row["public_item_prefix"],
        }
        for row in rows
    ]


def _all_manual_members(conn: Any, new_id: str, item_ids: Sequence[int]) -> set[int]:
    """Members whose every moved open requirement is manual-wake."""
    from yoke_contracts.qa_case_wake_path import MANUAL

    ids = sorted({int(item_id) for item_id in item_ids})
    if not ids:
        return set()
    rows = conn.execute(
        "SELECT q.deployment_member_item_id FROM qa_requirements q "
        "WHERE q.deployment_run_id=%s AND q.deployment_member_item_id=ANY(%s) "
        "AND q.waived_at IS NULL AND q.superseded_at IS NULL "
        "AND q.retracted_at IS NULL "
        "AND NOT EXISTS (SELECT 1 FROM qa_runs r WHERE r.qa_requirement_id=q.id) "
        "GROUP BY q.deployment_member_item_id "
        "HAVING bool_and(q.wake_path IS NOT DISTINCT FROM %s)",
        (new_id, ids, MANUAL),
    ).fetchall()
    return {int(row[0]) for row in rows}


def recheck_holding_members(
    conn: Any, *, new_id: str, item_ids: Sequence[int], project_id: int
) -> set[int]:
    """Members a takeover need not wake: their holder already set its recheck.

    All must hold: the notice would reach the claim holder (not the steering
    seat), that holder has a future unconsumed scheduled wake, and every moved
    open requirement of the member is manual-wake. The holder's own timer is
    its next look; an automatic requirement still needs the successor's wake.
    """
    from yoke_contracts.timestamps import utc_now
    from yoke_core.domain.merge_queue_landing_notice import (
        HOLDER,
        resolve_lane_recipient,
    )
    from yoke_core.domain.session_scheduled_wake import pending_session_wake_holders

    holders: dict[int, str] = {}
    for item_id in sorted(_all_manual_members(conn, new_id, item_ids)):
        session_id, _, route = resolve_lane_recipient(
            conn, item_id=item_id, project_id=project_id
        )
        if session_id and route == HOLDER:
            holders[item_id] = session_id
    timed = pending_session_wake_holders(conn, holders.values(), now=utc_now())
    return {item_id for item_id, session in holders.items() if session in timed}


def notify_moved_member_qa(
    conn: Any,
    *,
    old_id: str,
    new_id: str,
    item_ids: Sequence[int],
    stages: Sequence[Mapping[str, Any]],
) -> None:
    """Reach each moved member once, without a query per member.

    A recipient the hook cannot reach does not undo the move. The takeover
    is already durable in this transaction; the notice is the wake.
    """
    from yoke_contracts.public_ref import format_item_ref
    from yoke_core.domain.merge_queue_landing_notice import addressable_items

    from yoke_core.domain.deployment_qa_plan_ownership import (
        open_walk_members,
        plan_only_members,
    )

    stage_name = item_qa_stage_name(stages)
    # A member owing only plans has nothing to run; its plan groups moved whole.
    # A member mid-walk keeps walking on its carried execution; telling it to
    # wait would stop a walk that may pass on the newer build. A manual-only
    # member whose holder holds a scheduled recheck keeps sleeping until it.
    skipped = plan_only_members(conn, new_id, item_ids) | open_walk_members(
        conn, new_id, item_ids
    )
    rows = [
        row for row in _member_rows(conn, item_ids) if int(row["id"]) not in skipped
    ]
    by_project: dict[int, list[dict[str, Any]]] = {}
    for row in rows:
        by_project.setdefault(int(row["project_id"]), []).append(row)
    for project_id, members in by_project.items():
        reachable = addressable_items(
            conn,
            item_ids=[int(row["id"]) for row in members],
            project_id=project_id,
        ) - recheck_holding_members(
            conn,
            new_id=new_id,
            item_ids=[int(row["id"]) for row in members],
            project_id=project_id,
        )
        for row in members:
            item_id = int(row["id"])
            if item_id not in reachable:
                continue
            item_ref = format_item_ref(
                row["slug"], row["public_item_prefix"], row["project_sequence"]
            )
            body = moved_member_body(
                item_ref=item_ref,
                old_id=old_id,
                new_id=new_id,
                stage_name=stage_name,
            )
            try:
                with savepoint(conn, _SEND_SAVEPOINT, owns=False):
                    push_member_notice(
                        conn,
                        item_id=item_id,
                        project_id=project_id,
                        body_for_route=lambda route, body=body: body,
                        idempotency_key=f"deployment-qa-moved:{new_id}:{item_id}",
                    )
            except SavepointLostError:
                raise
            except SessionMessageError:
                continue


__all__ = [
    "item_qa_stage_name",
    "moved_member_body",
    "notify_moved_member_qa",
    "recheck_holding_members",
]
