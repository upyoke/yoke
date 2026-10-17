"""Retry a member's held close-out when the QA record blocking it settles.

A member whose item QA a run accepted can still be refused at close-out by
one of its own records: a verdictless capture, an unwaived source
requirement, a live plan execution. The holder settles that record in a
different call — a verdict, a waiver, a supersession, a withdrawal, a plan
execution's end — and nothing else re-reads the refused member, so it sat at
release wait until somebody noticed.

Each of those writes calls :func:`after_record_settled` once its record is
committed. It re-runs the same acceptance close-out
(:func:`notify_item_qa_accepted`) for every executing run whose item QA has
already accepted the member, and replays any settling run the item held
open. There is no separate hold: the refused member is found again from the
run membership and the gate's own readers. A retry that refuses again sends
its new reason; one that cannot run is reported and never reverses the
committed record.
"""

from __future__ import annotations

from typing import Any, Optional

from yoke_core.domain.project_identity import render_item_ref
from yoke_core.domain.schema_common import _table_exists


def _requirement_item(conn: Any, requirement_id: int) -> Optional[int]:
    row = conn.execute(
        "SELECT COALESCE(deployment_member_item_id,item_id) FROM qa_requirements "
        "WHERE id=%s",
        (int(requirement_id),),
    ).fetchone()
    value = None if row is None else row[0]
    return None if value is None else int(value)


def _accepting_runs(conn: Any, item_id: int) -> list[str]:
    """Executing, not yet settling runs that carry this member."""
    if not all(
        _table_exists(conn, name)
        for name in ("deployment_runs", "deployment_run_items")
    ):
        return []
    rows = conn.execute(
        "SELECT dr.id FROM deployment_runs dr "
        "JOIN deployment_run_items dri ON dri.run_id=dr.id "
        "WHERE dri.item_id=%s AND dr.status='executing' "
        "AND dr.settling_at IS NULL ORDER BY dr.id",
        (int(item_id),),
    ).fetchall()
    return [str(row[0]) for row in rows]


def retry_member_close_out(conn: Any, *, item_id: int) -> list[str]:
    """Re-run the accepted-member close-out on every run that accepted it.

    Returns one ``"<run>: <result>"`` line per attempt. A run whose item QA
    still owes this member anything is skipped: its own stage settlement
    announces acceptance, and withdrawing its waits here would be early.
    """
    from yoke_core.domain.deployment_qa_member_acceptance_notice import (
        notify_item_qa_accepted,
    )
    from yoke_core.domain.deployment_qa_run_acceptance import (
        item_qa_acceptance_blockers,
    )
    from yoke_core.domain.settling_run_replay import settlement_active

    if settlement_active():
        return []
    results = []
    for run_id in _accepting_runs(conn, int(item_id)):
        try:
            if item_qa_acceptance_blockers(conn, run_id=run_id, item_id=int(item_id)):
                continue
            result = notify_item_qa_accepted(conn, run_id=run_id, item_id=int(item_id))
        except Exception as exc:  # noqa: BLE001 - never reverse a settled record
            result = f"failed: {exc}"
        if result.startswith("failed:"):
            conn.rollback()  # leave the caller a usable connection
            print(
                f"Close-out retry for {render_item_ref(conn, int(item_id))} on run "
                f"{run_id} did not finish ({result}). Its settled record stays "
                f"recorded; read `yoke deployment-runs get {run_id}` and re-drive "
                f"it with `yoke watch deploy -- {run_id}`."
            )
        results.append(f"{run_id}: {result or 'nothing owed'}")
    return results


def after_record_settled(
    conn: Any, *, item_id: Optional[int] = None, requirement_id: Optional[int] = None
) -> None:
    """Follow a committed settling QA write with every close-out it unblocks."""
    from yoke_core.domain.settling_run_replay import replay_settling_runs_for_item

    if item_id is None and requirement_id is not None:
        item_id = _requirement_item(conn, int(requirement_id))
    if item_id is None:
        return
    retry_member_close_out(conn, item_id=int(item_id))
    replay_settling_runs_for_item(conn, item_id=int(item_id))


def after_verdict_recorded(conn: Any, run_id: int) -> None:
    """Follow one committed QA run verdict with the close-outs it unblocks."""
    row = conn.execute(
        "SELECT qa_requirement_id FROM qa_runs WHERE id=%s AND verdict IS NOT NULL",
        (int(run_id),),
    ).fetchone()
    if row is not None:
        after_record_settled(conn, requirement_id=int(row[0]))


__all__ = ["after_record_settled", "after_verdict_recorded", "retry_member_close_out"]
