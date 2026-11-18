"""Recognize a final member delivered before its sibling QA completes.

Only a selected flow with no shared QA or human approval, whose last
substantive stage is item QA, can discharge one member while its run remains
executing. Trailing no-op auto stages carry no further delivery obligation.
The QA acceptance reader verifies the current deployment receipt, candidate,
cases, and verdict for that member.

A supplemental QA run -- the same release proving the item on another
persistent environment, beside the completion run that delivers it -- never
delivers, so it is never the item's completion run. Its accepted final item
QA still answers that environment's source obligations while the run is
executing: :func:`member_qa_answer_ready` reads it on its own terms instead
of asking whether it is the delivery.
"""

from __future__ import annotations

from typing import Any

from yoke_core.domain.deployment_qa_run_acceptance import (
    item_qa_acceptance_blockers,
    pinned_stages,
)
from yoke_core.domain.deployment_qa_source_obligation import latest_completion_run


def independent_member_delivery_ready(conn: Any, *, item_id: int, run_id: str) -> bool:
    """True only after this member's final production QA is accepted.

    A run-level QA or human-approval stage is shared, wherever it appears in
    the flow. Either keeps every final member open until the run succeeds. A
    failed or cancelled run never qualifies. The selected-flow membership and
    frozen final intent are required even if another run carries the item.
    """
    run = latest_completion_run(conn, int(item_id))
    if run is None or run["id"] != str(run_id):
        return False
    return int(item_id) in latest_members_delivery_ready(conn, {int(item_id): run})


def latest_members_delivery_ready(
    conn: Any, latest: dict[int, dict[str, Any]]
) -> frozenset[int]:
    """:func:`independent_member_delivery_ready` for items whose latest
    completion run the caller already read, keyed by item; one acceptance
    read per executing run rather than per item."""
    by_run: dict[str, list[int]] = {}
    for item_id, run in latest.items():
        if run["status"] == "executing":
            by_run.setdefault(str(run["id"]), []).append(int(item_id))
    ready: set[int] = set()
    for run_id, item_ids in by_run.items():
        ready |= final_item_qa_accepted_items(conn, run_id=run_id, item_ids=item_ids)
    return frozenset(ready)


def member_qa_answer_ready(conn: Any, *, item_id: int, run_id: str) -> bool:
    """Whether an executing member run's item QA answers its sources now.

    The completion run answers only once it has independently delivered the
    member. A supplemental QA run of the same release answers as soon as its
    final item QA is accepted; delivery stays the completion run's own gate.
    """
    from yoke_core.domain.deployment_run_member_targeting import supplemental_qa_run

    if not supplemental_qa_run(conn, run_id=str(run_id), item_id=int(item_id)):
        return independent_member_delivery_ready(
            conn, item_id=int(item_id), run_id=str(run_id)
        )
    status = conn.execute(
        "SELECT status FROM deployment_runs WHERE id=%s", (str(run_id),)
    ).fetchone()
    if status is None or str(status["status"] or "") != "executing":
        return False
    return final_item_qa_accepted(conn, item_id=int(item_id), run_id=str(run_id))


def final_item_qa_accepted(conn: Any, *, item_id: int, run_id: str) -> bool:
    """The run's last substantive stage is this member's accepted item QA."""
    return int(item_id) in final_item_qa_accepted_items(
        conn, run_id=str(run_id), item_ids=(int(item_id),)
    )


def final_item_qa_accepted_items(
    conn: Any, *, run_id: str, item_ids
) -> frozenset[int]:
    """:func:`final_item_qa_accepted` for several members of one run.

    The membership rows come back in one read and the run's stage shape is
    judged once; only each member's own acceptance blockers stay per item.
    """
    from yoke_core.domain.deployment_run_composition_freeze import DELIVERY_INTENT_FINAL

    ids = tuple(dict.fromkeys(int(value) for value in item_ids))
    if not ids:
        return frozenset()
    rows = conn.execute(
        "SELECT dri.item_id,dri.delivery_intent,e.name AS target_name "
        "FROM deployment_run_items dri "
        "JOIN deployment_runs dr ON dr.id=dri.run_id "
        "LEFT JOIN environments e ON e.id=dr.target_environment_id "
        f"WHERE dri.run_id=%s AND dri.item_id IN ({','.join('%s' for _ in ids)})",
        (str(run_id), *ids),
    ).fetchall()
    finals = [
        row
        for row in rows
        if str(row["delivery_intent"] or "") == DELIVERY_INTENT_FINAL
        and str(row["target_name"] or "")
    ]
    if not finals or not _final_stage_is_item_qa(
        pinned_stages(conn, str(run_id)), str(finals[0]["target_name"])
    ):
        return frozenset()
    return frozenset(
        int(row["item_id"])
        for row in finals
        if not item_qa_acceptance_blockers(
            conn, run_id=str(run_id), item_id=int(row["item_id"])
        )
    )


def _final_stage_is_item_qa(stages: list, target_name: str) -> bool:
    """The last substantive stage is item-scoped QA on the run's target."""
    qa_stages = [
        stage
        for stage in stages
        if stage.get("stage_kind") == "qa" or stage.get("step_runner") == "qa"
    ]
    if (
        not qa_stages
        or any(stage.get("scope") == "run" for stage in qa_stages)
        or any(stage.get("step_runner") == "human-approval" for stage in stages)
    ):
        return False
    final_stage = qa_stages[-1]
    target = final_stage.get("target") or {}
    trailing = stages[stages.index(final_stage) + 1 :]
    return not (
        any(
            stage.get("step_runner") != "auto" or stage.get("stage_kind") != "execution"
            for stage in trailing
        )
        or final_stage.get("scope") != "item"
        or not isinstance(target, dict)
        or target.get("kind") != "persistent_environment"
        or target.get("environment") != target_name
    )


__all__ = [
    "final_item_qa_accepted",
    "final_item_qa_accepted_items",
    "independent_member_delivery_ready",
    "member_qa_answer_ready",
]
